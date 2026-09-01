from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class GateState(str, Enum):
    PASS = "PASS"
    REPAIRED_PASS = "REPAIRED_PASS"
    NEED_APPROVAL = "NEED_APPROVAL"
    FAILED_ROLLBACK = "FAILED_ROLLBACK"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Finding:
    finding_id: str
    rule_id: str
    severity: Severity
    message: str
    location: dict[str, Any] = field(default_factory=dict)
    observed: Any = None
    expected: Any = None
    evidence: dict[str, Any] = field(default_factory=dict)
    repairability: str = "MANUAL_ONLY"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        return payload


@dataclass
class AuditReport:
    schema_version: str
    job_id: str
    asset_path: str
    asset_sha256: str
    profile_id: str
    profile_version: str
    measurements: dict[str, Any]
    findings: list[Finding]
    checks_completed: list[str]
    checks_incomplete: list[str]
    created_at: str

    @property
    def error_count(self) -> int:
        return sum(item.severity is Severity.ERROR for item in self.findings)

    @property
    def warning_count(self) -> int:
        return sum(item.severity is Severity.WARNING for item in self.findings)

    @property
    def gate_state(self) -> GateState:
        if self.error_count or self.checks_incomplete:
            return GateState.REJECTED
        return GateState.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "asset": {
                "path": self.asset_path,
                "sha256": self.asset_sha256,
            },
            "profile": {
                "id": self.profile_id,
                "version": self.profile_version,
            },
            "measurements": self.measurements,
            "findings": [item.to_dict() for item in self.findings],
            "checks_completed": self.checks_completed,
            "checks_incomplete": self.checks_incomplete,
            "summary": {
                "gate_state": self.gate_state.value,
                "error_count": self.error_count,
                "warning_count": self.warning_count,
            },
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class RepairStep:
    step_id: str
    finding_ids: tuple[str, ...]
    skill: str
    operation: str
    parameters: dict[str, Any]
    expected_changes: tuple[str, ...]
    verify_rules: tuple[str, ...]
    risk_level: str
    rollback_on: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for name in ("finding_ids", "expected_changes", "verify_rules", "rollback_on"):
            payload[name] = list(payload[name])
        return payload


@dataclass(frozen=True)
class PatchPlan:
    schema_version: str
    plan_id: str
    asset_sha256: str
    profile_id: str
    profile_version: str
    state: str
    steps: tuple[RepairStep, ...]
    risk_level: str
    approval_required: bool
    reason: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "asset_sha256": self.asset_sha256,
            "profile": {"id": self.profile_id, "version": self.profile_version},
            "state": self.state,
            "steps": [step.to_dict() for step in self.steps],
            "risk_level": self.risk_level,
            "approval_required": self.approval_required,
            "reason": self.reason,
            "created_at": self.created_at,
        }
