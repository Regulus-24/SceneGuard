from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SemifinalDemoTests(unittest.TestCase):
    def test_launcher_exposes_quick_and_agentteams_modes(self) -> None:
        script = (ROOT / "scripts" / "start_semifinal_demo.ps1").read_text(encoding="utf-8-sig")
        for marker in (
            'ValidateSet("Quick", "AgentTeams")',
            "scripts/run_demo_smoke.py",
            "scripts/run_agentteams_native_supervisor.py",
            "AgentTeams Demo completed",
            ".gateway-token",
        ):
            self.assertIn(marker, script)

    def test_demo_runbook_names_real_evidence(self) -> None:
        runbook = (ROOT / "submission" / "semifinal" / "DEMO_RUNBOOK.zh-CN.md").read_text(encoding="utf-8")
        self.assertIn("semifinal-live-20260902-001", runbook)
        self.assertIn("REPAIRED_PASS", runbook)
        self.assertIn("jobs/.agentteams-native/<run-id>/run-result.json", runbook)
        self.assertIn('评委下载代码包后本地运行 Demo', runbook)

    def test_verified_demo_evidence_is_packaged(self) -> None:
        evidence = ROOT / "evidence" / "agentteams" / "semifinal-wrapper-20260902-001"
        self.assertTrue((evidence / "agent-control" / "run-result.json").is_file())
        self.assertTrue((evidence / "business-artifacts" / "release_attestation.json").is_file())
        submission = (ROOT / "src" / "sceneguard" / "submission.py").read_text(encoding="utf-8-sig")
        self.assertIn('"reports/semifinal-demo-smoke-latest.json"', submission)


if __name__ == "__main__":
    unittest.main()
