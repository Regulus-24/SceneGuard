from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .audit import audit_asset
from .models import AuditReport, Finding, PatchPlan, RepairStep, Severity
from .pipeline import _finish, _write_json
from .planner import build_patch_plan, validate_patch_plan
from .profile import QualityProfile
from .regression import compare_audits
from .repair import remove_degenerate_triangles, resize_embedded_textures
from .workspace import (
    append_trace,
    create_checkpoint,
    load_job_workspace,
    publish_candidate,
    rollback_to_checkpoint,
    sha256_file,
)


def plan_job(jobs_root: str | Path, profile: QualityProfile, job_id: str) -> dict[str, Any]:
    """Freeze the planner's deterministic PatchPlan for an already-audited Job."""
    workspace = load_job_workspace(jobs_root, job_id)
    plan_path = workspace.artifacts / "patch_plan.json"
    if plan_path.is_file():
        plan = patch_plan_from_dict(_read_json(plan_path))
        validate_patch_plan(plan, profile)
        if plan.asset_sha256 != _read_audit(workspace.audit_report).asset_sha256:
            raise ValueError("stored PatchPlan is not bound to the Job audit")
        return {"job_id": job_id, "stage": "PLANNED", "replayed": True, "patch_plan": plan.to_dict()}

    report = _read_audit(workspace.audit_report)
    if (report.profile_id, report.profile_version) != (profile.profile_id, profile.version):
        raise ValueError("active Profile does not match the Job audit")
    if sha256_file(workspace.working) != report.asset_sha256:
        raise ValueError("working asset changed after audit; create a new Job")
    plan = build_patch_plan(report, profile)
    validate_patch_plan(plan, profile)
    _write_json(plan_path, plan.to_dict())
    append_trace(
        workspace.trace,
        event="plan.completed",
        job_id=job_id,
        details={
            "actor_role": "repair-planner",
            "state": plan.state,
            "risk_level": plan.risk_level,
            "plan_id": plan.plan_id,
            "plan": "artifacts/patch_plan.json",
        },
    )
    return {"job_id": job_id, "stage": "PLANNED", "replayed": False, "patch_plan": plan.to_dict()}


