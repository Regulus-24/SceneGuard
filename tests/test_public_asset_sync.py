from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sync_public_assets",
    ROOT / "scripts" / "sync_public_assets.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublicAssetSyncTests(unittest.TestCase):
    def test_all_three_retained_github_assets_verify_offline(self) -> None:
        report = MODULE.sync_all(download=False)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["asset_count"], 3)
        self.assertTrue(all(item["license_spdx"] == "CC0-1.0" for item in report["assets"]))
        self.assertTrue(all(len(item["upstream_commit"]) == 40 for item in report["assets"]))

    def test_unpinned_download_url_is_rejected(self) -> None:
        source = json.loads(
            (ROOT / "samples" / "public" / "BoxVertexColors.source.json").read_text(
                encoding="utf-8"
            )
        )
        source["download_url"] = (
            "https://raw.githubusercontent.com/KhronosGroup/"
            "glTF-Sample-Assets/main/Models/BoxVertexColors/glTF-Binary/"
            "BoxVertexColors.glb"
        )
        with self.assertRaisesRegex(ValueError, "pinned"):
            MODULE.validate_record(source)

    def test_tampered_payload_is_rejected(self) -> None:
        source = json.loads(
            (ROOT / "samples" / "public" / "BoxVertexColors.source.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaisesRegex(ValueError, "byte size mismatch"):
            MODULE.verify_payload(source, b"tampered")


if __name__ == "__main__":
    unittest.main()
