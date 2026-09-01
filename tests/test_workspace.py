from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.profile import QualityProfile  # noqa: E402
from sceneguard.workspace import (  # noqa: E402
    create_checkpoint,
    create_job_workspace,
    rollback_to_checkpoint,
    sha256_file,
)


class WorkspaceTests(unittest.TestCase):
    def test_job_workspace_preserves_original_hash_and_trace(self) -> None:
        profile = QualityProfile.load(ROOT / "profiles" / "web-realtime-v0.1.json")
        source = ROOT / "samples" / "clean_triangle.glb"
        source_hash = sha256_file(source)
        with tempfile.TemporaryDirectory() as directory:
            workspace, report = create_job_workspace(
                source,
                jobs_root=directory,
                profile=profile,
                job_id="job-test",
            )
            self.assertEqual(sha256_file(workspace.original), source_hash)
            self.assertEqual(sha256_file(workspace.working), source_hash)
            self.assertEqual(report["summary"]["gate_state"], "PASS")
            manifest = json.loads((workspace.root / "job_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["original"]["read_only"])
            trace = [json.loads(line) for line in workspace.trace.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([item["event"] for item in trace], ["job.created", "audit.completed"])
            self.assertEqual(len({item["trace_id"] for item in trace}), 1)
            self.assertEqual(manifest["trace_id"], trace[0]["trace_id"])

    def test_checkpoint_and_atomic_rollback_restore_hash(self) -> None:
        profile = QualityProfile.load(ROOT / "profiles" / "web-realtime-v0.1.json")
        source = ROOT / "samples" / "clean_triangle.glb"
        with tempfile.TemporaryDirectory() as directory:
            workspace, _ = create_job_workspace(source, directory, profile, job_id="job-rollback")
            original_hash = sha256_file(workspace.working)
            checkpoint = create_checkpoint(workspace, "pre-change", expected_working_hash=original_hash)
            with workspace.working.open("ab") as stream:
                stream.write(b"controlled-failure-injection")
            self.assertNotEqual(sha256_file(workspace.working), original_hash)
            result = rollback_to_checkpoint(
                workspace,
                "pre-change",
                expected_checkpoint_hash=checkpoint["sha256"],
            )
            self.assertTrue(result["success"])
            self.assertEqual(sha256_file(workspace.working), original_hash)
            events = [json.loads(line)["event"] for line in workspace.trace.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(events[-2:], ["checkpoint.created", "rollback.completed"])

    def test_checkpoint_label_rejects_path_escape(self) -> None:
        profile = QualityProfile.load(ROOT / "profiles" / "web-realtime-v0.1.json")
        source = ROOT / "samples" / "clean_triangle.glb"
        with tempfile.TemporaryDirectory() as directory:
            workspace, _ = create_job_workspace(source, directory, profile, job_id="job-label")
            with self.assertRaisesRegex(ValueError, "checkpoint label"):
                create_checkpoint(workspace, "../escape")

    def test_job_id_rejects_path_escape_before_writing(self) -> None:
        profile = QualityProfile.load(ROOT / "profiles" / "web-realtime-v0.1.json")
        source = ROOT / "samples" / "clean_triangle.glb"
        with tempfile.TemporaryDirectory() as directory:
            jobs_root = Path(directory) / "jobs"
            with self.assertRaisesRegex(ValueError, "job id"):
                create_job_workspace(source, jobs_root, profile, job_id="../escape")
            self.assertFalse((Path(directory) / "escape").exists())
            self.assertFalse(jobs_root.exists())


if __name__ == "__main__":
    unittest.main()
