from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .models import AuditReport, GateState, Severity


@dataclass(frozen=True)
class RegressionReport:
    schema_version: str
    original_sha256: str
    candidate_sha256: str
    target_rules: tuple[str, ...]
    resolved_target_rules: tuple[str, ...]
    unresolved_target_rules: tuple[str, ...]
    new_error_findings: tuple[dict[str, Any], ...]
    required_checks_complete: bool
    repair_attempted: bool
    gate_state: GateState

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "original_sha256": self.original_sha256,
            "candidate_sha256": self.candidate_sha256,
            "target_rules": list(self.target_rules),
            "resolved_target_rules": list(self.resolved_target_rules),
            "unresolved_target_rules": list(self.unresolved_target_rules),
            "new_error_findings": list(self.new_error_findings),
            "required_checks_complete": self.required_checks_complete,
            "repair_attempted": self.repair_attempted,
            "gate_state": self.gate_state.value,
        }


def compare_audits(
    original: AuditReport,
    candidate: AuditReport,
    target_rules: Iterable[str] = (),
    repair_attempted: bool = False,
) -> RegressionReport:
    targets = tuple(sorted(set(target_rules)))
    original_errors = {_finding_signature(item): item for item in original.findings if item.severity is Severity.ERROR}
    candidate_errors = {_finding_signature(item): item for item in candidate.findings if item.severity is Severity.ERROR}
    candidate_error_rules = {item.rule_id for item in candidate_errors.values()}
    resolved = tuple(rule for rule in targets if rule not in candidate_error_rules)
    unresolved = tuple(rule for rule in targets if rule in candidate_error_rules)
    new_keys = sorted(set(candidate_errors) - set(original_errors))
    new_findings = tuple(candidate_errors[key].to_dict() for key in new_keys)
    checks_complete = not candidate.checks_incomplete

    if checks_complete and candidate.error_count == 0 and not unresolved:
        state = GateState.REPAIRED_PASS if repair_attempted else GateState.PASS
    elif repair_attempted:
        state = GateState.FAILED_ROLLBACK
    else:
        state = GateState.REJECTED

    return RegressionReport(
        schema_version="0.1",
        original_sha256=original.asset_sha256,
        candidate_sha256=candidate.asset_sha256,
        target_rules=targets,
        resolved_target_rules=resolved,
        unresolved_target_rules=unresolved,
        new_error_findings=new_findings,
        required_checks_complete=checks_complete,
        repair_attempted=repair_attempted,
        gate_state=state,
    )


def _finding_signature(finding: Any) -> str:
    return json.dumps(
        {"rule_id": finding.rule_id, "location": finding.location},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
