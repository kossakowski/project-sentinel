"""Phase 2 acceptance tests for GeoWeighter (deterministic geography weighting)."""

from sentinel.alerts.policy import AlertPolicy, ChannelClass, EventDecision, GeoTier, Relation
from sentinel.classification.geo_weighter import GeoWeighter


# 8. [2.5] target=RU, attacker_is_nato=true -> geo_tier HIGH (NATO attacks Russia).
def test_geo_weighter_nato_attacks_russia_high(config):
    gw = GeoWeighter(config)
    assert gw.geo_tier("RU", attacker_is_nato=True) is GeoTier.HIGH
    # A non-NATO attacker striking Russia stays LOW.
    assert gw.geo_tier("RU", attacker_is_nato=False) is GeoTier.LOW
    # It follows config, not a hardcoded "RU".
    config.geography.nato_attack_targets = []
    assert gw.geo_tier("RU", attacker_is_nato=True) is GeoTier.LOW


# 9. [2.11] kinetic event, target_country=PL, LLM urgency 4 -> floored >= 9.
def test_geo_weighter_floors_poland_kinetic(config):
    gw = GeoWeighter(config)
    assert gw.floor_urgency("missile_strike", "PL", 4) >= 9


# 9a. [2.11] kinetic event, target_country=RO, LLM urgency 7 -> stays 7 (no floor; NOTIFY, not CALL).
def test_geo_weighter_no_floor_other_nato(config):
    gw = GeoWeighter(config)
    assert gw.floor_urgency("missile_strike", "RO", 7) == 7


# 9b. [2.11] the floor follows geography.floor_countries, not a hardcoded == "PL".
def test_floor_countries_config_driven(config):
    gw = GeoWeighter(config)

    # Empty floor set: a PL kinetic urgency-4 event is NOT floored.
    config.geography.floor_countries = []
    assert gw.floor_urgency("missile_strike", "PL", 4) == 4

    # floor_countries=[RO]: an RO kinetic urgency-4 event IS floored >= 9.
    config.geography.floor_countries = ["RO"]
    assert gw.floor_urgency("missile_strike", "RO", 4) >= 9


# 9c. [2.11, 2.5b] event_type=debris_found, target_country=PL, LLM urgency 8 -> stays 8 (debris is not kinetic).
def test_debris_not_floored(config):
    gw = GeoWeighter(config)
    assert gw.floor_urgency("debris_found", "PL", 8) == 8


# 10. [2.5b] kinetic derived from config-driven event_type set; troop_movement/debris_found/
#     official_statement are NOT kinetic; the definition follows config.
def test_geo_weighter_kinetic_from_event_type(config):
    gw = GeoWeighter(config)

    # A type in the default kinetic set is kinetic.
    assert gw.is_kinetic("missile_strike") is True
    # troop_movement and the two 0.15 meta types are NOT kinetic (absent from the default set).
    assert gw.is_kinetic("troop_movement") is False
    assert gw.is_kinetic("debris_found") is False
    assert gw.is_kinetic("official_statement") is False
    assert "debris_found" not in config.geography.kinetic_event_types
    assert "official_statement" not in config.geography.kinetic_event_types

    # It follows config: move a type in/out of the set.
    config.geography.kinetic_event_types = ["troop_movement"]
    assert gw.is_kinetic("troop_movement") is True
    assert gw.is_kinetic("missile_strike") is False


def test_unresolved_target_is_unknown(config):
    """An unresolved / placeholder target country yields UNKNOWN (fail-open at AlertPolicy)."""
    gw = GeoWeighter(config)
    assert gw.geo_tier(None) is GeoTier.UNKNOWN
    assert gw.geo_tier("unknown") is GeoTier.UNKNOWN
    assert gw.geo_tier("") is GeoTier.UNKNOWN


def test_tier_for_affected_fail_open(config):
    """Event-level tier: HIGH for a monitored country, LOW for interior UA, UNKNOWN when empty."""
    gw = GeoWeighter(config)
    assert gw.tier_for_affected(["PL"]) is GeoTier.HIGH
    assert gw.tier_for_affected(["UA"]) is GeoTier.LOW
    assert gw.tier_for_affected([]) is GeoTier.UNKNOWN
    assert gw.tier_for_affected(["unknown", ""]) is GeoTier.UNKNOWN


