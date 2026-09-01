import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


submission = load_script("initial_submission_check.py")
smoke = load_script("run_demo_smoke.py")
packager = load_script("build_initial_materials_package.py")


def write_minimal_pptx(path: Path, slides: int = 15, text: str = "SceneGuard") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for number in range(1, slides + 1):
            archive.writestr(
                f"ppt/slides/slide{number}.xml",
                (
                    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                    f"<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t>"
                    "</a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
                ),
            )


def write_minimal_pdf(path: Path, pages: int = 15) -> None:
    path.write_bytes(b"%PDF-1.7\n" + b"\n".join(b"<< /Type /Page >>" for _ in range(pages)) + b"\n%%EOF")


def confirmed_team() -> dict:
    return {
        "status": "CONFIRMED",
        "project_name": "SceneGuard",
        "project_name_confirmed": True,
        "source_license_status": "ALL_RIGHTS_RESERVED_NOT_PUBLIC",
        "source_license_status_confirmed": True,
        "initial_code_policy": "NOT_PUBLIC_WITH_VERIFIABLE_REVIEW_MATERIALS",
        "initial_code_policy_confirmed": True,
        "cc0_asset_reviewed": True,
        "members": [
            {
                "name": name,
                "role": f"role-{name}",
                "responsibilities": f"responsibilities-{name}",
                "information_accurate": True,
                "role_responsibilities_confirmed": True,
                "public_use_authorized": True,
                "initial_membership_locked": True,
            }
            for name in ("a", "b", "c")
        ],
        "confirmed_at": "2026-08-13T18:00:00+08:00",
    }


class InitialSubmissionTests(unittest.TestCase):
    def test_missing_materials_root_returns_failure_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "missing"
            result = submission.collect_initial_submission(root)
            checks = {item["check_id"]: item["passed"] for item in result["checks"]}
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(checks["required.materials_root"])

    def test_pending_signoff_keeps_technical_materials_green(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SceneGuard_初赛作品简介_500字内.txt").write_text("场景" * 100, encoding="utf-8")
            write_minimal_pptx(root / "SceneGuard_初赛方案v3_待团队确认.pptx")
            write_minimal_pdf(root / "SceneGuard_初赛方案v3_待团队确认.pdf")
            result = submission.collect_initial_submission(root)
            self.assertEqual(result["status"], "WAITING_TEAM_CONFIRMATION")
            self.assertTrue(result["technical_materials_passed"])
            self.assertFalse(result["team_signoff_passed"])

    def test_complete_signoff_and_formal_files_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SceneGuard_初赛作品简介_500字内.txt").write_text("场景" * 100, encoding="utf-8")
            write_minimal_pptx(root / "SceneGuard_初赛方案v3_正式版.pptx")
            write_minimal_pdf(root / "SceneGuard_初赛方案v3_正式版.pdf")
            confirmation = confirmed_team()
            (root / "TEAM_CONFIRMATION.json").write_text(
                json.dumps(confirmation, ensure_ascii=False), encoding="utf-8"
            )
            result = submission.collect_initial_submission(root)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["team_signoff_passed"])

    def test_formal_files_are_preferred_when_drafts_remain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SceneGuard_初赛作品简介_500字内.txt").write_text("场景" * 100, encoding="utf-8")
            write_minimal_pptx(root / "SceneGuard_初赛方案v3_待团队确认.pptx")
            write_minimal_pdf(root / "SceneGuard_初赛方案v3_待团队确认.pdf")
            write_minimal_pptx(root / "SceneGuard_初赛方案v3_正式版.pptx")
            write_minimal_pdf(root / "SceneGuard_初赛方案v3_正式版.pdf")
            confirmation = confirmed_team()
            (root / "TEAM_CONFIRMATION.json").write_text(
                json.dumps(confirmation, ensure_ascii=False), encoding="utf-8"
            )
            result = submission.collect_initial_submission(root)
            self.assertEqual(result["status"], "PASS")
            selected = {item["check_id"]: item["detail"] for item in result["checks"]}
            self.assertIn("正式版", selected["required.pptx"])
            self.assertIn("正式版", selected["required.pdf"])

    def test_confirmation_rejects_missing_role_and_invalid_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SceneGuard_初赛作品简介_500字内.txt").write_text("场景" * 100, encoding="utf-8")
            write_minimal_pptx(root / "SceneGuard_初赛方案v3_正式版.pptx")
            write_minimal_pdf(root / "SceneGuard_初赛方案v3_正式版.pdf")
            confirmation = confirmed_team()
            confirmation["members"][0]["role"] = ""
            confirmation["confirmed_at"] = "not-a-timestamp"
            (root / "TEAM_CONFIRMATION.json").write_text(
                json.dumps(confirmation, ensure_ascii=False), encoding="utf-8"
            )
            result = submission.collect_initial_submission(root)
            self.assertEqual(result["status"], "WAITING_TEAM_CONFIRMATION")
            self.assertFalse(result["team_signoff_passed"])

    def test_overlong_introduction_and_secret_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SceneGuard_初赛作品简介_500字内.txt").write_text("字" * 501, encoding="utf-8")
            write_minimal_pptx(root / "SceneGuard_初赛方案v3_正式版.pptx", text="Bearer abcdefghijklmnop")
            write_minimal_pdf(root / "SceneGuard_初赛方案v3_正式版.pdf")
            result = submission.collect_initial_submission(root)
            checks = {item["check_id"]: item["passed"] for item in result["checks"]}
            self.assertFalse(checks["required.introduction_limit"])
            self.assertFalse(checks["required.no_secrets"])
            self.assertEqual(result["status"], "FAIL")


