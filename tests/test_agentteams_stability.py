from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "summarize_agentteams_stability",
    ROOT / "scripts" / "summarize_agentteams_stability.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def successful_result(run_id: str, duration_ms: int) -> dict:
    return {
        "run_id": run_id,
        "status": "COMPLETED",
        "gate_state": "REPAIRED_PASS",
        "agent_count": 5,
        "worker_count": 4,
        "operator_actions_after_dispatch": 0,
        "plan_id": f"plan-{run_id}",
        "duration_ms": duration_ms,
        "leader": {
            "native_tool_call": "coordinate_agentteams_project",
            "projectflow_created": True,
            "taskflow_acceptances": 4,
        },
        "tasks": [
            {"agent_id": "asset-auditor", "native_tool_call": "create_scene_job"},
            {"agent_id": "repair-planner", "native_tool_call": "freeze_patch_plan"},
            {"agent_id": "repair-executor", "native_tool_call": "execute_frozen_plan"},
            {"agent_id": "regression-verifier", "native_tool_call": "verify_and_finalize"},
        ],
        "skill_ids": sorted(MODULE.REQUIRED_L1_SKILLS),
        "invariants": {"passed": True, "checks": {"one": True, "two": True}},
        "artifact_hashes": {f"artifact-{index}": "a" * 64 for index in range(8)},
    }


class AgentTeamsStabilityTests(unittest.TestCase):
    def test_five_complete_runs_produce_pass_and_quantiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_ids = [f"run-{index}" for index in range(5)]
            for index, run_id in enumerate(run_ids):
                directory = root / run_id
                directory.mkdir()
                (directory / "run-result.json").write_text(
                    json.dumps(successful_result(run_id, 1000 + index * 100)),
                    encoding="utf-8",
                )
            report = MODULE.summarize(
                run_root=root,
                run_ids=run_ids,
                minimum_passes=5,
            )
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["passed_count"], 5)
            self.assertEqual(report["timing_ms"]["median_p50"], 1200)
            self.assertEqual(report["timing_ms"]["p90_nearest_rank"], 1400)

    def test_operator_intervention_fails_stability_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_id = "run-failed"
            directory = root / run_id
            directory.mkdir()
            payload = successful_result(run_id, 1000)
            payload["operator_actions_after_dispatch"] = 1
            (directory / "run-result.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            report = MODULE.summarize(
                run_root=root,
                run_ids=[run_id],
                minimum_passes=1,
            )
            self.assertEqual(report["status"], "FAIL")
            self.assertFalse(report["runs"][0]["checks"]["zero_operator_actions"])


if __name__ == "__main__":
    unittest.main()
