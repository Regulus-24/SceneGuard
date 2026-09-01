from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.audit import audit_asset  # noqa: E402
from sceneguard.models import GateState  # noqa: E402
from sceneguard.profile import QualityProfile  # noqa: E402
from sceneguard.regression import compare_audits  # noqa: E402


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = QualityProfile.load(ROOT / "profiles" / "web-realtime-v0.1.json")

    def audit(self, name: str):
        return audit_asset(ROOT / "samples" / name, self.profile)

    def test_unchanged_clean_asset_passes(self) -> None:
        clean = self.audit("clean_triangle.glb")
        report = compare_audits(clean, clean)
        self.assertEqual(report.gate_state, GateState.PASS)
        self.assertFalse(report.new_error_findings)

    def test_resolved_target_can_be_repaired_pass(self) -> None:
        original = self.audit("over_triangle_budget.glb")
        candidate = self.audit("clean_triangle.glb")
        report = compare_audits(
            original,
            candidate,
            target_rules=["profile.max_triangles"],
            repair_attempted=True,
        )
        self.assertEqual(report.gate_state, GateState.REPAIRED_PASS)
        self.assertEqual(report.resolved_target_rules, ("profile.max_triangles",))

    def test_new_error_requests_rollback(self) -> None:
        original = self.audit("clean_triangle.glb")
        candidate = self.audit("degenerate_triangle.glb")
        report = compare_audits(original, candidate, repair_attempted=True)
        self.assertEqual(report.gate_state, GateState.FAILED_ROLLBACK)
        self.assertTrue(report.new_error_findings)


if __name__ == "__main__":
    unittest.main()
