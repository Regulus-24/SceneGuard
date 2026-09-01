from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io_utils import atomic_write_json


def update_loop_state(
    benchmark: dict[str, Any],
    state_path: str | Path,
    *,
    target: str = "release",
) -> dict[str, Any]:
    if target not in {"core", "release"}:
        raise ValueError("target must be core or release")
    path = Path(state_path)
    previous = _load_state(path)
    core = benchmark["core"]
    release = benchmark["release"]
    score = int(core["score"])
    failed_checks = sorted(item["check_id"] for item in core["checks"] if not item["passed"])
    missing_external = sorted(release["external_evidence"]["missing"])
    fingerprint = json.dumps(
        {"failed_checks": failed_checks, "missing_external": missing_external},
        sort_keys=True,
        separators=(",", ":"),
    )

    best_score = max(int(previous.get("best_core_score", 0)), score)
    improved = score > int(previous.get("best_core_score", -1))
    no_improvement = 0 if improved else int(previous.get("consecutive_no_improvement", 0)) + 1
    same_failure = (
        int(previous.get("consecutive_same_failure", 0)) + 1
        if fingerprint == previous.get("last_failure_fingerprint")
        else 1
    )
    iteration = int(previous.get("iteration", 0)) + 1
    policy = benchmark["stop_policy"]
    decision = _decision(
        target=target,
        core_status=core["status"],
        release_status=release["status"],
        iteration=iteration,
        no_improvement=no_improvement,
        same_failure=same_failure,
        policy=policy,
    )
    receipt = {
        "iteration": iteration,
        "generated_at": benchmark["generated_at"],
        "core_score": score,
        "core_status": core["status"],
        "release_status": release["status"],
        "failed_checks": failed_checks,
        "missing_external": missing_external,
        "improved": improved,
        "decision": decision,
    }
    history = list(previous.get("history", []))
    history.append(receipt)
    history = history[-20:]
    state = {
        "schema_version": "0.1",
        "updated_at": datetime.now(UTC).isoformat(),
        "target": target,
        "iteration": iteration,
        "best_core_score": best_score,
        "consecutive_no_improvement": no_improvement,
        "consecutive_same_failure": same_failure,
        "last_failure_fingerprint": fingerprint,
        "decision": decision,
        "next_actions": benchmark["next_actions"],
        "history": history,
    }
    atomic_write_json(path, state)
    return state


def _decision(
    *,
    target: str,
    core_status: str,
    release_status: str,
    iteration: int,
    no_improvement: int,
    same_failure: int,
    policy: dict[str, Any],
) -> str:
    if target == "core" and core_status == "PASS":
        return "COMPLETE"
    if target == "release" and release_status == "PASS":
        return "COMPLETE"
    if iteration >= int(policy["max_iterations"]):
        return "STOP_ITERATION_LIMIT"
    if core_status == "PASS" and release_status == "BLOCKED_EXTERNAL":
        return "AWAIT_EXTERNAL_EVIDENCE"
    if (
        no_improvement >= int(policy["max_consecutive_no_improvement"])
        or same_failure >= int(policy["max_consecutive_same_failure"])
    ):
        return "REPLAN_REQUIRED"
    return "CONTINUE"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "0.1":
        raise ValueError("unsupported loop state schema")
    return payload
