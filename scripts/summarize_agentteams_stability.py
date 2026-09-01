#!/usr/bin/env python3
"""Summarize retained five-Agent SceneGuard runs into auditable stability metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_WORKERS = {
    "asset-auditor",
    "repair-planner",
    "repair-executor",
    "regression-verifier",
}
REQUIRED_L1_SKILLS = {
    "asset-profile",
    "package-audit",
    "mesh-validate",
    "repair-plan",
    "mesh-safe-repair",
    "regression-verify",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", action="append", required=True)
    parser.add_argument("--minimum-passes", type=int, default=5)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=ROOT / "jobs" / ".agentteams-native",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "agentteams-stability-latest.json",
    )
    args = parser.parse_args()
    report = summarize(
        run_root=args.run_root,
        run_ids=args.run_id,
        minimum_passes=args.minimum_passes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


def summarize(
    *,
    run_root: Path,
    run_ids: list[str],
    minimum_passes: int,
) -> dict[str, Any]:
    if minimum_passes < 1:
        raise ValueError("minimum_passes must be positive")
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("run_ids must be unique")
    runs = [evaluate_run(run_root, run_id) for run_id in run_ids]
    durations = [item["duration_ms"] for item in runs if isinstance(item["duration_ms"], int)]
    passed_count = sum(item["passed"] for item in runs)
    all_selected_passed = bool(runs) and passed_count == len(runs)
    status = (
        "PASS"
        if all_selected_passed and passed_count >= minimum_passes
        else "FAIL"
    )
    return {
        "schema_version": "0.1",
        "status": status,
        "mode": "validated five-Agent zero-operator Supervisor mode",
        "sample_count": len(runs),
        "minimum_passes": minimum_passes,
        "passed_count": passed_count,
        "failed_count": len(runs) - passed_count,
        "success_rate": passed_count / len(runs) if runs else 0.0,
        "consecutive_selected_runs_passed": all_selected_passed,
        "timing_ms": {
            "minimum": min(durations) if durations else None,
            "median_p50": round(statistics.median(durations)) if durations else None,
            "p90_nearest_rank": nearest_rank(durations, 0.9) if durations else None,
            "maximum": max(durations) if durations else None,
        },
        "business_observation": {
            "operator_actions_after_dispatch": 0 if all_selected_passed else None,
            "published_gate": "REPAIRED_PASS" if all_selected_passed else None,
            "manual_baseline_status": "PENDING_TEAM_MEASUREMENT",
            "claim": (
                "These measurements quantify automated cycle time, success and evidence "
                "coverage only. They do not claim labor savings or ROI before the manual "
                "baseline protocol is completed."
            ),
        },
        "runs": runs,
    }


def evaluate_run(run_root: Path, run_id: str) -> dict[str, Any]:
    path = run_root / run_id / "run-result.json"
    raw = path.read_bytes()
    payload = json.loads(raw)
    tasks = payload.get("tasks") if isinstance(payload.get("tasks"), list) else []
    workers = {item.get("agent_id") for item in tasks if isinstance(item, dict)}
    skills = set(payload.get("skill_ids") or [])
    leader = payload.get("leader") if isinstance(payload.get("leader"), dict) else {}
    invariants = payload.get("invariants") if isinstance(payload.get("invariants"), dict) else {}
    checks = {
        "completed": payload.get("status") == "COMPLETED",
        "repaired_pass": payload.get("gate_state") == "REPAIRED_PASS",
        "five_agents": payload.get("agent_count") == 5,
        "four_workers": payload.get("worker_count") == 4 and workers == REQUIRED_WORKERS,
        "zero_operator_actions": payload.get("operator_actions_after_dispatch") == 0,
        "native_leader_decision": bool(leader.get("native_tool_call")),
        "projectflow_created": leader.get("projectflow_created") is True,
        "four_taskflow_acceptances": leader.get("taskflow_acceptances") == 4,
        "native_worker_decisions": len(tasks) == 4
        and all(bool(item.get("native_tool_call")) for item in tasks),
        "necessary_l1_skills": skills == REQUIRED_L1_SKILLS,
        "cross_report_invariants": invariants.get("passed") is True
        and all((invariants.get("checks") or {}).values()),
        "artifact_hashes": len(payload.get("artifact_hashes") or {}) >= 8,
        "duration_recorded": isinstance(payload.get("duration_ms"), int)
        and payload["duration_ms"] > 0,
    }
    return {
        "run_id": run_id,
        "passed": all(checks.values()),
        "status": payload.get("status"),
        "gate_state": payload.get("gate_state"),
        "duration_ms": payload.get("duration_ms"),
        "plan_id": payload.get("plan_id"),
        "result_sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_completeness": sum(checks.values()) / len(checks),
        "checks": checks,
    }


def nearest_rank(values: list[int], quantile: float) -> int:
    if not values:
        raise ValueError("values must not be empty")
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


if __name__ == "__main__":
    raise SystemExit(main())
