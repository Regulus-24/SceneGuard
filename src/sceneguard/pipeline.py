from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit import audit_asset
from .models import PatchPlan, RepairStep
from .planner import build_patch_plan, validate_patch_plan
from .profile import QualityProfile
from .regression import compare_audits
from .repair import remove_degenerate_triangles, resize_embedded_textures
from .workspace import (
    append_trace,
    create_checkpoint,
    create_job_workspace,
    load_job_workspace,
    publish_candidate,
    rollback_to_checkpoint,
    sha256_file,
)


def run_job(
    asset: str | Path,
    profile: QualityProfile,
    jobs_root: str | Path,
    job_id: str | None = None,
    auto_repair: bool = True,
    fault_injection: str | None = None,
    approval_decision: str | None = None,
    approval_actor: str = "demo-user",
    request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the deterministic SceneGuard gate from intake through publish or rollback."""
    started = time.monotonic()
    if fault_injection not in {
        None,
        "tamper_before_execute",
        "tool_error_after_execute",
        "corrupt_after_execute",
    }:
        raise ValueError("unsupported fault injection")
    if approval_decision not in {None, "APPROVE", "REJECT"}:
        raise ValueError("approval_decision must be APPROVE, REJECT or omitted")
    profile.validate()
    workspace, _ = create_job_workspace(asset, jobs_root, profile, job_id)
    if request_context:
        append_trace(
            workspace.trace,
            event="gateway.request.accepted",
            job_id=workspace.job_id,
            details={
                "request_id": request_context.get("request_id"),
                "input_sha256": request_context.get("input_sha256"),
                "idempotency_key_sha256": request_context.get("idempotency_key_sha256"),
            },
        )
    original_report = audit_asset(workspace.working, profile, job_id=workspace.job_id)
    plan = build_patch_plan(original_report, profile)
    validate_patch_plan(plan, profile)
    _write_json(workspace.artifacts / "patch_plan.json", plan.to_dict())
    append_trace(
        workspace.trace,
        event="plan.completed",
        job_id=workspace.job_id,
        details={"state": plan.state, "risk_level": plan.risk_level, "plan": "artifacts/patch_plan.json"},
    )

    if plan.state == "NO_ACTION":
        release = publish_candidate(workspace, "PASS", profile)
        return _finish(workspace, "PASS", "asset passed without repair", started=started, release=release)

    if plan.state != "READY":
        return _finish(workspace, "REJECTED", plan.reason, started=started)

    if plan.approval_required:
        request = {
            "schema_version": "0.1",
            "job_id": workspace.job_id,
            "plan_id": plan.plan_id,
            "asset_sha256": plan.asset_sha256,
            "risk_level": plan.risk_level,
            "requested_at": datetime.now(UTC).isoformat(),
        }
        _write_json(workspace.artifacts / "approval_request.json", request)
        append_trace(
            workspace.trace,
            event="approval.requested",
            job_id=workspace.job_id,
            details={"plan_id": plan.plan_id, "asset_sha256": plan.asset_sha256, "risk_level": plan.risk_level},
        )
        if approval_decision is None:
            return _finish(
                workspace,
                "NEED_APPROVAL",
                f"{plan.risk_level} repair requires a human decision bound to the PatchPlan",
                started=started,
            )
        approval = {
            **request,
            "approval_id": f"approval-{uuid4().hex[:12]}",
            "decision": approval_decision,
            "actor": approval_actor,
            "decided_at": datetime.now(UTC).isoformat(),
        }
        _write_json(workspace.artifacts / "approval_record.json", approval)
        append_trace(
            workspace.trace,
            event="approval.decided",
            job_id=workspace.job_id,
            details={
                "approval_id": approval["approval_id"],
                "plan_id": plan.plan_id,
                "asset_sha256": plan.asset_sha256,
                "decision": approval_decision,
                "actor": approval_actor,
            },
        )
        if approval_decision == "REJECT":
            return _finish(
                workspace,
                "REJECTED",
                "human reviewer rejected the L2 PatchPlan",
                started=started,
            )
    elif approval_decision is not None:
        raise ValueError("approval_decision was supplied for a plan that does not require approval")

    if not auto_repair:
        return _finish(
            workspace,
            "NEED_APPROVAL",
            "eligible repair exists but auto-repair was disabled",
            started=started,
        )

    return _execute_ready_plan(
        workspace,
        profile,
        original_report,
        plan,
        started=started,
        fault_injection=fault_injection,
    )


def decide_pending_job(
    jobs_root: str | Path,
    profile: QualityProfile,
    job_id: str,
    decision: str,
    *,
    approval_actor: str = "demo-user",
    fault_injection: str | None = None,
) -> dict[str, Any]:
    """Apply a human decision to the exact pending PatchPlan and continue the same job."""
    started = time.monotonic()
    if decision not in {"APPROVE", "REJECT"}:
        raise ValueError("decision must be APPROVE or REJECT")
    if fault_injection not in {None, "tamper_before_execute", "tool_error_after_execute", "corrupt_after_execute"}:
        raise ValueError("unsupported fault injection")
    workspace = load_job_workspace(jobs_root, job_id)
    gate = json.loads((workspace.artifacts / "gate_decision.json").read_text(encoding="utf-8"))
    if gate.get("gate_state") != "NEED_APPROVAL":
        raise ValueError("job is not waiting for an approval decision")
    if (workspace.artifacts / "approval_record.json").exists():
        raise ValueError("job already has an approval decision")

    plan = _patch_plan_from_dict(
        json.loads((workspace.artifacts / "patch_plan.json").read_text(encoding="utf-8"))
    )
    validate_patch_plan(plan, profile)
    if plan.state != "READY" or not plan.approval_required:
        raise ValueError("PatchPlan is not eligible for approval")
    if sha256_file(workspace.working) != plan.asset_sha256:
        raise ValueError("working asset no longer matches the pending PatchPlan")

    request_path = workspace.artifacts / "approval_request.json"
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if request.get("plan_id") != plan.plan_id or request.get("asset_sha256") != plan.asset_sha256:
        raise ValueError("approval request does not match the pending PatchPlan")
    approval = {
        **request,
        "approval_id": f"approval-{uuid4().hex[:12]}",
        "decision": decision,
        "actor": approval_actor,
        "decided_at": datetime.now(UTC).isoformat(),
    }
    _write_json(workspace.artifacts / "approval_record.json", approval)
    append_trace(
        workspace.trace,
        event="approval.decided",
        job_id=workspace.job_id,
        details={
            "approval_id": approval["approval_id"],
            "plan_id": plan.plan_id,
            "asset_sha256": plan.asset_sha256,
            "decision": decision,
            "actor": approval_actor,
        },
    )
    if decision == "REJECT":
        return _finish(
            workspace,
            "REJECTED",
            "human reviewer rejected the L2 PatchPlan",
            started=started,
        )

    original_report = audit_asset(workspace.working, profile, job_id=workspace.job_id)
    return _execute_ready_plan(
        workspace,
        profile,
        original_report,
        plan,
        started=started,
        fault_injection=fault_injection,
    )


def _patch_plan_from_dict(payload: dict[str, Any]) -> PatchPlan:
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


def _execute_ready_plan(
    workspace: Any,
    profile: QualityProfile,
    original_report: Any,
    plan: PatchPlan,
    *,
    started: float,
    fault_injection: str | None,
) -> dict[str, Any]:
    checkpoint = create_checkpoint(workspace, "pre-repair", expected_working_hash=plan.asset_sha256)
    target_rules = sorted(
        {finding.rule_id for finding in original_report.findings if finding.repairability == "AUTO_CANDIDATE"}
    )
    try:
        if fault_injection == "tamper_before_execute":
            with workspace.working.open("ab") as stream:
                stream.write(b"SCENEGUARD_PRE_EXECUTE_TAMPER")
            append_trace(
                workspace.trace,
                event="demo.fault_injected",
                job_id=workspace.job_id,
                details={"mode": fault_injection},
            )
        step = plan.steps[0]
        if step.operation == "remove_degenerate_triangles":
            result = remove_degenerate_triangles(workspace.working, expected_sha256=plan.asset_sha256)
            result_summary = {"removed_triangle_count": result.removed_triangle_count}
        elif step.operation == "resize_embedded_textures":
            result = resize_embedded_textures(
                workspace.working,
                expected_sha256=plan.asset_sha256,
                max_dimension=int(step.parameters["max_dimension"]),
            )
            result_summary = {"resized_image_count": result.resized_image_count}
        else:
            raise ValueError(f"unsupported planned operation: {step.operation}")
        _write_json(workspace.artifacts / "execution_report.json", result.to_dict())
        append_trace(
            workspace.trace,
            event="repair.executed",
            job_id=workspace.job_id,
            details={
                "operation": result.operation,
                **result_summary,
                "before_sha256": result.before_sha256,
                "after_sha256": result.after_sha256,
                "report": "artifacts/execution_report.json",
            },
        )
        if fault_injection == "tool_error_after_execute":
            append_trace(
                workspace.trace,
                event="demo.fault_injected",
                job_id=workspace.job_id,
                details={"mode": fault_injection},
            )
            raise RuntimeError("injected tool failure after execution")
        if fault_injection == "corrupt_after_execute":
            with workspace.working.open("ab") as stream:
                stream.write(b"SCENEGUARD_FAULT")
            append_trace(
                workspace.trace,
                event="demo.fault_injected",
                job_id=workspace.job_id,
                details={"mode": fault_injection},
            )

        candidate_report = audit_asset(workspace.working, profile, job_id=workspace.job_id)
        _write_json(workspace.artifacts / "regression_audit.json", candidate_report.to_dict())
        regression = compare_audits(
            original_report,
            candidate_report,
            target_rules=target_rules,
            repair_attempted=True,
        )
        _write_json(workspace.artifacts / "regression_report.json", regression.to_dict())
        append_trace(
            workspace.trace,
            event="verification.completed",
            job_id=workspace.job_id,
            details={"gate_state": regression.gate_state.value, "report": "artifacts/regression_report.json"},
        )
        if regression.gate_state.value == "REPAIRED_PASS":
            release = publish_candidate(
                workspace,
                "REPAIRED_PASS",
                profile,
                regression_report="artifacts/regression_report.json",
            )
            return _finish(
                workspace,
                "REPAIRED_PASS",
                (
                    f"removed {result.removed_triangle_count} degenerate triangle(s) and passed regression"
                    if step.operation == "remove_degenerate_triangles"
                    else f"resized {result.resized_image_count} embedded texture(s) and passed regression"
                ),
                started=started,
                release=release,
            )
        reason = "post-repair regression did not satisfy the release gate"
    except Exception as exc:
        reason = f"repair or verification failed: {type(exc).__name__}: {exc}"
        _write_json(
            workspace.artifacts / "failure_report.json",
            {"schema_version": "0.1", "job_id": workspace.job_id, "reason": reason},
        )
        append_trace(
            workspace.trace,
            event="pipeline.failed",
            job_id=workspace.job_id,
            details={"reason": reason, "report": "artifacts/failure_report.json"},
        )

    rollback = rollback_to_checkpoint(
        workspace,
        "pre-repair",
        expected_checkpoint_hash=checkpoint["sha256"],
    )
    return _finish(workspace, "FAILED_ROLLBACK", reason, started=started, rollback=rollback)


def _finish(
    workspace: Any,
    gate_state: str,
    reason: str,
    started: float,
    release: dict[str, Any] | None = None,
    rollback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "0.1",
        "job_id": workspace.job_id,
        "gate_state": gate_state,
        "reason": reason,
        "original_sha256": sha256_file(workspace.original),
        "working_sha256": sha256_file(workspace.working),
        "published": release is not None,
        "release": release,
        "rollback": rollback,
        "artifacts": {
            "audit_report": "artifacts/audit_report.json",
            "patch_plan": "artifacts/patch_plan.json",
            "trace": "artifacts/trace.jsonl",
            "gate_decision": "artifacts/gate_decision.json",
            "metrics": "artifacts/metrics.json",
            "approval_request": (
                "artifacts/approval_request.json"
                if (workspace.artifacts / "approval_request.json").is_file()
                else None
            ),
            "approval_record": (
                "artifacts/approval_record.json"
                if (workspace.artifacts / "approval_record.json").is_file()
                else None
            ),
        },
        "completed_at": datetime.now(UTC).isoformat(),
    }
    _write_json(workspace.artifacts / "gate_decision.json", payload)
    append_trace(
        workspace.trace,
        event="gate.decided",
        job_id=workspace.job_id,
        details={"gate_state": gate_state, "reason": reason, "published": release is not None},
    )
    audit_payload = json.loads(workspace.audit_report.read_text(encoding="utf-8"))
    trace_lines = workspace.trace.read_text(encoding="utf-8").splitlines()
    metrics = {
        "schema_version": "0.1",
        "job_id": workspace.job_id,
        "gate_state": gate_state,
        "end_to_end_duration_ms": round((time.monotonic() - started) * 1000),
        "initial_error_count": audit_payload["summary"]["error_count"],
        "initial_warning_count": audit_payload["summary"]["warning_count"],
        "repair_attempted": (workspace.artifacts / "execution_report.json").is_file(),
        "rollback_completed": rollback is not None and bool(rollback.get("success")),
        "published": release is not None,
        "approval_required": (workspace.artifacts / "approval_request.json").is_file(),
        "approval_decided": (workspace.artifacts / "approval_record.json").is_file(),
        "trace_event_count": len(trace_lines),
        "artifact_file_count": sum(path.is_file() for path in workspace.artifacts.iterdir()),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    _write_json(workspace.artifacts / "metrics.json", metrics)
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
