from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.submission import (  # noqa: E402
    SubmissionManifestError,
    build_submission_archive,
    build_submission_manifest,
    verify_submission_manifest,
    verify_submission_archive,
    write_submission_manifest,
)


class SubmissionManifestTests(unittest.TestCase):
    def _project(self, directory: str) -> Path:
        root = Path(directory)
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "schemas").mkdir()
        (root / "submission" / "semifinal").mkdir(parents=True)
        (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (root / "src" / "sample.egg-info").mkdir()
        (root / "src" / "sample.egg-info" / "PKG-INFO").write_text("generated\n", encoding="utf-8")
        (root / "tests" / "test_main.py").write_text("# test\n", encoding="utf-8")
        (root / "schemas" / "contract.schema.json").write_text("{}\n", encoding="utf-8")
        (root / "README.md").write_text("# sample\n", encoding="utf-8")
        (root / "SEMIFINAL_SUBMISSION_CHECKLIST.zh-CN.md").write_text("# checklist\n", encoding="utf-8")
        (root / "submission" / "semifinal" / "defense.pdf").write_bytes(b"%PDF-test")
        (root / "jobs" / "delivery-repair" / "artifacts").mkdir(parents=True)
        (root / "jobs" / "delivery-repair" / "artifacts" / "audit_report.json").write_text(
            "{}\n", encoding="utf-8"
        )
        (root / "jobs" / "runtime.json").write_text("{}", encoding="utf-8")
        (root / "LICENSE").write_text("Apache License 2.0\n", encoding="utf-8")
        (root / "release-facts.v0.1.json").write_text("{}\n", encoding="utf-8")
        return root

    def test_build_and_verify_uses_relative_paths_and_excludes_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            payload = build_submission_manifest(root)
            paths = [item["path"] for item in payload["files"]]
            self.assertEqual(paths, sorted(paths))
            self.assertIn("src/main.py", paths)
            self.assertIn("schemas/contract.schema.json", paths)
            self.assertIn("LICENSE", paths)
            self.assertIn("release-facts.v0.1.json", paths)
            self.assertIn("SEMIFINAL_SUBMISSION_CHECKLIST.zh-CN.md", paths)
            self.assertIn("submission/semifinal/defense.pdf", paths)
            self.assertIn("jobs/delivery-repair/artifacts/audit_report.json", paths)
            self.assertNotIn("src/sample.egg-info/PKG-INFO", paths)
            self.assertNotIn("jobs/runtime.json", paths)
            self.assertTrue(all(not Path(path).is_absolute() for path in paths))
            output = root / "reports" / "submission-manifest.json"
            write_submission_manifest(payload, output)
            self.assertTrue(verify_submission_manifest(root, output)["passed"])

    def test_verify_detects_changed_and_unexpected_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            output = root / "reports" / "submission-manifest.json"
            write_submission_manifest(build_submission_manifest(root), output)
            (root / "src" / "main.py").write_text("print('changed')\n", encoding="utf-8")
            (root / "src" / "new.py").write_text("# new\n", encoding="utf-8")
            result = verify_submission_manifest(root, output)
            self.assertFalse(result["passed"])
            self.assertEqual(result["changed"], ["src/main.py"])
            self.assertEqual(result["unexpected"], ["src/new.py"])

    def test_sensitive_looking_deliverable_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            (root / "src" / "service-token.pem").write_text("not-a-real-secret", encoding="utf-8")
            with self.assertRaisesRegex(SubmissionManifestError, "sensitive-looking"):
                build_submission_manifest(root)

    def test_verifier_rejects_escaping_manifest_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            output = root / "manifest.json"
            output.write_text(
                json.dumps(
                    {
                        "schema_version": "0.1",
                        "manifest_type": "sceneguard-submission",
                        "files": [{"path": "../escape", "bytes": 0, "sha256": ""}],
                    }
                ),
                encoding="utf-8",
            )
            result = verify_submission_manifest(root, output)
            self.assertFalse(result["passed"])
            self.assertTrue(any("escapes" in error for error in result["errors"]))

    def test_archive_is_reproducible_scoped_and_self_verifying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            manifest = root / "reports" / "submission-manifest.json"
            write_submission_manifest(build_submission_manifest(root), manifest)
            first = root / "reports" / "first.zip"
            second = root / "reports" / "second.zip"
            one = build_submission_archive(root, manifest, first)
            two = build_submission_archive(root, manifest, second)
            self.assertTrue(one["passed"])
            self.assertEqual(one["sha256"], two["sha256"])
            self.assertTrue(verify_submission_archive(first)["passed"])

    def test_archive_rejects_stale_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            manifest = root / "reports" / "submission-manifest.json"
            write_submission_manifest(build_submission_manifest(root), manifest)
            (root / "src" / "main.py").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(SubmissionManifestError, "must verify"):
                build_submission_archive(root, manifest, root / "reports" / "stale.zip")

    def test_archive_cannot_overwrite_manifest_or_enter_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory)
            manifest = root / "reports" / "submission-manifest.json"
            write_submission_manifest(build_submission_manifest(root), manifest)
            with self.assertRaisesRegex(SubmissionManifestError, "must not overwrite"):
                build_submission_archive(root, manifest, manifest)
            with self.assertRaisesRegex(SubmissionManifestError, "under reports"):
                build_submission_archive(root, manifest, root / "src" / "submission.zip")


if __name__ == "__main__":
    unittest.main()
