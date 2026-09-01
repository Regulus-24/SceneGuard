from __future__ import annotations

import unittest
from pathlib import Path


from scripts.preflight import collect_preflight, core_ready


ROOT = Path(__file__).resolve().parents[1]


class PreflightTests(unittest.TestCase):
    def test_preflight_uses_the_same_recursive_dataset_as_golden(self) -> None:
        result = collect_preflight(ROOT, docker_command="docker-test", port_check=lambda host, port: True)
        core = result["deterministic_core"]
        self.assertEqual(core["sample_count"], 15)
        self.assertEqual(core["registered_sample_count"], 15)
        self.assertEqual(core["golden_sample_count"], 15)
        self.assertIn("samples/public/BoxVertexColors.glb", core["sample_paths"])
        self.assertTrue(core["source_golden_and_disk_match"])
        self.assertTrue(core_ready(result))


if __name__ == "__main__":
    unittest.main()
