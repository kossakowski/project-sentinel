"""GeoWeighter -- deterministic post-LLM geography weighting.

Computes the ``geo_tier`` of an event from its physical target country (and
whether the attacker is NATO), derives a ``kinetic`` flag from the classifier
``event_type`` against a config-driven set, and floors kinetic strikes on
``geography.floor_countries`` (default ``[PL]``) to the call tier.

Country tokens are resolved against a config-driven country set (the ISO codes in
the ``geography.*`` tier lists plus the English / native names carried by
``monitoring.target_countries`` / ``monitoring.aggressor_countries`` and
``geography.country_names``). A token
that does not resolve to a KNOWN country is UNKNOWN, never LOW: an unresolved
geo at call urgency fails toward firing (AlertPolicy 2.5a), while a LOW tier
demotes a call to an SMS. Treating a disobedient token (e.g. the country NAME
instead of its ISO code) as LOW would silently turn a Poland urgency-9/10 phone
call into an SMS.

No LLM / network I/O: purely a function of the classifier output and config, so
it is fully deterministic and unit-testable. Country resolution stays
country-level -- there is NO gazetteer / city list here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sentinel.config import SentinelConfig

if TYPE_CHECKING:
    from sentinel.alerts.policy import GeoTier

# Placeholder tokens the classifier emits when it cannot resolve a country; they
# carry no location signal and must not act as a match key. Single definition,
# shared with the corroborator's grouping keys so "placeholder" means exactly the
# same thing in geo weighting and in event grouping.
UNKNOWN_COUNTRY_TOKENS = frozenset({"", "UNKNOWN", "NONE"})


# ``sentinel.alerts.policy`` lives behind the ``sentinel.alerts`` package __init__,
# which eagerly imports the alert state machine (which in turn imports THIS module).
# Importing policy at module top would therefore create an import cycle when the
# classification package loads first. The GeoTier / call_tier_min symbols are only
# needed at call time, so import them lazily here.
def _geo_tier_enum() -> type[GeoTier]:
    from sentinel.alerts.policy import GeoTier

    return GeoTier


def _call_tier_min(config: SentinelConfig) -> int:
    from sentinel.alerts.policy import call_tier_min

    return call_tier_min(config)


@dataclass(frozen=True)
class WeightedResult:
    """The geography-weighted view of a classification.

    ``urgency`` is the floored urgency (2.11), ``geo_tier`` the event-level tier
    AlertPolicy's call gate consumes, ``kinetic`` the 2.5b flag.
    """

    urgency: int
    geo_tier: GeoTier
    kinetic: bool


class GeoWeighter:
    """Deterministic geo-tier / kinetic / floor computations from config."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        # Config is immutable for the life of the process, so the token -> ISO alias
        # map is built once here instead of on every resolve_country() call (which
        # runs once per country per article).
        self._aliases = self._build_country_aliases()

    # ------------------------------------------------------------------
    # Kinetic classification
    # ------------------------------------------------------------------
    def is_kinetic(self, event_type: str | None) -> bool:
        """True if ``event_type`` is in the config-driven kinetic set.

        The default set excludes ``debris_found`` and ``official_statement`` --
        inert-debris recovery and reaction stories are not kinetic strikes.

        The token is normalized (stripped + case-folded) before membership, and the
        config set the same way, so an off-case / whitespace-padded classifier token
        ("Missile_Strike", " missile_strike ") still matches -- exactly as
        ``resolve_country`` normalizes country tokens. The 2.11 Poland kinetic floor
        is a deterministic safety net whose whole premise is that the LLM's urgency
        number is unreliable; a second LLM formatting error on this string seam must
        not be able to silently disable it (which would drop a Poland strike into the
        NONE band and fire NO alert).
        """
        token = (event_type or "").strip().casefold()
        if not token:
            return False
        kinetic = {str(t).strip().casefold() for t in self.config.geography.kinetic_event_types}
        return token in kinetic

    # ------------------------------------------------------------------
    # Country resolution (config-driven; codes + names, no gazetteer)
    # ------------------------------------------------------------------
    def _build_country_aliases(self) -> dict[str, str]:
        """Every recognized country token -> its ISO code.

        Built from config only: the geography tier lists (bare ISO codes) plus the
        ``{code, name, name_native}`` objects in ``monitoring.target_countries`` /
        ``monitoring.aggressor_countries`` and ``geography.country_names``. So "PL",
        "Poland" and "Polska" all resolve to PL and "Ukraine" / "Ukraina" resolve to
        UA, while an unlisted token resolves to nothing (UNKNOWN).

        ``geography.country_names`` is what makes the LOW tier reachable by NAME: the
        tier lists carry only codes, and the monitored/aggressor blocks only name the
        countries Sentinel watches -- so without it a classifier emitting "Ukraine"
        would be UNKNOWN (fail-open to a call) instead of LOW (demoted to SMS).
        """
        geo = self.config.geography
        aliases: dict[str, str] = {}
        for raw in (*geo.high_tier_countries, *geo.low_tier_countries, *geo.nato_attack_targets):
            code = str(raw).strip().upper()
            if code:
                aliases[code] = code
        named = (
            *self.config.monitoring.target_countries,
            *self.config.monitoring.aggressor_countries,
            *geo.country_names,
        )
        for entry in named:
            code = str(entry.get("code", "")).strip().upper()
            if not code:
                continue
            aliases[code] = code
            for key in ("name", "name_native"):
                name = entry.get(key)
                if name:
                    aliases[str(name).strip().upper()] = code
        return aliases

    def resolve_country(self, country: str | None) -> str | None:
        """Resolve a classifier country token to a KNOWN ISO code, else ``None``.

        ``None`` means "unresolved" -- a placeholder token ("unknown"/"none"/""),
        a blank, or a token that is not a country this config knows about. Callers
        must treat unresolved as UNKNOWN (fail toward firing), never as LOW.
        """
        if not country:
            return None
        token = str(country).strip().upper()
        if token in UNKNOWN_COUNTRY_TOKENS:
            return None
        return self._aliases.get(token)

    def _high_set(self) -> set[str]:
        return {str(c).strip().upper() for c in self.config.geography.high_tier_countries}

    def _nato_attack_targets(self) -> set[str]:
        return {str(c).strip().upper() for c in self.config.geography.nato_attack_targets}

    # ------------------------------------------------------------------
    # Geo tier
    # ------------------------------------------------------------------
    def geo_tier(self, target_country: str | None, attacker_is_nato: bool = False) -> GeoTier:
        """HIGH if the target is a high-tier country OR (target == RU AND attacker is NATO).

        UNKNOWN when the target does not resolve to a known country (fail-open
        handled by AlertPolicy 2.5a); LOW for routine inside-Ukraine /
        interior-Moldova targets. ``geography.nato_attack_targets`` (default
        ``[RU]``) carries the R11 NATO-attacks-Russia case.
        """
        geo_tier = _geo_tier_enum()
        code = self.resolve_country(target_country)
        if code is None:
            return geo_tier.UNKNOWN
        if code in self._high_set():
            return geo_tier.HIGH
        if attacker_is_nato and code in self._nato_attack_targets():
            return geo_tier.HIGH
        return geo_tier.LOW

    def tier_for_affected(self, affected_countries: list[str] | None, attacker_is_nato: bool = False) -> GeoTier:
        """Event-level geo tier from a list of affected countries (fail-open).

        HIGH if any resolved affected country is high-tier (or a NATO-attack
        target with a NATO attacker); UNKNOWN if no country RESOLVES (so
        AlertPolicy fails a call-tier event toward firing); LOW only when the
        resolved countries are known and non-high-tier.
        """
        geo_tier = _geo_tier_enum()
        concrete = {code for c in (affected_countries or []) if (code := self.resolve_country(c))}
        if concrete & self._high_set():
            return geo_tier.HIGH
        if attacker_is_nato and (concrete & self._nato_attack_targets()):
            return geo_tier.HIGH
        if not concrete:
            return geo_tier.UNKNOWN
        return geo_tier.LOW

    def event_tier(
        self,
        target_country: str | None,
        affected_countries: list[str] | None,
        attacker_is_nato: bool = False,
    ) -> GeoTier:
        """The tier AlertPolicy's call gate consumes, from BOTH geo signals.

        The LLM's explicit ``target_country`` is the primary signal (2.5), but a
        HIGH-tier country named among ``affected_countries`` also lifts the event
        to HIGH: a botched/omitted target must never demote a Poland-affected
        urgency-9 to an SMS (prime directive -- fail toward firing). UNKNOWN only
        when NEITHER signal resolves.
        """
        geo_tier = _geo_tier_enum()
        target_tier = self.geo_tier(target_country, attacker_is_nato)
        if target_tier is geo_tier.HIGH:
            return geo_tier.HIGH
        affected_tier = self.tier_for_affected(affected_countries, attacker_is_nato)
        if affected_tier is geo_tier.HIGH:
            return geo_tier.HIGH
        if geo_tier.LOW in (target_tier, affected_tier):
            return geo_tier.LOW
        return geo_tier.UNKNOWN

    # ------------------------------------------------------------------
    # Poland-only kinetic floor
    # ------------------------------------------------------------------
    def floor_urgency(self, event_type: str | None, target_country: str | None, urgency: int) -> int:
        """Floor a kinetic strike on a floor-country to the call tier (>= 9).

        Config-driven via ``geography.floor_countries`` (default ``[PL]``). Only
        raises urgency, never lowers it. Debris-recovery and reaction stories are
        excluded because they are not kinetic (2.5b carve-out).
        """
        code = self.resolve_country(target_country)
        if code is None:
            return urgency
        floor_set = {str(c).strip().upper() for c in self.config.geography.floor_countries}
        if code in floor_set and self.is_kinetic(event_type):
            return max(urgency, _call_tier_min(self.config))
        return urgency

    def floor_for_event(
        self,
        event_type: str | None,
        target_country: str | None,
        affected_countries: list[str] | None,
        urgency: int,
    ) -> int:
        """Apply the 2.11 floor with the owner-resolved basis.

        The floor is applied to the LLM's ``target_country`` when it RESOLVES to a
        known country: a kinetic strike targeting Ukraine whose article also lists
        Poland among ``affected_countries`` (jets scrambled, "near the Polish
        border") is NOT a strike on Polish soil and must not be floored to a call.

        Only when the target is unresolved do we fall back to the affected
        countries -- a botched target on a kinetic story that names Polish soil
        still floors (2.5a's fail-open, applied to the floor).
        """
        code = self.resolve_country(target_country)
        if code is not None:
            return self.floor_urgency(event_type, code, urgency)
        for country in affected_countries or []:
            urgency = self.floor_urgency(event_type, country, urgency)
        return urgency

    def weigh(
        self,
        target_country: str | None,
        attacker_is_nato: bool,
        event_type: str | None,
        urgency: int,
        affected_countries: list[str] | None = None,
    ) -> WeightedResult:
        """Full weighting: floored urgency + event geo tier + kinetic flag.

        The single aggregate seam the classifier uses post-parse, so the floor
        basis (2.11 / target-first) and the tier derivation cannot drift apart.
        """
        return WeightedResult(
            urgency=self.floor_for_event(event_type, target_country, affected_countries, urgency),
            geo_tier=self.event_tier(target_country, affected_countries, attacker_is_nato),
            kinetic=self.is_kinetic(event_type),
        )
