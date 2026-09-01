from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.evaluation import run_golden_evaluation  # noqa: E402


class EvaluationTests(unittest.TestCase):
    def test_golden_evaluation_is_exact(self) -> None:
        result = run_golden_evaluation(
            ROOT / "evaluation" / "golden_findings.json",
            ROOT / "samples",
            ROOT / "profiles" / "web-realtime-v0.1.json",
        )
        self.assertEqual(result["dataset"]["sample_count"], 15)
        self.assertEqual(result["dataset"]["expected_error_rule_count"], 20)
        self.assertEqual(result["metrics"]["sample_gate_accuracy"], 1.0)
        self.assertEqual(result["metrics"]["expected_rule_recall"], 1.0)
        self.assertEqual(result["metrics"]["unexpected_error_rule_count"], 0)
        self.assertEqual(result["metrics"]["evidence_completeness"], 1.0)


if __name__ == "__main__":
    unittest.main()
