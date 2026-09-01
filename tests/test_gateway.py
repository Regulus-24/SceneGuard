from __future__ import annotations

import sys
import hashlib
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.gateway import GatewayError, GatewayService  # noqa: E402


class GatewayServiceTests(unittest.TestCase):
    def service(self, jobs_root: str | Path) -> GatewayService:
        return GatewayService(ROOT / "samples", ROOT / "profiles", jobs_root)

    def test_create_job_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            with self.assertRaisesRegex(ValueError, "job id"):
                self.service(jobs_root).create_job(
                    {
                        "asset": "clean_triangle.glb",
                        "profile": "web-realtime-v0.1.json",
                        "job_id": "../escape",
                    }
                )
            self.assertFalse((Path(jobs_root).parent / "escape").exists())

    def test_audit_contract(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            result = self.service(jobs_root).audit(
                {"asset": "clean_triangle.glb", "profile": "web-realtime-v0.1.json", "job_id": "gateway-test"}
            )
            self.assertEqual(result["summary"]["gate_state"], "PASS")
            self.assertEqual(result["job_id"], "gateway-test")

    def test_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            with self.assertRaises(GatewayError) as context:
                self.service(jobs_root).audit(
                    {"asset": "../profiles/web-realtime-v0.1.json", "profile": "web-realtime-v0.1.json"}
                )
            self.assertEqual(context.exception.code, "PATH_OUT_OF_SCOPE")

    def test_create_job_contract(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            result = self.service(jobs_root).create_job(
                {
                    "asset": "over_triangle_budget.glb",
                    "profile": "web-realtime-v0.1.json",
                    "job_id": "gateway-job",
                }
            )
            self.assertEqual(result["job_id"], "gateway-job")
            self.assertEqual(result["gate_state"], "REJECTED")

    def test_pipeline_contract_repairs_and_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            result = self.service(jobs_root).run_pipeline(
                {
                    "asset": "degenerate_triangle.glb",
                    "profile": "web-realtime-v0.2.json",
                    "job_id": "gateway-repair",
                }
            )
            self.assertEqual(result["gate_state"], "REPAIRED_PASS")
            self.assertTrue(result["published"])

    def test_staged_agent_chain_enforces_real_role_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = self.service(jobs_root)
            created = service.create_job(
                {
                    "asset": "degenerate_triangle.glb",
                    "profile": "web-realtime-v0.2.json",
                    "job_id": "agent-chain",
                }
            )
            self.assertEqual(created["gate_state"], "REJECTED")
            artifacts = Path(jobs_root) / "agent-chain" / "artifacts"

            with self.assertRaises(GatewayError) as bypass:
                service.execute_repair(
                    {
                        "job_id": "agent-chain",
                        "profile": "web-realtime-v0.2.json",
                        "plan_id": "plan-000000000000",
                    }
                )
            self.assertEqual(bypass.exception.code, "STAGE_PRECONDITION_FAILED")

            planned = service.plan_repair(
                {"job_id": "agent-chain", "profile": "web-realtime-v0.2.json"}
            )
            plan_id = planned["patch_plan"]["plan_id"]
            self.assertEqual(planned["patch_plan"]["state"], "READY")
            self.assertFalse((artifacts / "execution_report.json").exists())

            executed = service.execute_repair(
                {"job_id": "agent-chain", "profile": "web-realtime-v0.2.json", "plan_id": plan_id}
            )
            self.assertEqual(executed["execution"]["state"], "SUCCEEDED")
            self.assertFalse((artifacts / "regression_report.json").exists())
            self.assertFalse((artifacts / "gate_decision.json").exists())
            self.assertFalse((Path(jobs_root) / "agent-chain" / "published" / "asset.glb").exists())

            verified = service.verify_regression(
                {"job_id": "agent-chain", "profile": "web-realtime-v0.2.json", "plan_id": plan_id}
            )
            self.assertEqual(verified["decision"]["gate_state"], "REPAIRED_PASS")
            self.assertTrue(verified["decision"]["published"])
            trace = (artifacts / "trace.jsonl").read_text(encoding="utf-8")
            self.assertIn('"actor_role": "repair-planner"', trace)
            self.assertIn('"actor_role": "repair-executor"', trace)
            self.assertIn('"actor_role": "regression-verifier"', trace)

    def test_staged_calls_are_idempotent_and_plan_bound(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = self.service(jobs_root)
            service.create_job(
                {"asset": "clean_triangle.glb", "profile": "web-realtime-v0.2.json", "job_id": "stage-replay"}
            )
            first_plan = service.plan_repair(
                {"job_id": "stage-replay", "profile": "web-realtime-v0.2.json"}
            )
            replay_plan = service.plan_repair(
                {"job_id": "stage-replay", "profile": "web-realtime-v0.2.json"}
            )
            self.assertTrue(replay_plan["replayed"])
            self.assertEqual(first_plan["patch_plan"]["plan_id"], replay_plan["patch_plan"]["plan_id"])
            plan_id = first_plan["patch_plan"]["plan_id"]
            first_execute = service.execute_repair(
                {"job_id": "stage-replay", "profile": "web-realtime-v0.2.json", "plan_id": plan_id}
            )
            replay_execute = service.execute_repair(
                {"job_id": "stage-replay", "profile": "web-realtime-v0.2.json", "plan_id": plan_id}
            )
            self.assertEqual(first_execute["execution"]["state"], "SKIPPED")
            self.assertTrue(replay_execute["replayed"])

    def test_uploaded_glb_runs_pipeline_and_stays_in_upload_store(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = self.service(jobs_root)
            data = (ROOT / "samples" / "degenerate_triangle.glb").read_bytes()
            upload = service.upload_asset("用户模型.glb", data)
            self.assertTrue(upload["asset_ref"].startswith("upload:upload-"))
            self.assertEqual(upload["sha256"], hashlib.sha256(data).hexdigest())
            self.assertTrue((Path(jobs_root) / ".uploads" / f"{upload['upload_id']}.glb").is_file())

            result = service.run_pipeline(
                {
                    "asset": upload["asset_ref"],
                    "profile": "web-realtime-v0.2.json",
                    "job_id": "uploaded-repair",
                }
            )
            self.assertEqual(result["gate_state"], "REPAIRED_PASS")
            original, _, _ = service.job_asset_content("uploaded-repair", "original")
            published, _, _ = service.job_asset_content("uploaded-repair", "published")
            self.assertEqual(original, data)
            self.assertNotEqual(published, data)

    def test_upload_rejects_invalid_format_and_unsafe_name(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = self.service(jobs_root)
            with self.assertRaises(GatewayError) as unsafe:
                service.upload_asset("../escape.glb", b"glTF")
            self.assertEqual(unsafe.exception.code, "INVALID_FILENAME")
            with self.assertRaises(GatewayError) as invalid:
                service.upload_asset("fake.glb", b"not-a-glb")
            self.assertEqual(invalid.exception.code, "INVALID_GLB")

    def test_gateway_rejects_type_coercion_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = self.service(jobs_root)
            with self.assertRaises(GatewayError) as coercion:
                service.run_pipeline(
                    {
                        "asset": "clean_triangle.glb",
                        "profile": "web-realtime-v0.2.json",
                        "auto_repair": "false",
                    }
                )
            self.assertEqual(coercion.exception.code, "INVALID_REQUEST")
            with self.assertRaises(GatewayError) as unknown:
                service.audit(
                    {
                        "asset": "clean_triangle.glb",
                        "profile": "web-realtime-v0.1.json",
                        "silently_ignored_before": True,
                    }
                )
            self.assertEqual(unknown.exception.code, "INVALID_REQUEST")

    def test_pipeline_idempotency_replays_and_rejects_key_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = self.service(jobs_root)
            payload = {
                "asset": "clean_triangle.glb",
                "profile": "web-realtime-v0.2.json",
                "job_id": "idempotent-job",
            }
            first = service.run_pipeline_request(
                payload,
                request_id="request-first",
                idempotency_key="stable-operation-1",
            )
            replay = service.run_pipeline_request(
                payload,
                request_id="request-retry",
                idempotency_key="stable-operation-1",
            )
            self.assertFalse(first["meta"]["replayed"])
            self.assertTrue(replay["meta"]["replayed"])
            self.assertEqual(first["result"], replay["result"])
            traces = (Path(jobs_root) / "idempotent-job" / "artifacts" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertEqual(traces.count("gateway.request.accepted"), 1)
            changed = {**payload, "asset": "degenerate_triangle.glb"}
            with self.assertRaises(GatewayError) as context:
                service.run_pipeline_request(
                    changed,
                    request_id="request-conflict",
                    idempotency_key="stable-operation-1",
                )
            self.assertEqual(context.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_idempotent_failure_is_recorded_instead_of_stuck_pending(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = self.service(jobs_root)
            payload = {
                "asset": "missing.glb",
                "profile": "web-realtime-v0.2.json",
                "job_id": "never-created",
            }
            with self.assertRaises(GatewayError):
                service.run_pipeline_request(payload, request_id="failure-one", idempotency_key="failure-key")
            with self.assertRaises(GatewayError) as replay:
                service.run_pipeline_request(payload, request_id="failure-two", idempotency_key="failure-key")
            self.assertNotEqual(replay.exception.code, "IDEMPOTENCY_IN_PROGRESS")
            receipts = list((Path(jobs_root) / ".idempotency").glob("*.json"))
            self.assertEqual(len(receipts), 1)
            self.assertIn('"state": "FAILED"', receipts[0].read_text(encoding="utf-8"))

    def test_pending_receipt_recovers_completed_gate_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = self.service(jobs_root)
            payload = {
                "asset": "clean_triangle.glb",
                "profile": "web-realtime-v0.2.json",
                "job_id": "recovered-job",
            }
            completed = service.run_pipeline(payload)
            key = "crash-recovery-key"
            key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
            receipt_dir = Path(jobs_root) / ".idempotency"
            receipt_dir.mkdir()
            (receipt_dir / f"{key_hash}.json").write_text(
                json.dumps(
                    {
                        "schema_version": "0.1",
                        "state": "PENDING",
                        "request_id": "request-before-restart",
                        "input_sha256": service._canonical_sha256(payload),
                        "job_id": "recovered-job",
                    }
                ),
                encoding="utf-8",
            )
            restarted = self.service(jobs_root)
            recovered = restarted.run_pipeline_request(
                payload,
                request_id="request-after-restart",
                idempotency_key=key,
            )
            self.assertTrue(recovered["meta"]["replayed"])
            self.assertEqual(recovered["meta"]["idempotency"], "RECOVERED_REPLAY")
            self.assertEqual(recovered["result"], completed)

    def test_pipeline_contract_records_l2_approval(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            result = self.service(jobs_root).run_pipeline(
                {
                    "asset": "degenerate_triangle.glb",
                    "profile": "web-realtime-v0.3-approval.json",
                    "job_id": "gateway-approval",
                    "approval_decision": "APPROVE",
                    "approval_actor": "http-reviewer",
                }
            )
            self.assertEqual(result["gate_state"], "REPAIRED_PASS")
            self.assertEqual(result["artifacts"]["approval_record"], "artifacts/approval_record.json")

    def test_artifact_listing_read_and_path_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = self.service(jobs_root)
            service.run_pipeline(
                {
                    "asset": "clean_triangle.glb",
                    "profile": "web-realtime-v0.2.json",
                    "job_id": "artifact-job",
                }
            )
            listing = service.list_artifacts("artifact-job")
            names = {item["name"] for item in listing["artifacts"]}
            self.assertIn("gate_decision.json", names)
            artifact = service.read_artifact("artifact-job", "trace.jsonl")
            self.assertEqual(artifact["content"][0]["event"], "job.created")
            self.assertEqual(len(artifact["sha256"]), 64)
            with self.assertRaises(GatewayError):
                service.read_artifact("artifact-job", "../job_manifest.json")
            with self.assertRaises(GatewayError):
                service.list_artifacts("../escape")


if __name__ == "__main__":
    unittest.main()
