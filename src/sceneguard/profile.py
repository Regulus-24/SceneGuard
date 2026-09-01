from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RULE_TYPES = {
    "max_file_bytes": int,
    "max_triangles": int,
    "max_texture_dimension": int,
    "allow_external_uris": bool,
    "require_embedded_buffers": bool,
}
RISK_LEVELS = {"L0", "L1", "L2", "L3"}
RISK_POLICY_KEYS = (
    "auto_execute_risk_levels",
    "approval_required_risk_levels",
    "denied_risk_levels",
)


@dataclass(frozen=True)
class QualityProfile:
    profile_id: str
    version: str
    description: str
    rules: dict[str, Any]
    repair_policy: dict[str, Any]

    def validate(self) -> None:
        if not self.profile_id.strip() or not self.version.strip():
            raise ValueError("profile_id and version must be non-empty strings")
        missing_rules = sorted(set(RULE_TYPES) - set(self.rules))
        if missing_rules:
            raise ValueError("profile.rules is missing required rules: " + ", ".join(missing_rules))
        for name, expected_type in RULE_TYPES.items():
            value = self.rules[name]
            if type(value) is not expected_type:  # bool must not pass as int
                raise ValueError(f"profile.rules.{name} must be {expected_type.__name__}")
            if expected_type is int and value <= 0:
                raise ValueError(f"profile.rules.{name} must be positive")

        policy = self.repair_policy
        if not isinstance(policy, dict):
            raise ValueError("profile.repair_policy must be an object")
        allowed = _unique_string_list(policy.get("allowed_operations", []), "allowed_operations")
        risk_map = policy.get("operation_risk_levels", {})
        if not isinstance(risk_map, dict):
            raise ValueError("profile.repair_policy.operation_risk_levels must be an object")
        unknown_operations = sorted(set(risk_map) - set(allowed))
        if unknown_operations:
            raise ValueError("operation risk is declared for a non-whitelisted operation: " + ", ".join(unknown_operations))
        for operation, level in risk_map.items():
            if level not in RISK_LEVELS:
                raise ValueError(f"invalid risk level for {operation}: {level}")

        classified: dict[str, set[str]] = {}
        for key in RISK_POLICY_KEYS:
            levels = set(_unique_string_list(policy.get(key, []), key))
            invalid = sorted(levels - RISK_LEVELS)
            if invalid:
                raise ValueError(f"{key} contains invalid risk levels: {', '.join(invalid)}")
            classified[key] = levels
        for index, left in enumerate(RISK_POLICY_KEYS):
            for right in RISK_POLICY_KEYS[index + 1 :]:
                overlap = sorted(classified[left] & classified[right])
                if overlap:
                    raise ValueError(f"risk levels overlap between {left} and {right}: {', '.join(overlap)}")
        all_classified = set().union(*classified.values())
        for operation in allowed:
            level = risk_map.get(operation, "L1")
            if level not in all_classified:
                raise ValueError(f"whitelisted operation {operation} has unclassified risk level {level}")

    @classmethod
    def load(cls, path: str | Path) -> "QualityProfile":
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))
        required = {"profile_id", "version", "rules"}
        missing = sorted(required - payload.keys())
        if missing:
            raise ValueError(f"profile is missing required fields: {', '.join(missing)}")
        rules = payload["rules"]
        if not isinstance(rules, dict):
            raise ValueError("profile.rules must be an object")
        profile = cls(
            profile_id=str(payload["profile_id"]),
            version=str(payload["version"]),
            description=str(payload.get("description", "")),
            rules=rules,
            repair_policy=dict(payload.get("repair_policy", {})),
        )
        profile.validate()
        return profile


def _unique_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"profile.repair_policy.{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"profile.repair_policy.{field} must not contain duplicates")
    return value
