from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SemifinalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_registry = json.loads(
            (ROOT / "skills" / "registry.v0.2.json").read_text(encoding="utf-8")
        )
        cls.contract_registry = json.loads(
            (ROOT / "schemas" / "registry.v0.1.json").read_text(encoding="utf-8")
        )
        cls.scenario_suite = json.loads(
            (ROOT / "at" / "semifinal-scenario-suite.v0.2.json").read_text(encoding="utf-8")
        )

    def test_skill_governance_matches_all_contract_skills(self) -> None:
        governed = {item["id"] for item in self.skill_registry["skills"]}
        contracted = {item["id"] for item in self.contract_registry["skills"]}
        self.assertEqual(governed, contracted)
        self.assertEqual(governed, set(self.scenario_suite["required_skills"]))
        for item in self.skill_registry["skills"]:
            self.assertIn(item["release_state"], self.skill_registry["release_policy"]["states"])
            self.assertTrue(item["owner_agent"])
            self.assertTrue(item["evaluation_gate"])

    def test_partial_mesh_validate_is_not_overclaimed(self) -> None:
        mesh = next(item for item in self.skill_registry["skills"] if item["id"] == "mesh-validate")
        self.assertEqual(mesh["release_state"], "candidate")
        self.assertFalse(mesh["core_capability"])
        self.assertGreaterEqual(len(mesh["missing_capabilities"]), 3)
        self.assertIn("non-core", mesh["claim_boundary"])

    def test_suite_covers_seven_skills_and_five_agent_repair_chain(self) -> None:
        covered = {
            skill
            for scenario in self.scenario_suite["scenarios"]
            for skill in scenario["skills"]
        }
        self.assertEqual(covered, set(self.scenario_suite["required_skills"]))
        l1 = next(
            item
            for item in self.scenario_suite["scenarios"]
            if item["id"] == "S2_L1_AUTONOMOUS_REPAIR"
        )
        self.assertEqual(set(l1["agents_called"]), set(self.scenario_suite["required_agents"]))
        self.assertEqual(l1["expected_gate"], "REPAIRED_PASS")
        self.assertNotIn("texture-safe-resize", l1["skills"])

    def test_evidence_and_license_gates_are_frozen(self) -> None:
        evidence = set(self.scenario_suite["evidence_contract"]["per_run"])
        for field in {
            "run_id",
            "project_id",
            "matrix_event_ids",
            "job_id",
            "input_asset_sha256",
            "skill_ids_and_versions",
            "terminal_gate",
        }:
            self.assertIn(field, evidence)

        facts = json.loads((ROOT / "release-facts.v0.1.json").read_text(encoding="utf-8"))
        decision = json.loads(
            (ROOT / "evidence" / "team" / "release-decisions.json").read_text(encoding="utf-8")
        )
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(facts["release"]["license_spdx"], "Apache-2.0")
        self.assertEqual(decision["license_spdx"], "Apache-2.0")
        self.assertEqual(project["license"]["file"], "LICENSE")
        self.assertTrue((ROOT / "NOTICE").is_file())
        self.assertIn("Apache License", (ROOT / "LICENSE").read_text(encoding="utf-8")[:100])

    def test_agent_identity_and_business_value_contracts_are_explicit(self) -> None:
        identities = json.loads((ROOT / "at" / "agent-identities.v0.2.json").read_text(encoding="utf-8"))
        self.assertEqual(identities["identity_count"], 5)
        self.assertEqual(len(identities["identities"]), 5)
        self.assertEqual(
            {item["agent_id"] for item in identities["identities"]},
            {
                "scene-guard-leader",
                "asset-auditor",
                "repair-planner",
                "repair-executor",
                "regression-verifier",
            },
        )
        skill_ids = {skill for item in identities["identities"] for skill in item["allowed_skills"]}
        self.assertEqual(len(skill_ids), 7)
        value = json.loads(
            (ROOT / "benchmark" / "business-value.v0.1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(value["status"], "MEASUREMENT_PROTOCOL_READY_BASELINE_PENDING")
        self.assertEqual(value["manual_baseline_protocol"]["minimum_participants"], 3)
        self.assertIn("no_baseline", value["reporting_rules"])

    def test_validated_five_agent_release_evidence_is_frozen(self) -> None:
        facts = json.loads((ROOT / "release-facts.v0.1.json").read_text(encoding="utf-8"))
        agentteams = facts["agentteams"]
        envelope = json.loads((ROOT / agentteams["validated_supervisor_evidence"]).read_text(encoding="utf-8"))
        stability = json.loads((ROOT / agentteams["validated_supervisor_stability_report"]).read_text(encoding="utf-8"))
        self.assertEqual(envelope["status"], "PASS")
        self.assertEqual(envelope["team"], "sceneguard-auto-v1")
        self.assertEqual(envelope["agent_count"], 5)
        self.assertEqual(envelope["worker_count"], 4)
        self.assertEqual(envelope["operator_actions_after_dispatch"], 0)
        self.assertEqual(envelope["gate_state"], "REPAIRED_PASS")
        self.assertEqual(envelope["leader_model"], "qwen3.5:9b")
        self.assertEqual(envelope["worker_model"], "qwen3.5:4b")
        self.assertEqual(len(envelope["skill_ids"]), 6)
        self.assertEqual(len(envelope["trace_refs"]), 12)
        self.assertTrue(all((ROOT / item).is_file() for item in envelope["trace_refs"]))
        self.assertEqual(stability["status"], "PASS")
        self.assertEqual(stability["sample_count"], 5)
        self.assertEqual(stability["passed_count"], 5)
        self.assertEqual(stability["success_rate"], 1.0)
        self.assertTrue(stability["consecutive_selected_runs_passed"])


if __name__ == "__main__":
    unittest.main()
