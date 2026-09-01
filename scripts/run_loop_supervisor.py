from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.loop_session import LoopSessionAlreadyRunning, run_loop_session  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a bounded SceneGuard benchmark/worker supervision session (worker command must be explicit)."
    )
    parser.add_argument("--target", choices=("core", "release"), default="release")
    parser.add_argument("--hours", type=float, default=10.0, help="wall-clock budget, at most 24 hours")
    parser.add_argument("--poll-seconds", type=float, default=60.0)
    parser.add_argument("--worker-timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--watch-external", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--session-id")
    parser.add_argument(
        "--worker-command",
        nargs=argparse.REMAINDER,
        help="explicit argv executed without a shell; receives SCENEGUARD_LOOP_WORK_ITEM",
    )
    args = parser.parse_args()
    try:
        result = run_loop_session(
            ROOT,
            target=args.target,
            max_duration_seconds=args.hours * 60 * 60,
            poll_interval_seconds=args.poll_seconds,
            watch_external=args.watch_external,
            include_tests=not args.skip_tests,
            worker_command=args.worker_command,
            worker_timeout_seconds=args.worker_timeout_seconds,
            session_id=args.session_id,
        )
    except LoopSessionAlreadyRunning as exc:
        print(json.dumps({"outcome": "ALREADY_RUNNING", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 9
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {
        "COMPLETE": 0,
        "AWAIT_EXTERNAL_EVIDENCE": 4,
        "STOP_ITERATION_LIMIT": 5,
        "STOP_TIME_BUDGET": 5,
        "AGENT_ACTION_REQUIRED": 6,
        "WORKER_FAILED": 7,
        "REGRESSION_DETECTED": 8,
    }.get(result["outcome"], 10)


if __name__ == "__main__":
    raise SystemExit(main())