def execute_job(
    jobs_root: str | Path,
    profile: QualityProfile,
    job_id: str,
    plan_id: str,
) -> dict[str, Any]:
    """Execute only the exact frozen plan; never verify, publish, or decide the gate."""
    workspace = load_job_workspace(jobs_root, job_id)
    plan = _load_bound_plan(workspace, profile, plan_id)
    report_path = workspace.artifacts / "execution_report.json"
    if report_path.is_file():
        result = _read_json(report_path)
        if result.get("plan_id") != plan_id:
            raise ValueError("stored execution report belongs to a different PatchPlan")
        return {"job_id": job_id, "stage": "EXECUTED", "replayed": True, "execution": result}

    if plan.state != "READY":
        result = {
            "schema_version": "0.1",
            "job_id": job_id,
            "plan_id": plan_id,
            "state": "SKIPPED",
            "reason": f"PatchPlan state {plan.state} has no executable operation",
        }
        _write_json(report_path, result)
        append_trace(
            workspace.trace,
            event="repair.skipped",
            job_id=job_id,
            details={"actor_role": "repair-executor", "plan_id": plan_id, "plan_state": plan.state},
        )
        return {"job_id": job_id, "stage": "EXECUTED", "replayed": False, "execution": result}
    if plan.approval_required:
        approval_path = workspace.artifacts / "approval_record.json"
        if not approval_path.is_file():
            raise ValueError("PatchPlan requires a bound human approval before execution")
        approval = _read_json(approval_path)
        if approval.get("plan_id") != plan_id or approval.get("asset_sha256") != plan.asset_sha256:
            raise ValueError("approval record is not bound to this PatchPlan and asset")
        if approval.get("decision") != "APPROVE":
            raise ValueError("PatchPlan was not approved")
    if sha256_file(workspace.working) != plan.asset_sha256:
        raise ValueError("working asset no longer matches the frozen PatchPlan")

    checkpoint = create_checkpoint(workspace, "pre-repair", expected_working_hash=plan.asset_sha256)
    step = plan.steps[0]
    try:
        if step.operation == "remove_degenerate_triangles":
            operation_result = remove_degenerate_triangles(workspace.working, expected_sha256=plan.asset_sha256)
            summary = {"removed_triangle_count": operation_result.removed_triangle_count}
        elif step.operation == "resize_embedded_textures":
            operation_result = resize_embedded_textures(
                workspace.working,
                expected_sha256=plan.asset_sha256,
                max_dimension=int(step.parameters["max_dimension"]),
            )
            summary = {"resized_image_count": operation_result.resized_image_count}
        else:
            raise ValueError(f"unsupported planned operation: {step.operation}")
        result = {
            **operation_result.to_dict(),
            "job_id": job_id,
            "plan_id": plan_id,
            "step_id": step.step_id,
            "state": "SUCCEEDED",
            "checkpoint": checkpoint,
        }
        _write_json(report_path, result)
        append_trace(
            workspace.trace,
            event="repair.executed",
            job_id=job_id,
            details={
                "actor_role": "repair-executor",
                "plan_id": plan_id,
                "step_id": step.step_id,
                "operation": operation_result.operation,
                **summary,
                "before_sha256": operation_result.before_sha256,
                "after_sha256": operation_result.after_sha256,
                "report": "artifacts/execution_report.json",
            },
        )
    except Exception as exc:
        result = {
            "schema_version": "0.1",
            "job_id": job_id,
            "plan_id": plan_id,
            "step_id": step.step_id,
            "state": "FAILED",
            "reason": f"execution failed: {type(exc).__name__}: {exc}",
            "checkpoint": checkpoint,
        }
        _write_json(report_path, result)
        append_trace(
            workspace.trace,
            event="repair.failed",
            job_id=job_id,
            details={"actor_role": "repair-executor", "plan_id": plan_id, "reason": result["reason"]},
        )
    return {"job_id": job_id, "stage": "EXECUTED", "replayed": False, "execution": result}


def verify_job(
    jobs_root: str | Path,
    profile: QualityProfile,
    job_id: str,
    plan_id: str,
) -> dict[str, Any]:
    """Independently re-audit and exclusively publish or roll back the candidate."""
    started = time.monotonic()
    workspace = load_job_workspace(jobs_root, job_id)
    plan = _load_bound_plan(workspace, profile, plan_id)
    gate_path = workspace.artifacts / "gate_decision.json"
    if gate_path.is_file():
        return {"job_id": job_id, "stage": "FINALIZED", "replayed": True, "decision": _read_json(gate_path)}

    original_report = _read_audit(workspace.audit_report)
    if plan.state == "MANUAL_ONLY":
        decision = _finish(workspace, "REJECTED", plan.reason, started=started)
        return {"job_id": job_id, "stage": "FINALIZED", "replayed": False, "decision": decision}

    execution_path = workspace.artifacts / "execution_report.json"
    if not execution_path.is_file():
        raise ValueError("executor evidence is missing; verification cannot start")
    execution = _read_json(execution_path)
    if execution.get("plan_id") != plan_id:
        raise ValueError("executor evidence belongs to a different PatchPlan")

    if execution.get("state") == "FAILED":
        rollback = _rollback_from_execution(workspace, execution)
        decision = _finish(workspace, "FAILED_ROLLBACK", str(execution.get("reason")), started=started, rollback=rollback)
        return {"job_id": job_id, "stage": "FINALIZED", "replayed": False, "decision": decision}

    candidate_report = audit_asset(workspace.working, profile, job_id=job_id)
    _write_json(workspace.artifacts / "regression_audit.json", candidate_report.to_dict())
    target_rules = sorted({rule for step in plan.steps for rule in step.verify_rules})
    regression = compare_audits(
        original_report,
        candidate_report,
        target_rules=target_rules if plan.state == "READY" else (),
        repair_attempted=plan.state == "READY",
    )
    _write_json(workspace.artifacts / "regression_report.json", regression.to_dict())
    append_trace(
        workspace.trace,
        event="verification.completed",
        job_id=job_id,
        details={
            "actor_role": "regression-verifier",
            "plan_id": plan_id,
            "gate_state": regression.gate_state.value,
            "report": "artifacts/regression_report.json",
        },
    )
    if regression.gate_state.value in {"PASS", "REPAIRED_PASS"}:
        release = publish_candidate(
            workspace,
            regression.gate_state.value,
            profile,
            regression_report="artifacts/regression_report.json",
        )
        decision = _finish(
            workspace,
            regression.gate_state.value,
            "independent regression verification passed",
            started=started,
            release=release,
        )
    else:
        rollback = _rollback_from_execution(workspace, execution) if plan.state == "READY" else None
        decision = _finish(
            workspace,
            "FAILED_ROLLBACK" if rollback else "REJECTED",
            "independent regression verification rejected the candidate",
            started=started,
            rollback=rollback,
        )
    return {"job_id": job_id, "stage": "FINALIZED", "replayed": False, "decision": decision}


