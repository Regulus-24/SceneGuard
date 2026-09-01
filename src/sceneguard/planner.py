from __future__ import annotations

from datetime import UTC, datetime
import re
from uuid import uuid4

from .models import AuditReport, PatchPlan, RepairStep, Severity
from .profile import QualityProfile


RULE_TO_OPERATION = {
    "mesh.degenerate_triangles": "remove_degenerate_triangles",
    "profile.max_texture_dimension": "resize_embedded_textures",
}
PLAN_ID = re.compile(r"^plan-[a-f0-9]{12}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
PLAN_STATES = {"NO_ACTION", "READY", "MANUAL_ONLY"}
RISK_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


def validate_patch_plan(plan: PatchPlan, profile: QualityProfile) -> None:
    profile.validate()
    if plan.schema_version != "0.1":
        raise ValueError("unsupported PatchPlan schema_version")
    if PLAN_ID.fullmatch(plan.plan_id) is None:
        raise ValueError("PatchPlan plan_id is invalid")
    if SHA256.fullmatch(plan.asset_sha256) is None:
        raise ValueError("PatchPlan asset_sha256 must be a lowercase SHA-256 digest")
    if (plan.profile_id, plan.profile_version) != (profile.profile_id, profile.version):
        raise ValueError("PatchPlan profile binding does not match the active Profile")
    if plan.state not in PLAN_STATES or plan.risk_level not in RISK_RANK:
        raise ValueError("PatchPlan state or risk level is invalid")
    if not isinstance(plan.approval_required, bool) or not plan.reason.strip():
        raise ValueError("PatchPlan approval flag and reason are required")

    if plan.state != "READY":
        if plan.steps:
            raise ValueError("non-READY PatchPlan must not contain repair steps")
        if plan.approval_required:
            raise ValueError("non-READY PatchPlan must not request execution approval")
        return
    if not plan.steps:
        raise ValueError("READY PatchPlan must contain at least one repair step")

    allowed = set(profile.repair_policy.get("allowed_operations", []))
    risk_map = profile.repair_policy.get("operation_risk_levels", {})
    approval_levels = set(profile.repair_policy.get("approval_required_risk_levels", []))
    denied_levels = set(profile.repair_policy.get("denied_risk_levels", []))
    step_ids: set[str] = set()
    for step in plan.steps:
        if not step.step_id or step.step_id in step_ids:
            raise ValueError("PatchPlan step_id values must be non-empty and unique")
        step_ids.add(step.step_id)
        if step.operation not in allowed:
            raise ValueError(f"PatchPlan operation is not whitelisted: {step.operation}")
        expected_risk = risk_map.get(step.operation, "L1")
        if step.risk_level != expected_risk:
            raise ValueError("PatchPlan step risk does not match the active Profile")
        if not step.finding_ids or not step.verify_rules or not step.rollback_on:
            raise ValueError("PatchPlan steps require finding, verification and rollback bindings")
    highest_risk = max((step.risk_level for step in plan.steps), key=RISK_RANK.__getitem__)
    if plan.risk_level != highest_risk:
        raise ValueError("PatchPlan risk level must equal its highest-risk step")
    if plan.risk_level in denied_levels:
        raise ValueError("READY PatchPlan cannot contain a denied risk level")
    if plan.approval_required != (plan.risk_level in approval_levels):
        raise ValueError("PatchPlan approval flag does not match the active Profile")


def build_patch_plan(report: AuditReport, profile: QualityProfile) -> PatchPlan:
    errors = [finding for finding in report.findings if finding.severity is Severity.ERROR]
    allowed = set(profile.repair_policy.get("allowed_operations", []))
    created_at = datetime.now(UTC).isoformat()
    base = {
        "schema_version": "0.1",
        "plan_id": f"plan-{uuid4().hex[:12]}",
        "asset_sha256": report.asset_sha256,
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "created_at": created_at,
    }
    if not errors:
        return PatchPlan(
            **base,
            state="NO_ACTION",
            steps=(),
            risk_level="L0",
            approval_required=False,
            reason="asset audit contains no ERROR findings",
        )

    unsupported = [finding.rule_id for finding in errors if RULE_TO_OPERATION.get(finding.rule_id) not in allowed]
    if unsupported:
        return PatchPlan(
            **base,
            state="MANUAL_ONLY",
            steps=(),
            risk_level="L3",
            approval_required=False,
            reason="unsupported ERROR rules: " + ", ".join(sorted(set(unsupported))),
        )

    repairable = [finding for finding in errors if RULE_TO_OPERATION.get(finding.rule_id) in allowed]
    if not repairable:
        return PatchPlan(
            **base,
            state="MANUAL_ONLY",
            steps=(),
            risk_level="L3",
            approval_required=False,
            reason="no tested repair maps to the current findings",
        )

    operations = sorted({RULE_TO_OPERATION[finding.rule_id] for finding in repairable})
    if len(operations) != 1:
        return PatchPlan(
            **base,
            state="MANUAL_ONLY",
            steps=(),
            risk_level="L3",
            approval_required=False,
            reason="v0.1 executes one repair operation per PatchPlan; split mixed repairs into separate jobs",
        )
    operation = operations[0]
    findings = [finding for finding in repairable if RULE_TO_OPERATION.get(finding.rule_id) == operation]
    risk_level = str(profile.repair_policy.get("operation_risk_levels", {}).get(operation, "L1"))
    approval_required = risk_level in set(profile.repair_policy.get("approval_required_risk_levels", []))
    if risk_level in set(profile.repair_policy.get("denied_risk_levels", [])):
        return PatchPlan(
            **base,
            state="MANUAL_ONLY",
            steps=(),
            risk_level=risk_level,
            approval_required=False,
            reason=f"operation risk {risk_level} is denied by the active Profile",
        )

    if operation == "remove_degenerate_triangles":
        skill = "mesh-safe-repair"
        parameters = {"primitive_mode": "TRIANGLES", "preserve_buffer_layout": True}
        expected_changes = ("degenerate_triangle_count -> 0", "index accessor count decreases or stays equal")
        verify_rules = ("mesh.degenerate_triangles", "package.bounds", "package.references", "profile.budgets")
    else:
        skill = "texture-safe-resize"
        parameters = {"max_dimension": profile.rules["max_texture_dimension"], "preserve_aspect_ratio": True}
        expected_changes = (
            f"max_texture_dimension -> <= {profile.rules['max_texture_dimension']}",
            "geometry accessors and mesh topology remain unchanged",
        )
        verify_rules = ("profile.max_texture_dimension", "package.bounds", "package.references", "profile.budgets")
    step = RepairStep(
        step_id="step-001",
        finding_ids=tuple(finding.finding_id for finding in findings),
        skill=skill,
        operation=operation,
        parameters=parameters,
        expected_changes=expected_changes,
        verify_rules=verify_rules,
        risk_level=risk_level,
        rollback_on=("tool_error", "target_unresolved", "new_error_finding", "checks_incomplete"),
    )
    return PatchPlan(
        **base,
        state="READY",
        steps=(step,),
        risk_level=risk_level,
        approval_required=approval_required,
        reason=(
            f"all ERROR findings map to the tested {risk_level} repair whitelist; human approval required"
            if approval_required
            else f"all ERROR findings map to the tested {risk_level} repair whitelist"
        ),
    )
