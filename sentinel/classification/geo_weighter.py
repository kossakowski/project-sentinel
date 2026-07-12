"""GeoWeighter -- deterministic post-LLM geography weighting.

Computes the ``geo_tier`` of an event from its physical target country (and
whether the attacker is NATO), derives a ``kinetic`` flag from the classifier
``event_type`` against a config-driven set, and floors kinetic strikes on
``geography.floor_countries`` (default ``[PL]``) to the call tier.

No LLM / network I/O: purely a function of the classifier output and config, so
it is fully deterministic and unit-testable. Country resolution stays
country-level and LLM-driven -- there is NO gazetteer / city list here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sentinel.config import SentinelConfig

if TYPE_CHECKING:
    from sentinel.alerts.policy import GeoTier

# Placeholder tokens the classifier emits when it cannot resolve a country; they
# carry no location signal and must not act as a match key.
_UNKNOWN_TOKENS = {"", "UNKNOWN", "NONE"}


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
    """The geography-weighted view of a classification."""

    urgency: int
    geo_tier: GeoTier
    kinetic: bool


class GeoWeighter:
    """Deterministic geo-tier / kinetic / floor computations from config."""

    def __init__(self, config: SentinelConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Kinetic classification
    # ------------------------------------------------------------------
    def is_kinetic(self, event_type: str | None) -> bool:
        """True if ``event_type`` is in the config-driven kinetic set.

        The default set excludes ``debris_found`` and ``official_statement`` --
        inert-debris recovery and reaction stories are not kinetic strikes.
        """
        return (event_type or "") in set(self.config.geography.kinetic_event_types)

    # ------------------------------------------------------------------
    # Geo tier
    # ------------------------------------------------------------------
    @staticmethod
    def _norm(country: str | None) -> str | None:
        if not country:
            return None
        code = country.strip().upper()
        return None if code in _UNKNOWN_TOKENS else code

    def _high_set(self) -> set[str]:
        return {c.strip().upper() for c in self.config.geography.high_tier_countries}

    def geo_tier(self, target_country: str | None, attacker_is_nato: bool = False) -> GeoTier:
        """HIGH if the target is a high-tier country OR (target == RU AND attacker is NATO).

        UNKNOWN when the target is unresolved (fail-open handled by AlertPolicy);
        LOW for routine inside-Ukraine / interior-Moldova targets.
        """
        geo_tier = _geo_tier_enum()
        code = self._norm(target_country)
        if code is None:
            return geo_tier.UNKNOWN
        if code in self._high_set():
            return geo_tier.HIGH
        if code == "RU" and attacker_is_nato:
            return geo_tier.HIGH
        return geo_tier.LOW

    def tier_for_affected(self, affected_countries: list[str] | None, attacker_is_nato: bool = False) -> GeoTier:
        """Event-level geo tier from a list of affected countries (fail-open).

        HIGH if any concrete affected country is high-tier (or RU + NATO attacker);
        UNKNOWN if no concrete country is named (so AlertPolicy fails a call-tier
        event toward firing); LOW when concrete non-high-tier countries are named.
        """
        geo_tier = _geo_tier_enum()
        high = self._high_set()
        concrete = {code for c in (affected_countries or []) if (code := self._norm(c))}
        if concrete & high:
            return geo_tier.HIGH
        if not concrete:
            return geo_tier.UNKNOWN
        if attacker_is_nato and "RU" in concrete:
            return geo_tier.HIGH
        return geo_tier.LOW

    # ------------------------------------------------------------------
    # Poland-only kinetic floor
    # ------------------------------------------------------------------
    def floor_urgency(self, event_type: str | None, target_country: str | None, urgency: int) -> int:
        """Floor a kinetic strike on a floor-country to the call tier (>= 9).

        Config-driven via ``geography.floor_countries`` (default ``[PL]``). Only
        raises urgency, never lowers it. Debris-recovery and reaction stories are
        excluded because they are not kinetic (2.5b carve-out).
        """
        code = self._norm(target_country)
        if code is None:
            return urgency
        floor_set = {c.strip().upper() for c in self.config.geography.floor_countries}
        if code in floor_set and self.is_kinetic(event_type):
            return max(urgency, _call_tier_min(self.config))
        return urgency

    def weigh(
        self,
        target_country: str | None,
        attacker_is_nato: bool,
        event_type: str | None,
        urgency: int,
    ) -> WeightedResult:
        """Full weighting: floored urgency + geo tier + kinetic flag."""
        return WeightedResult(
            urgency=self.floor_urgency(event_type, target_country, urgency),
            geo_tier=self.geo_tier(target_country, attacker_is_nato),
            kinetic=self.is_kinetic(event_type),
        )
