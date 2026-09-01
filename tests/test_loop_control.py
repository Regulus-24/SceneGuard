from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.loop_control import update_loop_state  # noqa: E402


def benchmark_fixture(core_status: str = "FAIL", release_status: str = "FAIL_CORE") -> dict:
    return {
        "generated_at": "2026-08-06T00:00:00+00:00",
        "core": {
            "status": core_status,
            "score": 85 if core_status == "FAIL" else 100,
            "checks": [{"check_id": "contracts.material_sync", "passed": core_status == "PASS"}],
        },
        "release": {
            "status": release_status,
            "external_evidence": {"missing": ["docker runtime"] if release_status != "PASS" else []},
        },
        "next_actions": [],
        "stop_policy": {
            "max_iterations": 50,
            "max_consecutive_no_improvement": 3,
            "max_consecutive_same_failure": 3,
        },
    }


class LoopControlTests(unittest.TestCase):
    def test_repeated_failure_requires_replan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            decisions = [update_loop_state(copy.deepcopy(benchmark_fixture()), path)["decision"] for _ in range(3)]
            self.assertEqual(decisions, ["CONTINUE", "CONTINUE", "REPLAN_REQUIRED"])

    def test_core_pass_with_missing_runtime_waits_for_external_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = update_loop_state(
                benchmark_fixture("PASS", "BLOCKED_EXTERNAL"),
                Path(directory) / "state.json",
            )
            self.assertEqual(result["decision"], "AWAIT_EXTERNAL_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
