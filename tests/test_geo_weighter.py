"""Phase 2 acceptance tests for GeoWeighter (deterministic geography weighting)."""

from sentinel.alerts.policy import GeoTier
from sentinel.classification.geo_weighter import GeoWeighter


# 8. [2.5] target=RU, attacker_is_nato=true -> geo_tier HIGH (NATO attacks Russia).
def test_geo_weighter_nato_attacks_russia_high(config):
    gw = GeoWeighter(config)
    assert gw.geo_tier("RU", attacker_is_nato=True) is GeoTier.HIGH
    # A non-NATO attacker striking Russia stays LOW.
    assert gw.geo_tier("RU", attacker_is_nato=False) is GeoTier.LOW


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