# --------------------------------------------------------------------------
# Unrecognized country tokens must be UNKNOWN (fail-open), never LOW.
# --------------------------------------------------------------------------
def test_unrecognized_token_is_unknown_not_low(config):
    """A non-ISO / unknown-country token is UNRESOLVED -> UNKNOWN, so a 9-10 still calls.

    A LOW tier DEMOTES a call-urgency event to an SMS. Treating a token the config
    does not know (a country name the classifier emitted instead of the ISO code, a
    misspelling, an unmonitored state) as LOW would silently turn a Poland
    urgency-9/10 phone call into an SMS. Only a KNOWN, non-high-tier country may
    demote.
    """
    gw = GeoWeighter(config)
    policy = AlertPolicy(config)

    for token in ("Ruritania", "XX", "warszawa"):
        assert gw.geo_tier(token) is GeoTier.UNKNOWN, token
        assert gw.tier_for_affected([token]) is GeoTier.UNKNOWN, token
        intent = policy.decide(EventDecision(Relation.NEW), urgency=10, geo_tier=gw.geo_tier(token))
        assert intent.channel_class is ChannelClass.CALL, token

    # A KNOWN non-high-tier country (interior Ukraine) still demotes -- that is the
    # false-positive class the geo gate exists for.
    assert gw.geo_tier("UA") is GeoTier.LOW
    assert policy.decide(EventDecision(Relation.NEW), urgency=10, geo_tier=GeoTier.LOW).channel_class is (
        ChannelClass.NOTIFY
    )


def test_country_names_resolve_from_config(config):
    """Country NAME / native-name tokens resolve to their ISO code via config (no gazetteer)."""
    gw = GeoWeighter(config)
    assert gw.resolve_country("PL") == "PL"
    assert gw.resolve_country("Poland") == "PL"
    assert gw.resolve_country("polska") == "PL"
    assert gw.resolve_country("Ruritania") is None
    assert gw.resolve_country("unknown") is None

    # A name token weighs exactly like its code -- including the Poland kinetic floor.
    assert gw.geo_tier("Polska") is GeoTier.HIGH
    assert gw.floor_urgency("missile_strike", "Polska", 4) >= 9


# --------------------------------------------------------------------------
# Floor basis (owner-resolved): target_country first, affected only as fallback.
# --------------------------------------------------------------------------
def test_floor_basis_is_target_country(config):
    """A kinetic strike TARGETING Ukraine that lists PL among affected is NOT floored."""
    gw = GeoWeighter(config)
    assert gw.floor_for_event("missile_strike", "UA", ["UA", "PL"], 4) == 4
    assert gw.weigh("UA", False, "missile_strike", 4, ["UA", "PL"]).urgency == 4


def test_floor_falls_back_to_affected_when_target_unresolved(config):
    """An unresolved target on a kinetic story naming Polish soil STILL floors (fail-open)."""
    gw = GeoWeighter(config)
    assert gw.floor_for_event("missile_strike", "unknown", ["PL"], 4) >= 9
    assert gw.floor_for_event("missile_strike", None, ["PL"], 4) >= 9
    assert gw.weigh(None, False, "missile_strike", 4, ["PL"]).urgency >= 9


# --------------------------------------------------------------------------
# event_tier: both geo signals, biased toward firing.
# --------------------------------------------------------------------------
def test_event_tier_combines_target_and_affected(config):
    gw = GeoWeighter(config)
    # Target resolves HIGH -> HIGH.
    assert gw.event_tier("PL", []) is GeoTier.HIGH
    # Target LOW but a HIGH-tier country is affected -> HIGH (a botched target must
    # never demote a Poland-affected event).
    assert gw.event_tier("UA", ["PL"]) is GeoTier.HIGH
    # Target unresolved, affected LOW -> LOW.
    assert gw.event_tier(None, ["UA"]) is GeoTier.LOW
    # Nothing resolves -> UNKNOWN (fail-open at call urgency).
    assert gw.event_tier(None, []) is GeoTier.UNKNOWN
    assert gw.event_tier("unknown", ["unknown"]) is GeoTier.UNKNOWN
    # NATO attacking Russia -> HIGH via the target.
    assert gw.event_tier("RU", ["RU"], True) is GeoTier.HIGH
    assert gw.event_tier("RU", ["RU"], False) is GeoTier.LOW


def test_weigh_aggregates_floor_tier_and_kinetic(config):
    """weigh() is the live aggregate seam: floored urgency + event tier + kinetic flag."""
    gw = GeoWeighter(config)

    weighted = gw.weigh("PL", False, "missile_strike", 4, ["PL"])
    assert weighted.urgency >= 9
    assert weighted.geo_tier is GeoTier.HIGH
    assert weighted.kinetic is True

    debris = gw.weigh("PL", False, "debris_found", 8, ["PL"])
    assert debris.urgency == 8
    assert debris.geo_tier is GeoTier.HIGH
    assert debris.kinetic is False
