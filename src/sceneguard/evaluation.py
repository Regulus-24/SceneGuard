from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .audit import audit_asset
from .models import Severity
from .profile import QualityProfile


def run_golden_evaluation(
    manifest_path: str | Path,
    asset_root: str | Path,
    profile_path: str | Path,
) -> dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    samples = manifest.get("samples")
    if not isinstance(samples, dict) or not samples:
        raise ValueError("golden manifest requires a non-empty samples object")
    root = Path(asset_root).resolve()
    profile = QualityProfile.load(profile_path)

    results: list[dict[str, Any]] = []
    expected_total = 0
    detected_expected_total = 0
    unexpected_total = 0
    gate_matches = 0
    clean_false_positive_count = 0
    complete_evidence_jobs = 0

    for sample_name, expected in samples.items():
        if not isinstance(expected, dict):
            raise ValueError(f"invalid golden entry for {sample_name}")
        sample_path = (root / sample_name).resolve()
        if not sample_path.is_relative_to(root) or not sample_path.is_file():
            raise ValueError(f"sample is outside asset root or missing: {sample_name}")
        report = audit_asset(sample_path, profile, job_id=f"eval-{Path(sample_name).stem}")
        actual_rules = {
            item.rule_id for item in report.findings if item.severity is Severity.ERROR
        }
        expected_rules = set(expected.get("expected_error_rules", []))
        detected_expected = actual_rules & expected_rules
        unexpected = actual_rules - expected_rules
        missing = expected_rules - actual_rules
        expected_gate = expected.get("expected_gate")
        gate_match = report.gate_state.value == expected_gate
        evidence_complete = bool(
            report.asset_sha256
            and report.profile_id
            and report.profile_version
            and report.checks_completed
            and report.created_at
        )

        expected_total += len(expected_rules)
        detected_expected_total += len(detected_expected)
        unexpected_total += len(unexpected)
        gate_matches += int(gate_match)
        complete_evidence_jobs += int(evidence_complete)
        if not expected_rules:
            clean_false_positive_count += len(actual_rules)
        results.append(
            {
                "sample": sample_name,
                "expected_gate": expected_gate,
                "actual_gate": report.gate_state.value,
                "expected_error_rules": sorted(expected_rules),
                "actual_error_rules": sorted(actual_rules),
                "missing_error_rules": sorted(missing),
                "unexpected_error_rules": sorted(unexpected),
                "gate_match": gate_match,
                "evidence_complete": evidence_complete,
            }
        )

    sample_count = len(results)
    return {
        "schema_version": "0.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": f"{profile.profile_id}@{profile.version}",
        "dataset": {
            "sample_count": sample_count,
            "expected_error_rule_count": expected_total,
            "scope": "12 team-self-created deterministic GLBs plus 3 pinned CC0 public compatibility GLBs",
        },
        "metrics": {
            "sample_gate_accuracy": gate_matches / sample_count,
            "expected_rule_recall": detected_expected_total / expected_total if expected_total else 1.0,
            "unexpected_error_rule_count": unexpected_total,
            "clean_false_positive_rule_count": clean_false_positive_count,
            "evidence_completeness": complete_evidence_jobs / sample_count,
        },
        "results": results,
    }
