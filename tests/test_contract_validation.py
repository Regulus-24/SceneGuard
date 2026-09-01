from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.audit import audit_asset  # noqa: E402
from sceneguard.planner import build_patch_plan, validate_patch_plan  # noqa: E402
from sceneguard.profile import QualityProfile  # noqa: E402


class ContractValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_path = ROOT / "profiles" / "web-realtime-v0.2.json"
        self.profile = QualityProfile.load(self.profile_path)

    def _write_profile(self, payload: dict) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "profile.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_profile_rejects_wrong_rule_type(self) -> None:
        payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        payload["rules"]["max_triangles"] = True
        with self.assertRaisesRegex(ValueError, "max_triangles"):
            QualityProfile.load(self._write_profile(payload))

    def test_profile_rejects_overlapping_risk_policy(self) -> None:
        payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        payload["repair_policy"]["approval_required_risk_levels"].append("L1")
        with self.assertRaisesRegex(ValueError, "overlap"):
            QualityProfile.load(self._write_profile(payload))

    def test_profile_rejects_unclassified_whitelisted_operation(self) -> None:
        payload = json.loads(self.profile_path.read_text(encoding="utf-8"))
        payload["repair_policy"]["auto_execute_risk_levels"] = ["L0"]
        with self.assertRaisesRegex(ValueError, "unclassified"):
            QualityProfile.load(self._write_profile(payload))

    def test_patch_plan_rejects_tampered_hash_and_operation(self) -> None:
        report = audit_asset(ROOT / "samples" / "degenerate_triangle.glb", self.profile, job_id="contract")
        plan = build_patch_plan(report, self.profile)
        validate_patch_plan(plan, self.profile)
        with self.assertRaisesRegex(ValueError, "asset_sha256"):
            validate_patch_plan(replace(plan, asset_sha256="0" * 63), self.profile)
        bad_step = replace(plan.steps[0], operation="unreviewed_operation")
        with self.assertRaisesRegex(ValueError, "not whitelisted"):
            validate_patch_plan(replace(plan, steps=(bad_step,)), self.profile)

    def test_patch_plan_rejects_approval_policy_mismatch(self) -> None:
        report = audit_asset(ROOT / "samples" / "degenerate_triangle.glb", self.profile, job_id="contract")
        plan = build_patch_plan(report, self.profile)
        with self.assertRaisesRegex(ValueError, "approval flag"):
            validate_patch_plan(replace(plan, approval_required=True), self.profile)


if __name__ == "__main__":
    unittest.main()
