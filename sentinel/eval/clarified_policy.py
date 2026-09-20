"""Evaluation policy loading; runtime owns the unchanged v2 contract."""

from pathlib import Path

import yaml

from sentinel.classification.policy import FACT_SCHEMA, messages, prompt_hash, system_prompt  # noqa: F401


def load_policy(path: str) -> dict:
    policy = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or policy.get("version") != 2 or policy.get("scope") != "evaluation_only":
        raise ValueError("Expected evaluation-only policy version 2")
    for key, allowed in {
        "near_border_strike": {"awareness", "log_only", "critical"},
        "neutralised_drone": {"current_danger", "original_severity"},
    }.items():
        if policy.get(key) not in allowed:
            raise ValueError(f"Operator choice is still required: {key}")
    if policy.get("status") != "resolved":
        raise ValueError("Policy choices have not been resolved")
    for name, values in policy["ranges"].items():
        if not isinstance(values, list) or len(values) != 2 or not 1 <= values[0] <= values[1] <= 10:
            raise ValueError(f"Invalid policy range: {name}")
    return policy
