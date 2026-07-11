"""Deterministic prompt-construction tests for Phase 0 geography correctness.

These tests are OFFLINE: they build the classifier prompt string in-process from
the module-level ``SYSTEM_PROMPT`` and ``USER_PROMPT_TEMPLATE`` constants and assert
on the rendered text. No network / Anthropic API calls, no client instantiation.
"""

from sentinel.classification.classifier import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


def _full_prompt() -> str:
    """Render the full classifier prompt (system + user) deterministically."""
    user = USER_PROMPT_TEMPLATE.format(
        source_name="TestSource",
        source_type="rss",
        language="en",
        published_at="2026-07-11T00:00:00+00:00",
        title="Test title",
        summary="Test summary",
    )
    return SYSTEM_PROMPT + "\n" + user


# ---------------------------------------------------------------------------
# 0.6 — scope widened to Romania; monitored set 9-10-eligible
# ---------------------------------------------------------------------------


def test_prompt_scope_includes_romania():
    """[0.6] System scope names Romania; the 9-10 clause includes RO; old EXCLUSIVELY gone."""
    prompt = _full_prompt()
    assert "targeting Poland, Lithuania, Latvia, Estonia, or Romania" in prompt
    assert "PL/LT/LV/EE/RO" in prompt
    # The root-cause defect string must be gone/revised.
    assert "EXCLUSIVELY for attacks directly targeting PL, LT, LV, or EE" not in prompt


# ---------------------------------------------------------------------------
# 0.6 — NATO attack ON Russia is HIGH-eligible
# ---------------------------------------------------------------------------


def test_prompt_nato_attack_on_russia_high():
    """[0.6] A NATO/NATO-member attack ON Russia is HIGH-eligible."""
    prompt = _full_prompt()
    assert "R11 NATO ATTACK ON RUSSIA" in prompt
    assert "attack ON Russian territory" in prompt
    assert "HIGH-eligible" in prompt


# ---------------------------------------------------------------------------
# 0.5 — target-country gate
# ---------------------------------------------------------------------------


def test_prompt_target_country_gate():
    """[0.5] An unnamed 'a NATO country' must not resolve to Poland / a monitored country."""
    prompt = _full_prompt()
    assert "TARGET-COUNTRY GATE" in prompt
    assert '"a NATO country"' in prompt
    assert "MUST NOT be resolved to Poland" in prompt
    assert "EXPLICITLY named" in prompt


# ---------------------------------------------------------------------------
# 0.7 — R4 demoted to confirmed-PL tie-break
# ---------------------------------------------------------------------------


def test_prompt_r4_scoped_to_confirmed_pl():
    """[0.7] R4 applies only after Poland is confirmed; no non-PL -> PL elevation."""
    prompt = _full_prompt()
    assert "ONLY after Poland is already confirmed" in prompt
    assert "MUST NOT promote a non-Polish incident to a Polish label" in prompt
    # The old promoting language must be gone.
    assert "Events involving Poland score higher than equivalent events" not in prompt


# ---------------------------------------------------------------------------
# 0.8 — explicit-country-only + physical-location rules preserved
# ---------------------------------------------------------------------------


def test_prompt_affected_countries_explicit_only():
    """[0.8] The explicit-country-only and physical-location rules are still present."""
    prompt = _full_prompt()
    # Physical-location attribution (L34-35 equivalent).
    assert "Score affected_countries based on the PHYSICAL LOCATION of the attack" in prompt
    # affected_countries lists only explicitly-named countries (L145-146 equivalent).
    assert "ONLY list countries EXPLICITLY mentioned in the article as attacked" in prompt
    # Do-not-assume-a-monitored-country (L36-37 equivalent).
    assert "do NOT assume it was a monitored country" in prompt


# ---------------------------------------------------------------------------
# 0.9 — inside-Ukraine LOW (~2) and inside-Russia LOW (~1)
# ---------------------------------------------------------------------------


def test_prompt_inside_ukraine_low():
    """[0.9] Inside-Ukraine = LOW (~2) and Ukrainian-attack-inside-Russia = LOW (~1)."""
    prompt = _full_prompt()
    assert "strike physically inside Ukraine" in prompt
    assert "= urgency 2" in prompt
    assert "A Ukrainian attack physically inside Russia = urgency 1" in prompt


# ---------------------------------------------------------------------------
# 0.14 — rubric-v2 geography ladder
# ---------------------------------------------------------------------------


def test_prompt_geography_ladder():
    """[0.14] Every rubric-v2 ladder element is present in the prompt."""
    prompt = _full_prompt()
    # Poland: direct attack 9-10.
    assert "Poland: a direct Russian attack (kinetic strike on Polish soil) = 9-10" in prompt
    # Poland: live airspace intrusion >= 9.
    assert "live airspace intrusion over Poland by attack-capable weapons = 9 or higher" in prompt
    # Poland: inert debris = 8.
    assert "Inert debris/wreckage found in Poland after the fact (no live attack) = 8" in prompt
    # Baltic tier: minor 6-7.
    assert "Baltic states (LT/LV/EE): a minor incident (lone drone, found debris, airspace blip) = 6-7" in prompt
    # Baltic tier: strike 8 / deliberate-with-casualties 9.
    assert (
        "a real strike on their soil = 8; a deliberate Russian attack with casualties or shelter orders = 9"
    ) in prompt
    # Romania tier: minor 6 / injuries 7-8 / massive 9.
    assert "Romania: a minor incident = 6; a strike with injuries = 7-8; a massive deliberate attack = 9" in prompt
    # Moldova ~ 6.
    assert "Moldova: incidents on Moldovan soil = around 6" in prompt
    # Roundup / reaction scored on own weight.
    assert "a foreign government's reaction = around 4" in prompt
    assert "a Polish-government reaction (statement by Polish authorities) = around 6" in prompt


# ---------------------------------------------------------------------------
# 0.15 — debris_found + official_statement event types
# ---------------------------------------------------------------------------


def test_prompt_debris_and_statement_types():
    """[0.15] The enum gains debris_found + official_statement, with their scoring rules."""
    prompt = _full_prompt()
    # Enum line carries both new values.
    assert "drone_attack|debris_found|official_statement|other|none" in prompt
    # Debris-in-Poland scoring rule (per 0.14 = 8).
    assert "Debris found in Poland = 8" in prompt
    # official_statement reaction rule.
    assert 'event_type "official_statement"' in prompt
    assert "foreign reaction = around 4" in prompt
    # Both keep is_military_event: true so they survive the pre-dedup gate.
    assert "KEEP is_military_event: true" in prompt
