from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.benchmark import run_acceptance_benchmark, write_benchmark_receipt  # noqa: E402
from sceneguard.loop_control import update_loop_state  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one evidence-driven SceneGuard engineering iteration")
    parser.add_argument("--target", choices=("core", "release"), default="release")
    parser.add_argument("--config", default=Path("benchmark/acceptance.v0.1.json"), type=Path)
    parser.add_argument("--receipt", default=Path("reports/benchmark-latest.json"), type=Path)
    parser.add_argument("--state", default=Path("reports/loop-state.json"), type=Path)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    benchmark = run_acceptance_benchmark(ROOT, args.config, include_test_suite=not args.skip_tests)
    write_benchmark_receipt(benchmark, ROOT / args.receipt)
    state = update_loop_state(benchmark, ROOT / args.state, target=args.target)
    summary = {
        "iteration": state["iteration"],
        "decision": state["decision"],
        "best_core_score": state["best_core_score"],
        "core_status": benchmark["core"]["status"],
        "release_status": benchmark["release"]["status"],
        "next_actions": benchmark["next_actions"],
        "receipt": str(args.receipt),
        "state": str(args.state),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return {
        "COMPLETE": 0,
        "CONTINUE": 2,
        "REPLAN_REQUIRED": 3,
        "AWAIT_EXTERNAL_EVIDENCE": 4,
        "STOP_ITERATION_LIMIT": 5,
    }[state["decision"]]


if __name__ == "__main__":
    raise SystemExit(main())
