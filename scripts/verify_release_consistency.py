from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sceneguard.gateway import HTTP_API_ROUTES  # noqa: E402


def _load_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def verify() -> dict:
    facts = _load_json("release-facts.v0.1.json")
    inventory = facts["inventory"]
    release = facts["release"]
    checks: list[dict] = []

    def serializable(value):
        if isinstance(value, set):
            return sorted(value)
        return value

    def record(check_id: str, actual, expected) -> None:
        checks.append(
            {
                "check_id": check_id,
                "passed": actual == expected,
                "actual": serializable(actual),
                "expected": serializable(expected),
            }
        )

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    record("project.version", project["version"], facts["project"]["package_version"])
    record("project.python", project["requires-python"], facts["project"]["python"])
    record("dependencies.pillow", "Pillow==11.3.0" in project["dependencies"], True)

    registry = _load_json("schemas/registry.v0.1.json")
    record("inventory.schemas", len(registry["contracts"]), inventory["schemas"])
    record("inventory.skills", len(registry["skills"]), inventory["skills"])

    http_contract = _load_json("at/http_api.v0.1.json")
    record("inventory.http_contract_routes", len(http_contract["routes"]), inventory["http_routes"])
    record("inventory.http_implemented_routes", len(HTTP_API_ROUTES), inventory["http_routes"])
    contract_routes = {(item["method"], item["path"]) for item in http_contract["routes"]}
    record("inventory.http_route_set", contract_routes, set(HTTP_API_ROUTES))

    manifest = _load_json("samples/source_manifest.json")["samples"]
    disk_samples = {
        path.relative_to(ROOT / "samples").as_posix()
        for path in (ROOT / "samples").rglob("*.glb")
        if path.is_file()
    }
    public_samples = {
        name for name, metadata in manifest.items() if metadata.get("source_type") == "PUBLIC_LICENSED"
    }
    record("inventory.sample_manifest", set(manifest), disk_samples)
    record("inventory.samples_total", len(disk_samples), inventory["samples_total"])
    record("inventory.samples_public", len(public_samples), inventory["samples_public"])
    record(
        "inventory.samples_self_created",
        len(disk_samples - public_samples),
        inventory["samples_self_created"],
    )

    profiles = [_load_json(path.relative_to(ROOT).as_posix()) for path in sorted((ROOT / "profiles").glob("*.json"))]
    repair_operations = sorted(
        {
            operation
            for profile in profiles
            for operation in profile.get("repair_policy", {}).get("allowed_operations", [])
        }
    )
    record("inventory.repair_operations", repair_operations, sorted(inventory["repair_operations"]))

    runtime = _load_json("evidence/agentteams/runtime.json")
    agentteams = facts["agentteams"]
    record("agentteams.framework", runtime["framework"], agentteams["framework"])
    record("agentteams.framework_version", runtime["framework_version"], agentteams["framework_version"])
    record("agentteams.worker_runtime", runtime["worker_runtime"], agentteams["worker_runtime"])
    record("agentteams.team", runtime["team_name"], agentteams["team"])
    record("agentteams.worker_count", runtime["worker_count"], agentteams["business_workers"])
    record("agentteams.model_provider", runtime["model_provider"], agentteams["model_provider"])
    record("agentteams.model", runtime["model_name"], agentteams["model"])
    record(
        "agentteams.retained_run_discloses_assistance",
        "operator-assisted" in runtime["coordination"]["mode"].lower(),
        True,
    )
    record(
        "agentteams.automation_contract_exists",
        (ROOT / agentteams["autonomous_acceptance_contract"]).is_file(),
        True,
    )
    supervisor_evidence_path = ROOT / agentteams["validated_supervisor_evidence"]
    supervisor_stability_path = ROOT / agentteams["validated_supervisor_stability_report"]
    supervisor = json.loads(supervisor_evidence_path.read_text(encoding="utf-8"))
    stability = json.loads(supervisor_stability_path.read_text(encoding="utf-8"))
    record("agentteams.supervisor.status", supervisor["status"], "PASS")
    record("agentteams.supervisor.framework", supervisor["framework"], agentteams["framework"])
    record("agentteams.supervisor.team", supervisor["team"], agentteams["validated_supervisor_team"])
    record("agentteams.supervisor.agent_count", supervisor["agent_count"], agentteams["team_leaders"] + agentteams["business_workers"])
    record("agentteams.supervisor.worker_count", supervisor["worker_count"], agentteams["business_workers"])
    record("agentteams.supervisor.leader_model", supervisor["leader_model"], agentteams["validated_supervisor_leader_model"])
    record("agentteams.supervisor.worker_model", supervisor["worker_model"], agentteams["validated_supervisor_worker_model"])
    record("agentteams.supervisor.gate", supervisor["gate_state"], agentteams["validated_supervisor_gate"])
    record("agentteams.supervisor.operator_actions_after_dispatch", supervisor["operator_actions_after_dispatch"], agentteams["validated_supervisor_operator_actions_after_dispatch"])
    record("agentteams.stability.status", stability["status"], "PASS")
    record("agentteams.stability.sample_count", stability["sample_count"], agentteams["validated_supervisor_attempts"])
    record("agentteams.stability.passed_count", stability["passed_count"], agentteams["validated_supervisor_passed"])
    record("agentteams.stability.success_rate", stability["success_rate"], agentteams["validated_supervisor_success_rate"])
    record("agentteams.stability.p50_ms", stability["timing_ms"]["median_p50"], agentteams["validated_supervisor_p50_ms"])
    record("agentteams.stability.p90_ms", stability["timing_ms"]["p90_nearest_rank"], agentteams["validated_supervisor_p90_ms"])
    record("agentteams.stability.sha256", hashlib.sha256(supervisor_stability_path.read_bytes()).hexdigest(), supervisor["stability_report_sha256"])
    record("agentteams.supervisor.trace_count", len(supervisor["trace_refs"]), 12)
    record("agentteams.supervisor.trace_refs_exist", all((ROOT / item).is_file() for item in supervisor["trace_refs"]), True)

    docs = {
        name: (ROOT / name).read_text(encoding="utf-8")
        for name in ("README.md", "DATA_SOURCES.md", "MODEL_DISCLOSURE.md", "THIRD_PARTY_NOTICES.md")
    }
    required_doc_tokens = {
        "README.md": [
            "800+", "Top30", "12 个团队自建 GLB", "15 个真实 HTTP API",
            "qwen3.5:9b", "five-agent-supervisor-20260901.json",
        ],
        "DATA_SOURCES.md": [
            "twelve minimal GLB files", "oversized_texture.glb", "public-asset-sync-latest.json",
        ],
        "MODEL_DISCLOSURE.md": [
            "qwen3:8b", "Hermes Agent v0.10.0", "operator-assisted",
            "qwen3.5:9b", "five-agent-supervisor-20260901.json",
        ],
        "THIRD_PARTY_NOTICES.md": [
            "Pillow", "11.3.0", "HiClaw `1.1.2`", "Hermes Agent v0.10.0", "qwen3.5:9b",
        ],
    }
    for name, tokens in required_doc_tokens.items():
        for token in tokens:
            record(f"docs.{name}.{token}", token in docs[name], True)

    forbidden_doc_patterns = {
        "DATA_SOURCES.md": [r"contains eleven minimal GLB"],
        "MODEL_DISCLOSURE.md": [r"final Agent model/provider is not yet frozen"],
        "THIRD_PARTY_NOTICES.md": [r"declares no third-party runtime package"],
        "README.md": [r"登记 11 个真实 HTTP API"],
    }
    for name, patterns in forbidden_doc_patterns.items():
        for pattern in patterns:
            record(f"docs.{name}.forbid:{pattern}", re.search(pattern, docs[name]) is None, True)

    engineering_passed = all(check["passed"] for check in checks)
    blockers = []
    if release["license_status"] != "FROZEN" or not (ROOT / "LICENSE").is_file():
        blockers.append("LICENSE_DECISION_REQUIRED")
    if not (ROOT / "evidence" / "team" / "release-decisions.json").is_file():
        blockers.append("TEAM_RELEASE_DECISIONS_MISSING")

    if not engineering_passed:
        status = "FAIL_CONSISTENCY"
    elif blockers:
        status = "PASS_ENGINEERING_BLOCKED_EXTERNAL"
    else:
        status = "PASS_RELEASE_READY"
    return {
        "schema_version": "0.1",
        "status": status,
        "facts_source": "release-facts.v0.1.json",
        "checks_passed": sum(check["passed"] for check in checks),
        "checks_total": len(checks),
        "checks": checks,
        "release_blockers": blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-check SceneGuard code, docs and retained evidence")
    parser.add_argument("--output", type=Path, default=Path("reports/release-consistency.json"))
    args = parser.parse_args()
    result = verify()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"].startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