def _rollback_from_execution(workspace: Any, execution: dict[str, Any]) -> dict[str, Any]:
    checkpoint = execution.get("checkpoint")
    if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get("sha256"), str):
        raise ValueError("executor checkpoint evidence is missing")
    return rollback_to_checkpoint(workspace, "pre-repair", expected_checkpoint_hash=checkpoint["sha256"])


def _load_bound_plan(workspace: Any, profile: QualityProfile, plan_id: str) -> PatchPlan:
    plan_path = workspace.artifacts / "patch_plan.json"
    if not plan_path.is_file():
        raise ValueError("planner evidence is missing; execution is forbidden")
    plan = patch_plan_from_dict(_read_json(plan_path))
    validate_patch_plan(plan, profile)
    if plan.plan_id != plan_id:
        raise ValueError("requested plan_id does not match the frozen PatchPlan")
    return plan


def patch_plan_from_dict(payload: dict[str, Any]) -> PatchPlan:
    profile = payload.get("profile", {})
    steps = tuple(
        RepairStep(
            step_id=str(step["step_id"]),
            finding_ids=tuple(step["finding_ids"]),
            skill=str(step["skill"]),
            operation=str(step["operation"]),
            parameters=dict(step["parameters"]),
            expected_changes=tuple(step["expected_changes"]),
            verify_rules=tuple(step["verify_rules"]),
            risk_level=str(step["risk_level"]),
            rollback_on=tuple(step["rollback_on"]),
        )
        for step in payload.get("steps", [])
    )
    return PatchPlan(
        schema_version=str(payload["schema_version"]),
        plan_id=str(payload["plan_id"]),
        asset_sha256=str(payload["asset_sha256"]),
        profile_id=str(profile["id"]),
        profile_version=str(profile["version"]),
        state=str(payload["state"]),
        steps=steps,
        risk_level=str(payload["risk_level"]),
        approval_required=bool(payload["approval_required"]),
        reason=str(payload["reason"]),
        created_at=str(payload["created_at"]),
    )


def _read_audit(path: Path) -> AuditReport:
    payload = _read_json(path)
    asset = payload["asset"]
    profile = payload["profile"]
    findings = [
        Finding(
            finding_id=str(item["finding_id"]),
            rule_id=str(item["rule_id"]),
            severity=Severity(str(item["severity"])),
            message=str(item["message"]),
            location=dict(item.get("location", {})),
            observed=item.get("observed"),
            expected=item.get("expected"),
            evidence=dict(item.get("evidence", {})),
            repairability=str(item.get("repairability", "MANUAL_ONLY")),
            confidence=float(item.get("confidence", 1.0)),
        )
        for item in payload.get("findings", [])
    ]
    return AuditReport(
        schema_version=str(payload["schema_version"]),
        job_id=str(payload["job_id"]),
        asset_path=str(asset["path"]),
        asset_sha256=str(asset["sha256"]),
        profile_id=str(profile["id"]),
        profile_version=str(profile["version"]),
        measurements=dict(payload.get("measurements", {})),
        findings=findings,
        checks_completed=list(payload.get("checks_completed", [])),
        checks_incomplete=list(payload.get("checks_incomplete", [])),
        created_at=str(payload["created_at"]),
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload
