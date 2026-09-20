"""Strict runtime response schema shared with frozen evaluations."""

from sentinel.classification.policy import FACT_SCHEMA

FIELDS = {
    "is_military_event": {"type": "boolean"},
    "event_type": {"type": "string"},
    "urgency_score": {"type": "integer", "minimum": 1, "maximum": 10},
    "affected_countries": {"type": "array", "items": {"type": "string"}},
    "aggressor": {"type": "string"},
    "is_new_event": {"type": "boolean"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "summary_pl": {"type": "string"},
    "incident_memory": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {"type": "string", "enum": ["new", "duplicate", "update", "escalation", "uncertain"]},
            "matched_event_id": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": ["decision", "matched_event_id", "confidence", "reason"],
    },
}
RESPONSE_SCHEMA = {"type": "object", "properties": FIELDS, "required": list(FIELDS), "additionalProperties": False}


CLASSIFICATION_SCHEMA = {
    **RESPONSE_SCHEMA,
    "properties": {**FIELDS, "facts": FACT_SCHEMA},
    "required": [*FIELDS, "facts"],
}
