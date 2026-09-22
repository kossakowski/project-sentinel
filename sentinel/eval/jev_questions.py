"""Evaluation-only Jev questions; never imported by the monitoring runtime."""

import json
import math
import re

from sentinel.classification.policy import messages, system_prompt

VERSION = "jev-comparison-v1"


def build_request(article, candidates, policy, settings):
    """Use the same source context as Luna, without annotations or model history."""
    state = json.loads(messages(article, candidates, policy)[1]["content"])
    prompt = system_prompt(policy)
    discipline = prompt.split("SOURCE DISCIPLINE\n", 1)[1].split("FACTS BEFORE POLICY", 1)[0].strip()
    facts = prompt.split("FACTS BEFORE POLICY\n", 1)[1].split("ALERT POLICY", 1)[0].strip()
    definitions = {
        match.group(1): match.group(2).strip()
        for match in re.finditer(r"^- ([\w.]+): (.*?)(?=\n- |\Z)", facts, flags=re.MULTILINE | re.DOTALL)
    }
    severity = (
        prompt.split("ALERT POLICY — ORDER AND PRECEDENCE\n", 1)[1].split("is_military_event means", 1)[0].strip()
    )
    identity = prompt.split("INCIDENT IDENTITY — INDEPENDENT OF SEVERITY\n", 1)[1]
    identity = identity.split("Use matched_event_id", 1)[0].strip()

    def choice(question, criteria, rules):
        return {
            "type": "choice",
            "instructions": {
                "question": question,
                "source_discipline": discipline,
                "definitions": rules,
            },
            "criteria": criteria,
        }

    presence = {
        "yes": "The current source explicitly supports this condition.",
        "no": "The condition is absent or explicitly denied in the current source.",
        "unclear": "The source raises this condition but does not establish whether it applies.",
    }
    questions = {}
    for group, countries, definition in (
        ("affected", policy["monitored_countries"], "affected_countries"),
        ("attack", settings["attack_countries"], "facts.attack_countries"),
    ):
        for country in countries:
            questions[f"{group}_{country}"] = choice(
                f"Does the current article satisfy the definition of {definition} for country {country}?",
                presence,
                definitions[definition],
            )
    questions["attack_other"] = choice(
        "Does the current source explicitly locate a hostile physical impact or incursion in a country "
        f"outside this list: {', '.join(settings['attack_countries'])}?",
        presence,
        definitions["facts.attack_countries"],
    )
    questions["protection"] = choice(
        "What protective measure does the current article report?",
        {
            "official_warning": "Explicit official resident air-raid, shelter or evacuation order.",
            "precaution": "Scramble, readiness or precautionary airport closure without a resident order.",
            "none": "No protective measure is reported.",
            "unclear": "A measure or alarm is mentioned but its kind cannot be established.",
        },
        definitions["facts.protection"],
    )
    questions["status"] = choice(
        "What is the current incident status according to this article?",
        {
            "active": "Current danger or ongoing protective measures.",
            "resolved": "Explicitly ended or neutralised danger, including in a retrospective report.",
            "historical": "Past-event retrospective without new danger or an explicit resolution statement.",
            "unclear": "Current status is not supplied; past tense or discovery alone does not establish resolution.",
        },
        definitions["facts.status"],
    )
    # A Choice preserves discrete urgency and its entire distribution. A Score
    # mean could conceal a split between harmless and critical outcomes.
    questions["urgency"] = choice(
        "Which integer urgency does the current article warrant under the alert policy? "
        "Apply rule precedence and geography first. Adjust scale only within the applicable band.",
        {
            str(n): {
                "urgency": n,
                "eligible_policy_bands": [name for name, (low, high) in policy["ranges"].items() if low <= n <= high],
            }
            for n in range(1, 11)
        },
        facts + "\n\n" + severity,
    )
    for index, candidate in enumerate(candidates):
        questions[f"memory_{index}"] = choice(
            f"How does the current article relate to remembered_incidents[{index}] "
            f"(ID {candidate['id']})? Compare only this candidate. Different country/day/weapon "
            "or an explicitly separate wave may distinguish episodes; shared generic attributes do not prove identity.",
            {
                "duplicate": "Same episode, already-covered facts, including translation or confirmation.",
                "update": "Same episode, routine details, investigation, reactions or danger ending.",
                "escalation": "Same continuing episode with significant new danger.",
                "unrelated": "A different episode, including a separate wave after the old episode ended.",
                "uncertain": "The source does not establish identity or separation.",
            },
            identity,
        )
    return {"model": settings["model"], "state": state, "questions": questions}


def validate_answers(payload, response):
    if not isinstance(response, dict) or response.get("model") != payload["model"]:
        raise ValueError("Unexpected Jev model or response shape")
    answers = response.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(payload["questions"]):
        raise ValueError("Missing or unexpected Jev answers")
    for name, question in payload["questions"].items():
        answer = answers[name]
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            raise ValueError("Invalid Jev answer type")
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, dict) or set(probabilities) != set(question["criteria"]):
            raise ValueError("Invalid Jev probability options")
        values = [*probabilities.values(), answer.get("confidence")]
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
            raise ValueError("Invalid Jev probability or confidence")
        if not math.isclose(sum(probabilities.values()), 1, abs_tol=1e-3):
            raise ValueError("Jev probabilities do not sum to one")
        chosen = answer.get("choice")
        if chosen not in probabilities or probabilities[chosen] + 1e-6 < max(probabilities.values()):
            raise ValueError("Invalid Jev winning choice")
    return answers


def decode(payload, response, settings):
    answers = validate_answers(payload, response)
    candidates = payload["state"]["remembered_incidents"]
    matches = [
        (c["id"], answers[f"memory_{i}"])
        for i, c in enumerate(candidates)
        if answers[f"memory_{i}"]["choice"] in {"duplicate", "update", "escalation"}
    ]
    ambiguous = any(answers[f"memory_{i}"]["choice"] == "uncertain" for i in range(len(candidates)))
    if len(matches) == 1 and not ambiguous:
        matched_id, answer = matches[0]
        memory = {"decision": answer["choice"], "matched_event_id": matched_id, "confidence": answer["confidence"]}
    else:
        memory = {"decision": "uncertain" if matches or ambiguous else "new", "matched_event_id": None}
    uncertain = [name for name, answer in answers.items() if answer["choice"] in {"unclear", "uncertain"}]
    countries = [c for c in settings["attack_countries"] if answers[f"attack_{c}"]["choice"] == "yes"]
    if answers["attack_other"]["choice"] == "yes":
        countries.append("OTHER")  # Expose an unsupported location, never silently drop it.
    data = {
        "urgency_score": int(answers["urgency"]["choice"]),
        "affected_countries": [
            name.removeprefix("affected_")
            for name, answer in answers.items()
            if name.startswith("affected_") and answer["choice"] == "yes"
        ],
        "facts": {
            "attack_countries": countries,
            "protection": answers["protection"]["choice"],
            "status": answers["status"]["choice"],
        },
        "incident_memory": memory,
    }
    return data, {"uncertain_questions": uncertain, "competing_matches": len(matches)}
