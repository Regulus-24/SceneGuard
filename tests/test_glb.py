from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.glb import GlbFormatError, parse_glb, parse_glb_bytes  # noqa: E402


class GlbParserTests(unittest.TestCase):
    def test_parses_self_created_triangle(self) -> None:
        document = parse_glb(ROOT / "samples" / "clean_triangle.glb")
        self.assertEqual(document.json["asset"]["version"], "2.0")
        self.assertEqual(len(document.json["meshes"]), 1)
        self.assertGreater(len(document.binary), 0)
        self.assertEqual(len(document.sha256), 64)

    def test_rejects_invalid_magic(self) -> None:
        with self.assertRaisesRegex(GlbFormatError, "magic"):
            parse_glb_bytes(b"NOPE" + struct.pack("<II", 2, 12))

    def test_rejects_declared_length_mismatch(self) -> None:
        data = (ROOT / "samples" / "clean_triangle.glb").read_bytes()
        corrupted = data[:8] + struct.pack("<I", len(data) + 4) + data[12:]
        with self.assertRaisesRegex(GlbFormatError, "declares"):
            parse_glb_bytes(corrupted)


if __name__ == "__main__":
    unittest.main()
