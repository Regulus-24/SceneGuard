from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.benchmark import _validate_release_evidence, run_acceptance_benchmark  # noqa: E402


class BenchmarkTests(unittest.TestCase):
    def test_placeholder_runtime_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
            result = _validate_release_evidence(path, "evidence/agentteams/runtime.json")
            self.assertFalse(result["valid"])
            self.assertIn("worker_count", result["reason"])

    def test_official_skill_evidence_rejects_non_aliyun_source(self) -> None:
        payload = {
            "status": "PASS",
            "skill_name": "lookalike",
            "skill_version": "1.0",
            "official_source_url": "https://example.com/fake-skill",
            "official_quickstart_url": "https://help.aliyun.com/zh/skillsportal/quickly-use-alibaba-cloud-skills",
            "observed_at": "2026-08-06T00:00:00Z",
            "auth_mode": "RAM",
            "necessity_in_sceneguard": "read-only discovery",
            "successful_call": {
                "operation": "search-resources",
                "sanitized_result_summary": "one redacted result",
                "trace_ref": "evidence/trace/success.json",
            },
            "failure_tested": True,
            "failure_case": {
                "mode": "least privilege denial",
                "observed_error_code": "Forbidden",
                "fallback": "local evidence bundle",
                "trace_ref": "evidence/trace/failure.json",
            },
            "replacement_strategy": "adapter",
            "trace_refs": ["evidence/trace/success.json", "evidence/trace/failure.json"],
            "secret_scan_passed": True,
            "confirmed_by": ["reviewer"],
        }
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "evidence" / "trace"
            trace.mkdir(parents=True)
            (trace / "success.json").write_text("{}", encoding="utf-8")
            (trace / "failure.json").write_text("{}", encoding="utf-8")
            path = Path(directory) / "integration.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = _validate_release_evidence(path, "evidence/official-skill/integration.json", Path(directory))
            self.assertFalse(result["valid"])
            self.assertIn("official_source_url", result["reason"])

    def test_official_skill_evidence_accepts_required_real_contract(self) -> None:
        payload = {
            "status": "PASS",
            "skill_name": "alibabacloud-resourcecenter-search",
            "skill_version": "1.0",
            "official_source_url": "https://skills.aliyun.com/skills/alibabacloud-resourcecenter-search",
            "official_quickstart_url": "https://help.aliyun.com/zh/skillsportal/quickly-use-alibaba-cloud-skills",
            "observed_at": "2026-08-06T00:00:00Z",
            "auth_mode": "RAM role; credentials redacted",
            "necessity_in_sceneguard": "read-only discovery",
            "successful_call": {
                "operation": "search-resources",
                "sanitized_result_summary": "one redacted result",
                "trace_ref": "evidence/trace/success.json",
            },
            "failure_tested": True,
            "failure_case": {
                "mode": "least privilege denial",
                "observed_error_code": "Forbidden",
                "fallback": "local evidence bundle",
                "trace_ref": "evidence/trace/failure.json",
            },
            "replacement_strategy": "read-only API adapter",
            "trace_refs": ["evidence/trace/success.json", "evidence/trace/failure.json"],
            "secret_scan_passed": True,
            "confirmed_by": ["reviewer"],
        }
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "evidence" / "trace"
            trace.mkdir(parents=True)
            (trace / "success.json").write_text("{}", encoding="utf-8")
            (trace / "failure.json").write_text("{}", encoding="utf-8")
            path = Path(directory) / "integration.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = _validate_release_evidence(path, "evidence/official-skill/integration.json", Path(directory))
            self.assertTrue(result["valid"])
            (trace / "success.json").write_text(
                '{"DASHSCOPE_API_KEY":"sk-example-secret-value-123456"}', encoding="utf-8"
            )
            leaked = _validate_release_evidence(path, "evidence/official-skill/integration.json", Path(directory))
            self.assertFalse(leaked["valid"])
            self.assertIn("secret_scan_verified", leaked["reason"])
            self.assertEqual(leaked["secret_scan"]["findings"][0]["path"], "evidence/trace/success.json")

    def test_external_evidence_rejects_phantom_and_escaping_trace_refs(self) -> None:
        payload = {
            "status": "PASS",
            "skill_name": "alibabacloud-resourcecenter-search",
            "skill_version": "1.0",
            "official_source_url": "https://skills.aliyun.com/skills/alibabacloud-resourcecenter-search",
            "official_quickstart_url": "https://help.aliyun.com/zh/skillsportal/quickly-use-alibaba-cloud-skills",
            "observed_at": "2026-08-06T00:00:00Z",
            "auth_mode": "RAM",
            "necessity_in_sceneguard": "read-only discovery",
            "successful_call": {
                "operation": "search-resources",
                "sanitized_result_summary": "one redacted result",
                "trace_ref": "evidence/missing.json",
            },
            "failure_tested": True,
            "failure_case": {
                "mode": "least privilege denial",
                "observed_error_code": "Forbidden",
                "fallback": "local evidence bundle",
                "trace_ref": "../outside.log",
            },
            "replacement_strategy": "adapter",
            "trace_refs": ["evidence/missing.json", "../outside.log"],
            "secret_scan_passed": True,
            "confirmed_by": ["reviewer"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "integration.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = _validate_release_evidence(path, "evidence/official-skill/integration.json", Path(directory))
            self.assertFalse(result["valid"])
            self.assertEqual(result["trace_ref_validation"]["missing"], ["evidence/missing.json"])
            self.assertEqual(result["trace_ref_validation"]["invalid"], ["../outside.log"])

    def test_agentteams_evidence_accepts_complete_runtime_contract(self) -> None:
        payload = {
            "status": "PASS",
            "framework": "AgentTeams/HiClaw",
            "framework_version": "1.0",
            "host": {"os": "Linux", "cpu": "x86_64", "memory_gb": 8, "docker_version": "27.0"},
            "worker_runtime": "Docker containers",
            "model_provider": "redacted-provider",
            "model_name": "redacted-model",
            "worker_count": 4,
            "workers": ["auditor", "planner", "executor", "verifier"],
            "team_leader": "sceneguard-leader",
            "observed_at": "2026-08-06T00:00:00Z",
            "gateway": {"reachable_url_redacted": "http://gateway:18091", "health_http_status": 200},
            "cases": {
                "clean": {
                    "job_id": "real-clean",
                    "gate_state": "PASS",
                    "trace_ref": "evidence/agentteams/trace-clean.jsonl",
                },
                "repair": {
                    "job_id": "real-repair",
                    "gate_state": "REPAIRED_PASS",
                    "trace_ref": "evidence/agentteams/trace-repair.jsonl",
                },
            },
            "trace_refs": ["evidence/agentteams/trace-clean.jsonl", "evidence/agentteams/trace-repair.jsonl"],
            "secret_scan_passed": True,
            "confirmed_by": ["team-reviewer"],
        }
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence" / "agentteams"
            evidence.mkdir(parents=True)
            (evidence / "trace-clean.jsonl").write_text('{"event":"complete"}\n', encoding="utf-8")
            (evidence / "trace-repair.jsonl").write_text('{"event":"complete"}\n', encoding="utf-8")
            path = evidence / "runtime.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = _validate_release_evidence(path, "evidence/agentteams/runtime.json", Path(directory))
            self.assertTrue(result["valid"])
            (evidence / "trace-clean.jsonl").write_text(
                '{"artifact":"C:\\\\Users\\\\real-user\\\\secret.log"}\n', encoding="utf-8"
            )
            leaked = _validate_release_evidence(path, "evidence/agentteams/runtime.json", Path(directory))
            self.assertFalse(leaked["valid"])
            self.assertIn("secret_scan_verified", leaked["reason"])
            self.assertEqual(leaked["secret_scan"]["findings"][0]["kind"], "windows_user_path")

    def test_team_release_decision_requires_three_confirmations_and_license(self) -> None:
        payload = {
            "status": "PASS",
            "project_name": "SceneGuard",
            "project_name_confirmed": True,
            "license_spdx": "Apache-2.0",
            "license_file": "LICENSE",
            "members_confirmed": ["member-a", "member-b", "member-c"],
            "roles_confirmed": True,
            "public_bios_authorized": True,
            "public_asset_license_reviewed": True,
            "confirmed_at": "2026-08-10T00:00:00Z",
            "confirmed_by": ["member-a", "member-b", "member-c"],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence" / "team"
            evidence.mkdir(parents=True)
            path = evidence / "release-decisions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            without_license = _validate_release_evidence(path, "evidence/team/release-decisions.json", root)
            self.assertFalse(without_license["valid"])
            self.assertIn("license_file", without_license["reason"])
            (root / "LICENSE").write_text("Apache License 2.0\n", encoding="utf-8")
            payload["members_confirmed"] = None
            path.write_text(json.dumps(payload), encoding="utf-8")
            malformed = _validate_release_evidence(path, "evidence/team/release-decisions.json", root)
            self.assertFalse(malformed["valid"])
            payload["members_confirmed"] = ["member-a", "member-b", "member-c"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            complete = _validate_release_evidence(path, "evidence/team/release-decisions.json", root)
            self.assertTrue(complete["valid"])

    def test_pass_status_cannot_bypass_template_placeholders(self) -> None:
        payload = json.loads(
            (ROOT / "evidence" / "official-skill" / "integration.template.json").read_text(encoding="utf-8")
        )
        payload["status"] = "PASS"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "integration.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = _validate_release_evidence(path, "evidence/official-skill/integration.json", root)
            self.assertFalse(result["valid"])
            self.assertIn("no_placeholders", result["reason"])
            self.assertIn("$.skill_version", result["placeholder_paths"])

    def test_acceptance_benchmark_without_recursive_test_run(self) -> None:
        result = run_acceptance_benchmark(ROOT, include_test_suite=False)
        check_ids = {item["check_id"] for item in result["core"]["checks"]}
        self.assertIn("pipeline.five_gate_states", check_ids)
        self.assertIn("contracts.material_sync", check_ids)
        self.assertIn("submission.manifest", check_ids)
        self.assertIn("gateway.request_contract", check_ids)
        self.assertIn("contracts.api_docs", check_ids)
        self.assertIn("contracts.schemas", check_ids)
        self.assertIn("requirements.registry", check_ids)
        pipeline = next(item for item in result["core"]["checks"] if item["check_id"] == "pipeline.five_gate_states")
        self.assertGreaterEqual(pipeline["evidence"]["metrics"]["denominators"]["repair_attempts"], 5)
        self.assertTrue(pipeline["evidence"]["repair_benchmark"]["threshold_met"])
        self.assertGreaterEqual(pipeline["evidence"]["metrics"]["denominators"]["rollback_attempts"], 3)
        self.assertTrue(pipeline["evidence"]["rollback_benchmark"]["threshold_met"])
        self.assertEqual(result["benchmark_id"], "sceneguard-release-v0.1")
        self.assertTrue(result["requirements"]["core"]["passed"])
        self.assertTrue(result["requirements"]["release"]["passed"])
        self.assertEqual(result["requirements"]["release"]["failed_ids"], [])
        self.assertEqual(result["release"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
