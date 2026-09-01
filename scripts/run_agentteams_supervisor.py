from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROFILE = "web-realtime-v0.2.json"
ASSET = "degenerate_triangle.glb"
ROLES = (
    {
        "role": "asset-auditor",
        "container": "hiclaw-worker-sgauto-asset-auditor",
        "model": "qwen3.5:4b",
        "action": "create",
        "tool": "create_scene_job",
        "description": "Create one isolated SceneGuard Job and preserve its initial audit evidence.",
    },
    {
        "role": "repair-planner",
        "container": "hiclaw-worker-sgauto-repair-planner",
        "model": "qwen3.5:4b",
        "action": "plan",
        "tool": "freeze_patch_plan",
        "description": "Inspect the audit evidence and freeze the only policy-valid PatchPlan.",
    },
    {
        "role": "repair-executor",
        "container": "hiclaw-worker-sgauto-repair-executor",
        "model": "qwen3.5:4b",
        "action": "execute",
        "tool": "execute_frozen_plan",
        "description": "Execute only the supplied frozen Plan ID; never verify or publish.",
    },
    {
        "role": "regression-verifier",
        "container": "hiclaw-worker-sgauto-regression-verifier",
        "model": "qwen3.5:4b",
        "action": "verify",
        "tool": "verify_and_finalize",
        "description": "Independently re-audit and exclusively publish or roll back the candidate.",
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validated autonomous SceneGuard AgentTeams supervisor")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-model-retries", type=int, default=2)
    args = parser.parse_args()
    if not args.job_id.replace("-", "").isalnum() or not args.run_id.replace("-", "").isalnum():
        raise SystemExit("job-id and run-id must be alphanumeric/hyphen identifiers")

    evidence_root = ROOT / "jobs" / ".agentteams-supervisor" / args.run_id
    evidence_root.mkdir(parents=True, exist_ok=False)
    trace_path = evidence_root / "supervisor-trace.jsonl"
    previous: dict[str, Any] | None = None
    plan_id: str | None = None
    stage_records = []
    started = time.monotonic()

    for index, config in enumerate(ROLES, start=1):
        expected = {
            "job_id": args.job_id,
            "profile": PROFILE,
            **({"asset": ASSET} if config["action"] == "create" else {}),
            **({"plan_id": plan_id} if config["action"] in {"execute", "verify"} else {}),
        }
        decision, attempt_count = decide(config, expected, previous, args.max_model_retries)
        stage_dir = evidence_root / f"{index:02d}-{config['role']}"
        stage_dir.mkdir()
        write_json(stage_dir / "decision.json", decision)
        append_trace(
            trace_path,
            args.run_id,
            "agent.decision.accepted",
            {"role": config["role"], "action": config["action"], "attempt_count": attempt_count},
        )

        result = execute_in_worker(config, decision["arguments"])
        write_json(stage_dir / "tool-result.json", result)
        result_hash = canonical_sha256(result)
        append_trace(
            trace_path,
            args.run_id,
            "agent.tool.completed",
            {
                "role": config["role"],
                "container": config["container"],
                "action": config["action"],
                "result_sha256": result_hash,
                "ok": result.get("ok"),
            },
        )
        if result.get("ok") is not True:
            write_json(
                evidence_root / "run-result.json",
                {
                    "run_id": args.run_id,
                    "job_id": args.job_id,
                    "status": "FAILED",
                    "failed_role": config["role"],
                    "tool_result_sha256": result_hash,
                },
            )
            return 1
        if config["action"] == "plan":
            plan_id = result["result"]["patch_plan"]["plan_id"]
        previous = result
        stage_records.append(
            {
                "role": config["role"],
                "model": config["model"],
                "container": config["container"],
                "native_tool_call": config["tool"],
                "model_attempts": attempt_count,
                "result_sha256": result_hash,
            }
        )

    final_decision = previous["result"]["decision"] if previous else {}
    invariant = verify_final_invariants(args.job_id, plan_id, final_decision)
    payload = {
        "schema_version": "0.1",
        "run_id": args.run_id,
        "job_id": args.job_id,
        "mode": "AgentTeams workers with deterministic validated supervisor",
        "operator_actions_after_dispatch": 0,
        "status": "COMPLETED" if invariant["passed"] else "FAILED_INVARIANT",
        "gate_state": final_decision.get("gate_state"),
        "plan_id": plan_id,
        "stages": stage_records,
        "invariants": invariant,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "completed_at": datetime.now(UTC).isoformat(),
    }
    write_json(evidence_root / "run-result.json", payload)
    append_trace(trace_path, args.run_id, "run.completed", {"status": payload["status"], "gate_state": payload["gate_state"]})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "COMPLETED" else 1


def decide(
    config: dict[str, str],
    expected: dict[str, Any],
    previous: dict[str, Any] | None,
    max_retries: int,
) -> tuple[dict[str, Any], int]:
    request_payload = {
        "role": config["role"],
        "model": config["model"],
        "tool": config["tool"],
        "description": config["description"],
        "expected": expected,
        "previous": previous,
        "max_retries": max_retries,
    }
    completed = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            config["container"],
            "python3",
            "/opt/sceneguard-tools/sceneguard_role_decider.py",
        ],
        cwd=ROOT,
        input=json.dumps(request_payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{config['role']} Worker returned invalid decision JSON") from exc
    if completed.returncode != 0 or not isinstance(result, dict):
        raise RuntimeError(f"{config['role']} Worker decision failed: {result}")
    if (
        result.get("role") != config["role"]
        or result.get("tool") != config["tool"]
        or result.get("arguments") != expected
        or result.get("decision_runtime") != "inside_agentteams_worker"
    ):
        raise RuntimeError(f"{config['role']} Worker decision violated the supervisor contract")
    attempt_count = int(result["attempt_count"])
    return {
        "schema_version": "0.1",
        "role": config["role"],
        "model": config["model"],
        "tool": config["tool"],
        "arguments": result["arguments"],
        "decision_runtime": result["decision_runtime"],
        "decision_sha256": canonical_sha256({"tool": config["tool"], "arguments": result["arguments"]}),
    }, attempt_count


def execute_in_worker(config: dict[str, str], arguments: dict[str, Any]) -> dict[str, Any]:
    command = [
        "docker",
        "exec",
        config["container"],
        "python3",
        "/opt/sceneguard-tools/sceneguard_client.py",
        config["action"],
    ]
    if config["action"] == "create":
        command.extend([arguments["asset"], arguments["profile"], arguments["job_id"]])
    elif config["action"] == "plan":
        command.extend([arguments["job_id"], arguments["profile"]])
    else:
        command.extend([arguments["job_id"], arguments["profile"], arguments["plan_id"]])
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120, check=False)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{config['role']} returned invalid JSON (exit {completed.returncode})") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{config['role']} returned a non-object JSON result")
    return payload


def verify_final_invariants(job_id: str, plan_id: str | None, decision: dict[str, Any]) -> dict[str, Any]:
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


def append_trace(path: Path, run_id: str, event: str, details: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "schema_version": "0.1",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "run_id": run_id,
                    "event": event,
                    "details": details,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
