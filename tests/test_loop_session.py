from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.io_utils import atomic_write_json  # noqa: E402
from sceneguard.loop_session import (  # noqa: E402
    LoopSessionAlreadyRunning,
    LoopSessionLock,
    run_loop_session,
)


def benchmark_fixture(*, score: int = 100, core_status: str = "PASS", release_status: str = "BLOCKED_EXTERNAL") -> dict:
    return {
        "generated_at": "2026-08-10T00:00:00+00:00",
        "core": {
            "status": core_status,
            "score": score,
            "checks": [{"check_id": "fixture", "passed": core_status == "PASS"}],
        },
        "release": {
            "status": release_status,
            "external_evidence": {
                "missing": ["evidence/runtime.json"] if release_status == "BLOCKED_EXTERNAL" else []
            },
        },
        "requirements": {},
        "next_actions": [{"type": "FIX", "check_id": "fixture", "action": "repair fixture"}],
        "stop_policy": {
            "max_iterations": 50,
            "max_consecutive_no_improvement": 3,
            "max_consecutive_same_failure": 3,
        },
    }


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class LoopSessionTests(unittest.TestCase):
    def test_external_blocker_without_watch_does_not_spin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls: list[int] = []

            def runner(*args, **kwargs):
                calls.append(1)
                return benchmark_fixture()

            result = run_loop_session(root, benchmark_runner=runner, session_id="external-once")
            self.assertEqual(result["outcome"], "AWAIT_EXTERNAL_EVIDENCE")
            self.assertEqual(len(calls), 1)
            self.assertEqual(result["session_iterations"], 1)

    def test_failed_core_writes_bounded_agent_work_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def runner(*args, **kwargs):
                return benchmark_fixture(score=80, core_status="FAIL", release_status="FAIL_CORE")

            result = run_loop_session(root, benchmark_runner=runner, session_id="agent-handoff")
            self.assertEqual(result["outcome"], "AGENT_ACTION_REQUIRED")
            work_item = json.loads((root / result["work_item"]).read_text(encoding="utf-8"))
            self.assertTrue(work_item["safety"]["do_not_fabricate_external_evidence"])
            self.assertTrue(work_item["safety"]["stop_on_core_score_regression"])
            receipt = root / "reports/loop-sessions/agent-handoff/benchmark-iteration-001.json"
            self.assertTrue(receipt.is_file())

    def test_watch_external_stops_at_wall_clock_budget_without_rerunning_tests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "benchmark/acceptance.v0.1.json"
            atomic_write_json(config, {"required_release_evidence": ["evidence/runtime.json"]})
            clock = FakeClock()
            calls: list[int] = []

            def runner(*args, **kwargs):
                calls.append(1)
                return benchmark_fixture()

            result = run_loop_session(
                root,
                benchmark_runner=runner,
                session_id="watch-budget",
                watch_external=True,
                max_duration_seconds=5,
                poll_interval_seconds=2,
                monotonic=clock.monotonic,
                sleeper=clock.sleep,
            )
            self.assertEqual(result["outcome"], "STOP_TIME_BUDGET")
            self.assertEqual(len(calls), 1)

    def test_session_lock_rejects_concurrent_supervisor_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "supervisor.lock"
            with LoopSessionLock(lock_path):
                with self.assertRaises(LoopSessionAlreadyRunning):
                    with LoopSessionLock(lock_path):
                        pass
            with LoopSessionLock(lock_path):
                pass

    def test_worker_regression_stops_and_preserves_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = iter(
                [
                    benchmark_fixture(score=90, core_status="FAIL", release_status="FAIL_CORE"),
                    benchmark_fixture(score=80, core_status="FAIL", release_status="FAIL_CORE"),
                ]
            )

            def runner(*args, **kwargs):
                return next(fixtures)

            def checkpoint_builder(project_root: Path, session_dir: Path, iteration: int) -> Path:
                path = session_dir / "checkpoints" / f"iteration-{iteration:03d}.zip"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"recovery")
                return path

            def worker_runner(*args, **kwargs):
                return {"status": "PASS", "exit_code": 0, "duration_ms": 1}

            result = run_loop_session(
                root,
                benchmark_runner=runner,
                worker_command=("explicit-worker",),
                checkpoint_builder=checkpoint_builder,
                worker_runner=worker_runner,
                session_id="regression-stop",
            )
            self.assertEqual(result["outcome"], "REGRESSION_DETECTED")
            self.assertTrue((root / result["recovery_archive"]).is_file())
            self.assertEqual(result["session_iterations"], 2)


if __name__ == "__main__":
    unittest.main()
