"""Second-stage Jev experiment: explicit geography and full classification fields."""

import re
from copy import deepcopy

from sentinel.eval.jev_questions import build_request, decode, validate_answers

VERSION = "jev-pipeline-v2"


def source_spans(article):
    """Candidate excerpts are copied, never generated; all fit the runtime quote cap."""
    spans = {"none": ""}
    for text in (article.title, article.summary):
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            for start in range(0, len(sentence), 160):
                chunk = sentence[start : start + 160]
                if chunk.strip():
                    spans[f"span_{len(spans)}"] = chunk
    if len(spans) > 255:
        raise ValueError("Too many evidence candidates; source needs explicit preprocessing")
    return spans


def build_pipeline_request(article, candidates, policy, settings):
    payload = build_request(article, candidates, policy, settings)
    questions = payload["questions"]
    names = settings["country_names"]
    for group, countries in (("affected", policy["monitored_countries"]), ("attack", settings["attack_countries"])):
        for country in countries:
            question = questions[f"{group}_{country}"]
            condition = (
                "a concrete local military incident, drone discovery, or protective response"
                if group == "affected"
                else "a hostile physical impact or incursion"
            )
            question["instructions"]["question"] = (
                f"Does the CURRENT article explicitly locate {condition} IN {names[country]}? "
                f"Its ISO country code is {country}. An asset's nationality or destination is not its location. "
                "Use this article only; remembered incidents cannot supply missing geography."
            )
            if group == "affected":
                question["instructions"]["definitions"] += (
                    " A hostile attack physically in this country counts even without a civilian warning. "
                    "A reported local protective measure counts even when the article says that it has now ended."
                )
    questions["attack_other"]["instructions"]["question"] = (
        "Does the CURRENT source explicitly locate a hostile impact or incursion outside these countries: "
        + "; ".join(names[c] for c in settings["attack_countries"])
        + "?"
    )
    questions["status"]["instructions"]["definitions"] += (
        " A civilian story with no military incident or protective measure has unclear incident status. "
        "Past-tense grammar alone does not establish a historical retrospective. "
        "Resolved requires an actual danger or protective alert to have ended; completed routine "
        "training that never involved real danger does not establish neutralisation of danger."
    )

    def choice(text, criteria):
        return {
            "type": "choice",
            "instructions": {
                "question": text,
                "source_discipline": questions["status"]["instructions"]["source_discipline"],
            },
            "criteria": criteria,
        }

    questions["military"] = choice(
        "Does the CURRENT article report a military incident, relevant hostile threat, nuclear activity "
        "or military protective response, including a past incident? Ordinary non-nuclear exercises, "
        "pure civilian events and pure diplomacy do not qualify.",
        {
            "yes": "A military incident, relevant threat or protective response is reported.",
            "no": "Only civilian events, diplomacy or conventional exercises are reported.",
        },
    )
    questions["event_type"] = choice("Which event type best describes the current article?", settings["event_types"])
    questions["aggressor"] = choice(
        "Which hostile actor is explicitly identified in the CURRENT article? Nationality must be stated, "
        "not inferred from script, weapon type or remembered incidents.",
        {
            **{c: names[c] for c in settings["attack_countries"]},
            "unknown": "Hostility is reported but the actor is unstated or outside the listed countries.",
            "none": "No hostile actor is reported.",
        },
    )
    for i, candidate in enumerate(candidates):
        questions[f"identity_{i}"] = choice(
            f"Does the CURRENT article describe the same concrete episode as remembered_incidents[{i}] "
            f"(ID {candidate['id']})? Judge identity independently of whether its details changed. "
            "A separate wave after an ended episode is different. Shared country or weapon alone is insufficient.",
            {
                "same": "The same continuing episode, whether duplicate, update or escalation.",
                "different": "A distinct episode, location or explicitly separate wave.",
                "uncertain": "Identity or separation cannot be established from the source.",
            },
        )
    spans = source_spans(article)
    payload["state"]["source_spans"] = spans
    for field, condition in (
        ("attack_countries", "the explicitly stated location of a hostile physical impact or incursion"),
        ("protection", "an official resident warning or precautionary military response"),
        ("status", "whether actual danger or protective measures are active, resolved or historical"),
    ):
        questions[f"evidence_{field}"] = choice(
            f"Which CURRENT source span most directly supports {condition}? Select none if there is no supporting text.",
            {key: text if text else "No supporting source span." for key, text in spans.items()},
        )
    return payload


def enforce_geography(data, monitored):
    """A monitored country explicitly attacked is necessarily affected."""
    result = deepcopy(data)
    before = set(result["affected_countries"])
    added = (set(result["facts"]["attack_countries"]) & set(monitored)) - before
    result["affected_countries"] = sorted(before | added)
    return result, sorted(added)


def decode_pipeline(payload, response, settings, monitored):
    answers = validate_answers(payload, response)
    # The v1 decoder ignores extra question names, retaining all raw probabilities.
    raw, diagnostics = decode(payload, response, settings)
    result, added = enforce_geography(raw, monitored)
    candidates = payload["state"]["remembered_incidents"]
    matched = []
    conflicts = []
    for i, candidate in enumerate(candidates):
        identity, relation = answers[f"identity_{i}"], answers[f"memory_{i}"]
        if identity["choice"] == "same" and relation["choice"] in {"duplicate", "update", "escalation"}:
            matched.append((candidate["id"], identity, relation))
        elif identity["choice"] != "different" or relation["choice"] != "unrelated":
            conflicts.append(candidate["id"])
    if len(matched) == 1 and not conflicts:
        event_id, identity, relation = matched[0]
        memory = {
            "decision": relation["choice"],
            "matched_event_id": event_id,
            "confidence": identity["confidence"],
            "reason": f"Jev identity=same; relation={relation['choice']}; supplied candidate {event_id}.",
        }
    else:
        memory = {
            "decision": "uncertain" if matched or conflicts else "new",
            "matched_event_id": None,
            "confidence": 0.0 if matched or conflicts else 1.0,
            "reason": "Candidate comparison ambiguous." if matched or conflicts else "No matching supplied episode.",
        }
    result.update(
        incident_memory=memory,
        is_new_event=memory["decision"] in {"new", "uncertain"},
        is_military_event=answers["military"]["choice"] == "yes",
        event_type=answers["event_type"]["choice"],
        aggressor=answers["aggressor"]["choice"],
        confidence=answers["urgency"]["confidence"],
    )
    result["facts"]["evidence"] = {
        field: payload["state"]["source_spans"][answers[f"evidence_{field}"]["choice"]]
        for field in ("attack_countries", "protection", "status")
    }
    diagnostics.update(
        raw_affected_countries=raw["affected_countries"],
        added_affected_countries=added,
        identity_conflicts=conflicts,
        question_version=VERSION,
    )
    return result, diagnostics
