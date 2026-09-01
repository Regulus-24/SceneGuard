#!/usr/bin/env python3
"""Run a validated zero-operator 1 TeamLeader + 4 Worker AgentTeams chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = ROOT / "scripts" / "agentteams_container_bridge.py"
BRIDGE_TARGET = "/opt/sceneguard-tools/agentteams_container_bridge.py"
TEAM = "sceneguard-auto-v1"
TEAM_ROOM = "room:!hBkcVV9fSCyavvO9as:matrix-local.hiclaw.io:18080"
ASSET = "mixed_valid_degenerate.glb"
PROFILE = "web-realtime-v0.5-visual-demo.json"

LEADER = {
    "agent_id": "scene-guard-leader",
    "runtime_name": "sceneguard-auto-v1-leader",
    "container": "hiclaw-worker-sceneguard-auto-v1-leader",
    "model": "qwen3.5:9b",
    "skills": ["asset-profile"],
}
STAGES = [
    {
        "agent_id": "asset-auditor",
        "runtime_name": "sgauto-asset-auditor",
        "container": "hiclaw-worker-sgauto-asset-auditor",
        "model": "qwen3.5:4b",
        "stage": "create",
        "description": "Create an isolated SceneGuard Job and retain its initial package and mesh audit evidence.",
        "skills": ["package-audit", "mesh-validate"],
    },
    {
        "agent_id": "repair-planner",
        "runtime_name": "sgauto-repair-planner",
        "container": "hiclaw-worker-sgauto-repair-planner",
        "model": "qwen3.5:4b",
        "stage": "plan",
        "description": "Freeze the only Profile-valid repair plan bound to the exact Job and input hash.",
        "skills": ["repair-plan"],
    },
    {
        "agent_id": "repair-executor",
        "runtime_name": "sgauto-repair-executor",
        "container": "hiclaw-worker-sgauto-repair-executor",
        "model": "qwen3.5:4b",
        "stage": "execute",
        "description": "Execute only the frozen L1 mesh repair plan on the isolated working copy.",
        "skills": ["mesh-safe-repair"],
    },
    {
        "agent_id": "regression-verifier",
        "runtime_name": "sgauto-regression-verifier",
        "container": "hiclaw-worker-sgauto-regression-verifier",
        "model": "qwen3.5:4b",
        "stage": "verify",
        "description": "Independently re-audit the candidate and exclusively publish or roll it back.",
        "skills": ["package-audit", "mesh-validate", "regression-verify"],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--max-model-retries", type=int, default=2)
    args = parser.parse_args()
    for name, value in {
        "run-id": args.run_id,
        "job-id": args.job_id,
        "project-id": args.project_id or args.run_id,
    }.items():
        if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise SystemExit(f"{name} must match [A-Za-z0-9_-]+")

    project_id = args.project_id or args.run_id
    evidence_root = ROOT / "jobs" / ".agentteams-native" / args.run_id
    evidence_root.mkdir(parents=True, exist_ok=False)
    trace_path = evidence_root / "control-trace.jsonl"
    started = time.monotonic()
    task_specs = build_tasks(project_id, args.job_id)
    stage_records: list[dict[str, Any]] = []

    try:
        verify_runtime()
        deploy_bridge()
        append_trace(trace_path, args.run_id, "runtime.ready", {"team": TEAM, "containers": container_names()})

        leader_init = invoke(
            LEADER["container"],
            {
                "mode": "leader_init",
                "team": TEAM,
                "run_id": args.run_id,
                "project_id": project_id,
                "job_id": args.job_id,
                "asset": ASSET,
                "profile": PROFILE,
                "room_id": TEAM_ROOM,
                "model": LEADER["model"],
                "skills": ",".join(LEADER["skills"]),
                "tasks": task_specs,
                "max_retries": args.max_model_retries,
            },
        )
        require_ok("leader_init", leader_init)
        write_json(evidence_root / "00-team-leader-init.json", leader_init)
        append_trace(
            trace_path,
            args.run_id,
            "leader.project.created",
            {
                "project_id": project_id,
                "task_ids": [task["taskId"] for task in task_specs],
                "decision_sha256": leader_init["decision"]["decision_sha256"],
            },
        )

        previous_summary: dict[str, Any] | None = {
            "leader_decision_sha256": leader_init["decision"]["decision_sha256"],
            "project_id": project_id,
        }
        plan_id: str | None = None
        final_tool_result: dict[str, Any] | None = None

        for index, stage in enumerate(STAGES):
            task = task_specs[index]
            arguments: dict[str, str] = {
                "job_id": args.job_id,
                "profile": PROFILE,
            }
            if stage["stage"] == "create":
                arguments["asset"] = ASSET
            if stage["stage"] in {"execute", "verify"}:
                if not plan_id:
                    raise RuntimeError(f"{stage['stage']} cannot run without frozen plan_id")
                arguments["plan_id"] = plan_id

            worker = invoke(
                stage["container"],
                {
                    "mode": "worker_run",
                    "team": TEAM,
                    "task_id": task["taskId"],
                    "role": stage["agent_id"],
                    "stage": stage["stage"],
                    "model": stage["model"],
                    "description": stage["description"],
                    "arguments": arguments,
                    "skill_ids": stage["skills"],
                    "previous": previous_summary,
                    "max_retries": args.max_model_retries,
                },
            )
            require_ok(stage["agent_id"], worker)
            write_json(evidence_root / f"{index + 1:02d}-{stage['agent_id']}.json", worker)
            append_trace(
                trace_path,
                args.run_id,
                "worker.task.submitted",
                {
                    "agent_id": stage["agent_id"],
                    "task_id": task["taskId"],
                    "skill_ids": stage["skills"],
                    "decision_sha256": worker["decision"]["decision_sha256"],
                    "tool_result_sha256": worker["tool_result_sha256"],
                },
            )

            if stage["stage"] == "plan":
                plan_id = required_nested(
                    worker,
                    "tool_result",
                    "result",
                    "patch_plan",
                    "plan_id",
                )
            final_tool_result = worker["tool_result"]
            previous_summary = {
                "agent_id": stage["agent_id"],
                "task_id": task["taskId"],
                "tool_result_sha256": worker["tool_result_sha256"],
                "ok": True,
                **({"plan_id": plan_id} if plan_id else {}),
            }

            next_task = task_specs[index + 1] if index + 1 < len(task_specs) else None
            accepted = invoke(
                LEADER["container"],
                {
                    "mode": "leader_accept",
                    "team": TEAM,
                    "project_id": project_id,
                    "completed_task_id": task["taskId"],
                    "room_id": TEAM_ROOM,
                    "next_task": next_task,
                },
            )
            require_ok(f"leader_accept_{task['taskId']}", accepted)
            write_json(evidence_root / f"{index + 1:02d}-leader-accept.json", accepted)
            append_trace(
                trace_path,
                args.run_id,
                "leader.task.accepted",
                {
                    "task_id": task["taskId"],
                    "next_task_id": next_task["taskId"] if next_task else None,
                },
            )
            stage_records.append(
                {
                    "agent_id": stage["agent_id"],
                    "runtime_name": stage["runtime_name"],
                    "container": stage["container"],
                    "model": stage["model"],
                    "task_id": task["taskId"],
                    "skills": stage["skills"],
                    "native_tool_call": worker["decision"]["tool"],
                    "decision_sha256": worker["decision"]["decision_sha256"],
                    "tool_result_sha256": worker["tool_result_sha256"],
                }
            )

        if final_tool_result is None:
            raise RuntimeError("Verifier produced no final tool result")
        decision = required_nested(final_tool_result, "result", "decision")
        invariant = verify_invariants(args.job_id, plan_id, decision)
        result = {
            "schema_version": "0.2",
            "run_id": args.run_id,
            "job_id": args.job_id,
            "project_id": project_id,
            "team": TEAM,
            "mode": "five AgentTeams containers with validated zero-operator supervisor",
            "agent_count": 5,
            "worker_count": 4,
            "operator_actions_after_dispatch": 0,
            "status": "COMPLETED" if invariant["passed"] else "FAILED_INVARIANT",
            "gate_state": decision.get("gate_state"),
            "plan_id": plan_id,
            "leader": {
                "agent_id": LEADER["agent_id"],
                "container": LEADER["container"],
                "model": LEADER["model"],
                "skills": LEADER["skills"],
                "native_tool_call": leader_init["decision"]["tool"],
                "decision_sha256": leader_init["decision"]["decision_sha256"],
                "projectflow_created": True,
                "taskflow_acceptances": 4,
            },
            "tasks": stage_records,
            "skill_ids": sorted({*LEADER["skills"], *(skill for stage in STAGES for skill in stage["skills"])}),
            "invariants": invariant,
            "artifact_hashes": artifact_hashes(args.job_id),
            "business_metrics": read_json(ROOT / "jobs" / args.job_id / "artifacts" / "metrics.json"),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "completed_at": datetime.now(UTC).isoformat(),
            "claim_boundary": (
                "Validated five-Agent Supervisor mode: all five model decisions and business actions "
                "ran inside AgentTeams containers; the host enforced the finite state machine. "
                "This is not claimed as free-form native Matrix orchestration."
            ),
        }
        write_json(evidence_root / "run-result.json", result)

        finalized = invoke(
            LEADER["container"],
            {
                "mode": "leader_finalize",
                "team": TEAM,
                "project_id": project_id,
                "result": result,
            },
        )
        require_ok("leader_finalize", finalized)
        write_json(evidence_root / "05-team-leader-finalize.json", finalized)
        append_trace(
            trace_path,
            args.run_id,
            "run.completed",
            {
                "status": result["status"],
                "gate_state": result["gate_state"],
                "result_sha256": finalized["result_sha256"],
            },
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "COMPLETED" else 1
    except Exception as exc:
        failure = {
            "schema_version": "0.2",
            "run_id": args.run_id,
            "job_id": args.job_id,
            "project_id": project_id,
            "status": "FAILED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "operator_actions_after_dispatch": 0,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        write_json(evidence_root / "run-result.json", failure)
        append_trace(trace_path, args.run_id, "run.failed", {"error_type": type(exc).__name__, "error": str(exc)})
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1


def build_tasks(project_id: str, job_id: str) -> list[dict[str, Any]]:
    titles = [
        "Audit package and mesh",
        "Freeze Profile-bound repair plan",
        "Execute frozen L1 repair",
        "Independently verify and finalize",
    ]
    specs = [
        (
            f"# Asset audit\n\nJob: `{job_id}`\nAsset: `{ASSET}`\nProfile: `{PROFILE}`\n\n"
            "Use only package-audit and mesh-validate. Create the isolated Job, retain the exact "
            "input hash and complete audit JSON, then submit machine deliverables."
        ),
        (
            f"# Repair planning\n\nJob: `{job_id}`\nProfile: `{PROFILE}`\n\n"
            "Use only repair-plan. Accept the upstream audit as machine evidence, freeze one "
            "hash/Profile-bound whitelist PatchPlan, and never execute it."
        ),
        (
            f"# Repair execution\n\nJob: `{job_id}`\nProfile: `{PROFILE}`\n\n"
            "Use only mesh-safe-repair. Execute the exact frozen plan on the working copy, retain "
            "checkpoint and before/after hashes, and do not verify or publish."
        ),
        (
            f"# Regression verification\n\nJob: `{job_id}`\nProfile: `{PROFILE}`\n\n"
            "Use package-audit, mesh-validate and regression-verify. Independently re-audit, "
            "publish only on REPAIRED_PASS, otherwise force rollback."
        ),
    ]
    tasks = []
    for index, (stage, title, spec) in enumerate(zip(STAGES, titles, specs), start=1):
        task_id = f"{project_id}-{index:02d}"
        tasks.append(
            {
                "taskId": task_id,
                "title": title,
                "assignedTo": stage["runtime_name"],
                "dependsOn": [] if index == 1 else [f"{project_id}-{index - 1:02d}"],
                "spec": spec,
            }
        )
    return tasks


def verify_runtime() -> None:
    completed = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    running = set(completed.stdout.splitlines())
    missing = sorted(set(container_names()) - running)
    if completed.returncode != 0 or missing:
        raise RuntimeError(f"AgentTeams containers not ready: {missing}")
    if not BRIDGE_SOURCE.is_file():
        raise RuntimeError(f"missing container bridge source: {BRIDGE_SOURCE}")

    team_query = subprocess.run(
        [
            "docker",
            "exec",
            LEADER["container"],
            "hiclaw",
            "get",
            "teams",
            TEAM,
            "-o",
            "json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if team_query.returncode != 0:
        raise RuntimeError(f"cannot lock authoritative Team topology: {team_query.stderr.strip()}")
    try:
        team = json.loads(team_query.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Team topology query returned invalid JSON") from exc
    expected_workers = {stage["runtime_name"] for stage in STAGES}
    actual_workers = {str(item) for item in team.get("workerNames", [])}
    checks = {
        "name": team.get("name") == TEAM,
        "phase": team.get("phase") == "Active",
        "leader": team.get("leaderName") == LEADER["runtime_name"],
        "workers": actual_workers == expected_workers,
        "ready_workers": team.get("readyWorkers") == 4,
        "total_workers": team.get("totalWorkers") == 4,
        "room": team.get("teamRoomID") == TEAM_ROOM.removeprefix("room:"),
    }
    if not all(checks.values()):
        raise RuntimeError(f"authoritative Team topology mismatch: {checks}")


def deploy_bridge() -> None:
    for container in container_names():
        mkdir = subprocess.run(
            ["docker", "exec", container, "mkdir", "-p", "/opt/sceneguard-tools"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if mkdir.returncode != 0:
            raise RuntimeError(f"cannot prepare bridge directory in {container}: {mkdir.stderr.strip()}")
        copied = subprocess.run(
            ["docker", "cp", str(BRIDGE_SOURCE), f"{container}:{BRIDGE_TARGET}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if copied.returncode != 0:
            raise RuntimeError(f"cannot deploy bridge to {container}: {copied.stderr.strip()}")


def container_names() -> list[str]:
    return [LEADER["container"], *(stage["container"] for stage in STAGES)]


def invoke(container: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = {
        **payload,
        "team": TEAM,
        "team_leader": LEADER["runtime_name"],
        "team_workers": [stage["runtime_name"] for stage in STAGES],
    }
    completed = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "/opt/venv/copaw/bin/python",
            BRIDGE_TARGET,
        ],
        cwd=ROOT,
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{container} returned invalid JSON (exit {completed.returncode}): "
            f"{completed.stderr[-800:]}"
        ) from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"{container} returned a non-object result")
    if completed.returncode != 0 and result.get("ok") is not False:
        raise RuntimeError(f"{container} bridge failed: {result}")
    return result


def require_ok(step: str, payload: dict[str, Any]) -> None:
    if payload.get("ok") is not True:
        raise RuntimeError(f"{step} failed: {json.dumps(payload, ensure_ascii=False)[:1800]}")


def verify_invariants(job_id: str, plan_id: str | None, decision: dict[str, Any]) -> dict[str, Any]:
    artifacts = ROOT / "jobs" / job_id / "artifacts"
    plan = read_json(artifacts / "patch_plan.json")
    execution = read_json(artifacts / "execution_report.json")
    regression = read_json(artifacts / "regression_report.json")
    release = read_json(artifacts / "release_attestation.json")
    checks = {
        "plan_id_frozen": plan.get("plan_id") == plan_id == execution.get("plan_id"),
        "execution_to_regression_hash": execution.get("after_sha256") == regression.get("candidate_sha256"),
        "gate_agrees": decision.get("gate_state") == regression.get("gate_state") == release.get("gate_state"),
        "published_hash_agrees": decision.get("working_sha256") == release.get("published_sha256"),
        "terminal_repaired_pass": decision.get("gate_state") == "REPAIRED_PASS" and decision.get("published") is True,
    }
    return {"passed": all(checks.values()), "checks": checks}


def artifact_hashes(job_id: str) -> dict[str, str]:
    root = ROOT / "jobs" / job_id / "artifacts"
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir())
        if path.is_file()
    }


def required_nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise RuntimeError(f"missing required result field: {'.'.join(keys)}")
        current = current[key]
    return current


def append_trace(path: Path, run_id: str, event: str, details: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "schema_version": "0.2",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "run_id": run_id,
                    "event": event,
                    "details": details,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
