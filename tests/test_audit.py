from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.audit import audit_asset  # noqa: E402
from sceneguard.models import GateState  # noqa: E402
from sceneguard.profile import QualityProfile  # noqa: E402


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = QualityProfile.load(ROOT / "profiles" / "web-realtime-v0.1.json")

    def audit(self, name: str):
        return audit_asset(ROOT / "samples" / name, self.profile, job_id="test-job")

    def test_clean_triangle_passes(self) -> None:
        report = self.audit("clean_triangle.glb")
        self.assertEqual(report.gate_state, GateState.PASS)
        self.assertEqual(report.measurements["triangle_count"], 1)
        self.assertEqual(report.error_count, 0)

    def test_triangle_budget_rejects(self) -> None:
        report = self.audit("over_triangle_budget.glb")
        self.assertEqual(report.gate_state, GateState.REJECTED)
        self.assertIn("profile.max_triangles", {item.rule_id for item in report.findings})

    def test_broken_reference_rejects(self) -> None:
        report = self.audit("broken_reference.glb")
        self.assertEqual(report.gate_state, GateState.REJECTED)
        self.assertIn("package.reference_integrity", {item.rule_id for item in report.findings})

    def test_accessor_bounds_rejects(self) -> None:
        report = self.audit("accessor_out_of_bounds.glb")
        self.assertEqual(report.gate_state, GateState.REJECTED)
        self.assertIn("package.accessor_bounds", {item.rule_id for item in report.findings})

    def test_external_buffer_rejects(self) -> None:
        report = self.audit("external_buffer.glb")
        self.assertEqual(report.gate_state, GateState.REJECTED)
        self.assertIn("package.single_file", {item.rule_id for item in report.findings})

    def test_degenerate_triangle_rejects(self) -> None:
        report = self.audit("degenerate_triangle.glb")
        self.assertEqual(report.gate_state, GateState.REJECTED)
        self.assertEqual(report.measurements["degenerate_triangle_count"], 1)
        self.assertIn("mesh.degenerate_triangles", {item.rule_id for item in report.findings})


if __name__ == "__main__":
    unittest.main()