class DemoSmokeTests(unittest.TestCase):
    def test_fixed_demo_contract_passes(self) -> None:
        responses = [
            ({"ok": True, "version": "0.1.0"}, {}),
            ({"assets": [{"file": "mixed_valid_degenerate.glb"}]}, {}),
            ({"profiles": [{"file": "web-realtime-v0.5-visual-demo.json"}]}, {}),
            (
                {
                    "ok": True,
                    "result": {"job_id": "job", "gate_state": "REPAIRED_PASS", "published": True},
                    "meta": {"request_id": "placeholder", "input_sha256": "a", "output_sha256": "b"},
                },
                {"x-request-id": "placeholder"},
            ),
            (
                {
                    "artifacts": [
                        {"name": "gate_decision.json"},
                        {"name": "trace.jsonl"},
                        {"name": "execution_report.json"},
                        {"name": "regression_report.json"},
                    ]
                },
                {},
            ),
            ({"content": {"gate_state": "REPAIRED_PASS", "published": True}}, {}),
        ]
        byte_responses = [(b"original", {"content-type": "model/gltf-binary"}), (b"fixed", {"content-type": "model/gltf-binary"})]

        def fake_json(*args, **kwargs):
            value = responses.pop(0)
            if kwargs.get("method") == "POST":
                request_id = kwargs["headers"]["X-Request-ID"]
                value[0]["meta"]["request_id"] = request_id
                value[1]["x-request-id"] = request_id
            return value

        with patch.object(smoke, "_json_request", side_effect=fake_json), patch.object(
            smoke, "_bytes_request", side_effect=byte_responses
        ):
            result = smoke.run_smoke("http://127.0.0.1:18096")
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(all(item["passed"] for item in result["checks"]))


class InitialMaterialsPackageTests(unittest.TestCase):
    def test_formal_package_is_scoped_and_self_verifying(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SceneGuard_初赛作品简介_500字内.txt").write_text("场景" * 100, encoding="utf-8")
            write_minimal_pptx(root / "SceneGuard_初赛方案v3_正式版.pptx")
            write_minimal_pdf(root / "SceneGuard_初赛方案v3_正式版.pdf")
            (root / "TEAM_CONFIRMATION.json").write_text(
                json.dumps(confirmed_team(), ensure_ascii=False), encoding="utf-8"
            )
            (root / "SceneGuard_Demo彩排与录屏脚本.txt").write_text("demo", encoding="utf-8")
            screenshot_dir = root / "demo_screenshots"
            screenshot_dir.mkdir()
            (screenshot_dir / "01.png").write_bytes(b"png")
            archive = root / "formal.zip"
            result = packager.build_package(root, archive)
            self.assertTrue(result["passed"])
            self.assertTrue(packager.verify_package(archive)["passed"])
            with zipfile.ZipFile(archive) as package:
                names = set(package.namelist())
                self.assertIn("MATERIALS_MANIFEST.json", names)
                self.assertIn("SUBMISSION_CHECK.json", names)
                self.assertFalse(any("待团队确认" in name for name in names))

    def test_packager_rejects_pending_signoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SceneGuard_初赛作品简介_500字内.txt").write_text("场景", encoding="utf-8")
            write_minimal_pptx(root / "SceneGuard_初赛方案v3_待团队确认.pptx")
            write_minimal_pdf(root / "SceneGuard_初赛方案v3_待团队确认.pdf")
            with self.assertRaisesRegex(ValueError, "must be PASS"):
                packager.build_package(root, root / "formal.zip")


if __name__ == "__main__":
    unittest.main()
