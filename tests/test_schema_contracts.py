from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.schema_contracts import SchemaContractError, SchemaStore  # noqa: E402


class SchemaContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SchemaStore(ROOT / "schemas")

    def test_all_registered_schemas_are_safe_draft_2020_12_documents(self) -> None:
        registry = json.loads((ROOT / "schemas" / "registry.v0.1.json").read_text(encoding="utf-8"))
        for contract in registry["contracts"]:
            with self.subTest(contract=contract["id"]):
                path, payload = self.store.load(ROOT / contract["path"])
                self.assertTrue(path.is_relative_to(ROOT / "schemas"))
                self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_profile_contract_accepts_current_profiles_and_rejects_missing_rules(self) -> None:
        schema = ROOT / "schemas" / "goal-contract.schema.json"
        for profile_path in sorted((ROOT / "profiles").glob("*.json")):
            with self.subTest(profile=profile_path.name):
                payload = json.loads(profile_path.read_text(encoding="utf-8"))
                self.assertEqual(self.store.validate(payload, schema), [])
        invalid = json.loads((ROOT / "profiles" / "web-realtime-v0.2.json").read_text(encoding="utf-8"))
        del invalid["rules"]["max_triangles"]
        issues = self.store.validate(invalid, schema)
        self.assertTrue(any("max_triangles" in issue.message for issue in issues))

    def test_runtime_artifacts_match_published_contracts(self) -> None:
        examples = {
            "audit-report.schema.json": ROOT / "jobs" / "delivery-repair" / "artifacts" / "audit_report.json",
            "patch-plan.schema.json": ROOT / "jobs" / "delivery-repair" / "artifacts" / "patch_plan.json",
            "execution-report.schema.json": ROOT / "jobs" / "delivery-repair" / "artifacts" / "execution_report.json",
            "regression-report.schema.json": ROOT / "jobs" / "delivery-repair" / "artifacts" / "regression_report.json",
        }
        for schema, example in examples.items():
            with self.subTest(schema=schema):
                payload = json.loads(example.read_text(encoding="utf-8"))
                self.assertEqual(self.store.validate(payload, ROOT / "schemas" / schema), [])

    def test_remote_schema_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema = root / "unsafe.json"
            schema.write_text(
                json.dumps(
                    {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "$ref": "https://example.com/remote.json",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SchemaContractError, "remote"):
                SchemaStore(root).validate({}, schema)


if __name__ == "__main__":
    unittest.main()
