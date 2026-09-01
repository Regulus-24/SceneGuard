from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.pipeline import decide_pending_job, run_job  # noqa: E402
from sceneguard.profile import QualityProfile  # noqa: E402
from sceneguard.repair import RepairError, resize_embedded_textures  # noqa: E402
from sceneguard.workspace import sha256_file  # noqa: E402


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = QualityProfile.load(ROOT / "profiles" / "web-realtime-v0.2.json")
        cls.approval_profile = QualityProfile.load(ROOT / "profiles" / "web-realtime-v0.3-approval.json")
        cls.texture_profile = QualityProfile.load(
            ROOT / "profiles" / "web-realtime-v0.4-texture-approval.json"
        )

    def test_l2_approval_pending_reject_and_approve(self) -> None:
        source = ROOT / "samples" / "degenerate_triangle.glb"
        source_hash = sha256_file(source)
        with tempfile.TemporaryDirectory() as directory:
            pending = run_job(source, self.approval_profile, directory, job_id="approval-pending")
            rejected = run_job(
                source,
                self.approval_profile,
                directory,
                job_id="approval-rejected",
                approval_decision="REJECT",
                approval_actor="reviewer-a",
            )
            approved = run_job(
                source,
                self.approval_profile,
                directory,
                job_id="approval-approved",
                approval_decision="APPROVE",
                approval_actor="reviewer-b",
            )
            self.assertEqual(pending["gate_state"], "NEED_APPROVAL")
            self.assertEqual(rejected["gate_state"], "REJECTED")
            self.assertEqual(approved["gate_state"], "REPAIRED_PASS")
            for job_id in ("approval-pending", "approval-rejected", "approval-approved"):
                root = Path(directory) / job_id
                self.assertEqual(sha256_file(root / "original" / "asset.glb"), source_hash)
                self.assertTrue((root / "artifacts" / "approval_request.json").is_file())
            rejected_root = Path(directory) / "approval-rejected"
            self.assertEqual(sha256_file(rejected_root / "working" / "candidate.glb"), source_hash)
            record = json.loads((rejected_root / "artifacts" / "approval_record.json").read_text(encoding="utf-8"))
            plan = json.loads((rejected_root / "artifacts" / "patch_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(record["decision"], "REJECT")
            self.assertEqual(record["plan_id"], plan["plan_id"])
            self.assertEqual(record["asset_sha256"], plan["asset_sha256"])

    def test_pending_job_continues_with_the_same_patch_plan(self) -> None:
        source = ROOT / "samples" / "degenerate_triangle.glb"
        with tempfile.TemporaryDirectory() as directory:
            pending = run_job(source, self.approval_profile, directory, job_id="approval-resume")
            root = Path(directory) / "approval-resume" / "artifacts"
            plan_before = json.loads((root / "patch_plan.json").read_text(encoding="utf-8"))
            approved = decide_pending_job(
                directory,
                self.approval_profile,
                "approval-resume",
                "APPROVE",
                approval_actor="reviewer-resume",
            )
            plan_after = json.loads((root / "patch_plan.json").read_text(encoding="utf-8"))
            record = json.loads((root / "approval_record.json").read_text(encoding="utf-8"))
            self.assertEqual(pending["gate_state"], "NEED_APPROVAL")
            self.assertEqual(approved["gate_state"], "REPAIRED_PASS")
            self.assertEqual(plan_before["plan_id"], plan_after["plan_id"])
            self.assertEqual(record["plan_id"], plan_before["plan_id"])
            self.assertEqual(record["actor"], "reviewer-resume")

    def test_clean_asset_is_published_without_repair(self) -> None:
        source = ROOT / "samples" / "clean_triangle.glb"
        with tempfile.TemporaryDirectory() as directory:
            result = run_job(source, self.profile, directory, job_id="clean")
            self.assertEqual(result["gate_state"], "PASS")
            self.assertTrue(result["published"])
            self.assertEqual(sha256_file(source), result["release"]["published_sha256"])

    def test_degenerate_triangle_is_repaired_verified_and_published(self) -> None:
        source = ROOT / "samples" / "degenerate_triangle.glb"
        source_hash = sha256_file(source)
        with tempfile.TemporaryDirectory() as directory:
            result = run_job(source, self.profile, directory, job_id="repair")
            root = Path(directory) / "repair"
            self.assertEqual(result["gate_state"], "REPAIRED_PASS")
            self.assertTrue(result["published"])
            self.assertEqual(sha256_file(root / "original" / "asset.glb"), source_hash)
            self.assertNotEqual(sha256_file(root / "published" / "asset.glb"), source_hash)
            execution = json.loads((root / "artifacts" / "execution_report.json").read_text(encoding="utf-8"))
            self.assertEqual(execution["removed_triangle_count"], 1)
            metrics = json.loads((root / "artifacts" / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["gate_state"], "REPAIRED_PASS")
            self.assertTrue(metrics["repair_attempted"])
            self.assertTrue(metrics["published"])

    def test_fault_after_execution_triggers_atomic_rollback(self) -> None:
        source = ROOT / "samples" / "degenerate_triangle.glb"
        source_hash = sha256_file(source)
        with tempfile.TemporaryDirectory() as directory:
            for mode in ("tamper_before_execute", "tool_error_after_execute", "corrupt_after_execute"):
                with self.subTest(mode=mode):
                    job_id = "rollback-" + mode
                    result = run_job(
                        source,
                        self.profile,
                        directory,
                        job_id=job_id,
                        fault_injection=mode,
                    )
                    root = Path(directory) / job_id
                    self.assertEqual(result["gate_state"], "FAILED_ROLLBACK")
                    self.assertFalse(result["published"])
                    self.assertEqual(sha256_file(root / "working" / "candidate.glb"), source_hash)
                    self.assertFalse((root / "published" / "asset.glb").exists())
                    events = [
                        json.loads(line)["event"]
                        for line in (root / "artifacts" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
                    ]
                    self.assertIn("demo.fault_injected", events)
                    self.assertIn("rollback.completed", events)

    def test_mixed_primitive_preserves_valid_triangle(self) -> None:
        source = ROOT / "samples" / "mixed_valid_degenerate.glb"
        profile = QualityProfile(
            profile_id=self.profile.profile_id,
            version="0.2-mixed-test",
            description="test-only profile allowing two input triangles",
            rules={**self.profile.rules, "max_triangles": 2},
            repair_policy=self.profile.repair_policy,
        )
        with tempfile.TemporaryDirectory() as directory:
            result = run_job(source, profile, directory, job_id="mixed")
            root = Path(directory) / "mixed"
            self.assertEqual(result["gate_state"], "REPAIRED_PASS")
            execution = json.loads((root / "artifacts" / "execution_report.json").read_text(encoding="utf-8"))
            self.assertEqual(execution["removed_triangle_count"], 1)
            regression = json.loads((root / "artifacts" / "regression_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(regression["measurements"]["triangle_count"], 1)

    def test_unsupported_error_is_rejected_without_mutation(self) -> None:
        source = ROOT / "samples" / "external_buffer.glb"
        source_hash = sha256_file(source)
        with tempfile.TemporaryDirectory() as directory:
            result = run_job(source, self.profile, directory, job_id="manual")
            root = Path(directory) / "manual"
            self.assertEqual(result["gate_state"], "REJECTED")
            self.assertFalse(result["published"])
            self.assertEqual(sha256_file(root / "working" / "candidate.glb"), source_hash)

    def test_texture_resize_requires_approval_then_passes_regression(self) -> None:
        source = ROOT / "samples" / "oversized_texture.glb"
        source_hash = sha256_file(source)
        with tempfile.TemporaryDirectory() as directory:
            pending = run_job(source, self.texture_profile, directory, job_id="texture-pending")
            self.assertEqual(pending["gate_state"], "NEED_APPROVAL")
            approved = run_job(
                source,
                self.texture_profile,
                directory,
                job_id="texture-approved",
                approval_decision="APPROVE",
                approval_actor="visual-reviewer",
            )
            root = Path(directory) / "texture-approved"
            self.assertEqual(approved["gate_state"], "REPAIRED_PASS")
            self.assertTrue(approved["published"])
            self.assertEqual(sha256_file(root / "original" / "asset.glb"), source_hash)
            execution = json.loads((root / "artifacts" / "execution_report.json").read_text(encoding="utf-8"))
            self.assertEqual(execution["operation"], "resize_embedded_textures")
            self.assertEqual(execution["resized_image_count"], 1)
            self.assertEqual(execution["changed_images"][0]["old_width"], 2048)
            self.assertEqual(execution["changed_images"][0]["new_width"], 1024)
            regression = json.loads((root / "artifacts" / "regression_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(regression["measurements"]["max_texture_dimension"], 1024)
            self.assertEqual(regression["measurements"]["triangle_count"], 1)

    def test_texture_resize_rejects_hash_mismatch(self) -> None:
        source = ROOT / "samples" / "oversized_texture.glb"
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.glb"
            candidate.write_bytes(source.read_bytes())
            with self.assertRaises(RepairError):
                resize_embedded_textures(candidate, expected_sha256="0" * 64, max_dimension=1024)


if __name__ == "__main__":
    unittest.main()
