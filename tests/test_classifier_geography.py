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


def test_prompt_named_city_resolves_to_country():
    """[0.5, 0.8] The gate carves out named cities/regions that identify a monitored country.

    Guards against under-alerting: a headline naming a monitored-country city (e.g. Rzeszow) but not
    the country word must still attribute the country via physical location, while the gate keeps
    fully suppressing GENERIC references ('a NATO country'). This closes the city-only suppression
    gap without weakening the 0.5 false-positive gate.
    """
    prompt = _full_prompt()
    # Named place counts as explicitly naming the country (physical-location attribution).
    assert "Rzeszow -> Poland" in prompt
    assert "count as explicitly naming that country via its physical location" in prompt
    # The carve-out explicitly does NOT loosen the generic-reference gate.
    assert "does NOT apply to generic category references" in prompt


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


# ---------------------------------------------------------------------------
# 0.5 / 0.6 / 0.14 — calibration rules must not contradict the target-country
# gate or the geography ladder. These guard against the CALIBRATION/CRITICAL
# rules re-introducing an unnamed-NATO auto-9 or a universal strike floor.
# ---------------------------------------------------------------------------


def test_prompt_no_unnamed_nato_auto_high():
    """[0.5, 0.6] No calibration example commands >=9 for an UNNAMED NATO reference."""
    prompt = _full_prompt()
    # The old unnamed-NATO >=9 examples must be gone.
    assert "'Drones violating airspace of NATO state' with shelter warnings = 9" not in prompt
    assert "'Russian strike on NATO border' = 9" not in prompt
    # The rules now explicitly route an unnamed NATO reference to the gate (not 9).
    assert "An unnamed 'a NATO state' does NOT qualify" in prompt
    assert "An unnamed 'a NATO border' does NOT qualify" in prompt


def test_prompt_strike_rule_defers_to_ladder():
    """[0.14] R3's strike scoring follows the ladder (Baltic 8 / Romania 7-8), not a universal MIN 9."""
    prompt = _full_prompt()
    assert "score MINIMUM 9 for Poland" in prompt
    assert "a real strike on Baltic (LT/LV/EE) soil = 8" in prompt
    assert "a strike with injuries on Romanian soil = 7-8" in prompt


def test_prompt_reaction_rule_has_polish_government_exception():
    """[0.14] R6's reaction cap carves out the Polish-government reaction at ~6 (not capped at 4)."""
    prompt = _full_prompt()
    assert (
        "a reaction or statement BY the Polish government / Polish authorities is its own "
        "event_type 'official_statement' scored around 6 per the GEOGRAPHY LADDER, NOT capped at 4"
    ) in prompt


def test_prompt_crash_rule_has_debris_carveout():
    """[0.14, 0.15] R7's 4-max crash cap carves out debris found on monitored soil (PL debris = 8)."""
    prompt = _full_prompt()
    assert "debris DISCOVERED on the soil of a monitored country is event_type 'debris_found'" in prompt
    assert "debris found in Poland = 8; debris found on Baltic or Romanian soil per the ladder" in prompt


def test_prompt_moldova_exempt_from_nonmonitored_cap():
    """[0.14] The non-monitored 1-3/5-max cap carves out Moldova (~6 per the ladder)."""
    prompt = _full_prompt()
    assert "the article concerns Moldova (incidents on Moldovan soil = around 6" in prompt


def test_prompt_json_example_includes_ro():
    """[0.6] The affected_countries JSON example lists RO so the model is not biased against it."""
    prompt = _full_prompt()
    assert '"affected_countries": ["PL", "LT", "LV", "EE", "RO"]' in prompt


# ---------------------------------------------------------------------------
# 0.14 — R2's airspace escalation must not give Romania the Baltic shelter-order
# ->9 shortcut; Romania follows its own ladder (minor 6 / injuries 7-8 / massive 9).
# ---------------------------------------------------------------------------


def test_prompt_r2_romania_no_shelter_shortcut():
    """[0.14] R2 scores Romania airspace on its own ladder, not the Baltic shelter escalation."""
    prompt = _full_prompt()
    # The Baltic shelter-order->9 escalation stays scoped to LT/LV/EE only.
    assert "Over the Baltic states (LT/LV/EE), a lone/minor airspace incident = 6-7" in prompt
    # Romania scored on its own ladder, with no shelter-order shortcut to 9.
    assert "Over Romania, a minor airspace incident = 6" in prompt
    assert "Romania has no shelter-order shortcut to 9" in prompt
    # The old lumped 'Baltic states or Romania' escalation is gone.
    assert "Over the Baltic states or Romania" not in prompt


# ---------------------------------------------------------------------------
# 0.14 — the user-prompt urgency scale must not contradict the geography ladder
# (air-raid alerts belong at the 9-10 call band, not 7-8; no flat single-drone 5-6).
# ---------------------------------------------------------------------------


def test_prompt_urgency_scale_aligns_with_ladder():
    """[0.14] The urgency-scale anchors follow the ladder rather than contradicting it."""
    prompt = _full_prompt()
    # Poland shelter/air-raid orders belong at the 9-10 call band (an active aerial threat over Poland)...
    assert "shelter or air-raid orders issued in Poland" in prompt
    # ...but a Baltic/Romanian strike or shelter order is NOT auto-9-10 -- it follows the ladder.
    assert "a strike or shelter order there is NOT automatically 9-10" in prompt
    assert "air alerts in Baltic states" not in prompt
    # The old blanket "monitored country" shelter->9-10 anchor is gone (it would call Baltic/RO 8s).
    assert "shelter orders or air-raid alerts issued in a monitored country" not in prompt
    # The stale flat single-drone 5-6 anchor is gone.
    assert "single drone found near border" not in prompt
    # The 7-8 band still carries the ladder's real-strike anchors.
    assert "a real strike on Baltic soil = 8" in prompt
    assert "a strike with injuries on Romanian soil = 7-8" in prompt
    assert "inert debris found in Poland = 8" in prompt


def test_prompt_shelter_floor_scoped_to_poland():
    """[0.14, 0.6] R1's unconditional MIN-9 shelter floor is scoped to Poland; Baltic/RO defer to the ladder.

    Guards the owner ground truth (Vilnius strike with shelter orders = 8/sms): a shelter order in a
    Baltic/Romanian context must not unconditionally floor urgency to 9 -- only Poland gets that floor.
    """
    prompt = _full_prompt()
    # Poland keeps the non-negotiable shelter/air-raid MIN-9 floor.
    assert "If authorities in POLAND issue shelter-in-place orders" in prompt
    assert "This is non-negotiable for Poland:" in prompt
    # Baltic/Romania shelter orders are a ladder-scored escalation factor, not an unconditional 9.
    assert "a shelter order is an escalation FACTOR scored by the GEOGRAPHY LADDER, NOT an unconditional 9" in prompt
    # The old blanket "in a monitored country = 9-10" shelter floor is gone.
    assert "in a monitored country = 9-10" not in prompt


def test_prompt_deliberate_baltic_attack_reaches_9():
    """[0.14 + prime directive] A deliberate Baltic attack with shelter orders (not only casualties) still reaches 9.

    Guards against dangerous under-alerting: the calibration rules must NOT gate the Baltic 9 tier
    to confirmed casualties only. A deliberate Russian attack with shelter orders but no casualty
    count yet must still be call-tier, matching the ladder ("casualties or shelter orders = 9").
    """
    prompt = _full_prompt()
    # The ladder's deliberate-attack 9 path (casualties OR shelter orders) is intact.
    assert "a deliberate Russian attack with casualties or shelter orders = 9" in prompt
    # R2 and R3 both route the Baltic 9 tier through the deliberate-attack path with BOTH escalators.
    assert prompt.count("a deliberate Russian attack (with casualties or shelter orders)") >= 2
    # The stale casualties-ONLY gating (which would suppress a shelter-only deliberate attack) is gone.
    assert "only for a deliberate Russian attack with casualties" not in prompt
