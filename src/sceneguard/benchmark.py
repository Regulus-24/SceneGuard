from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io_utils import atomic_write_json
from urllib.parse import urlparse

from .audit import audit_asset
from .evaluation import run_golden_evaluation
from .gateway import (
    HTTP_API_ROUTES,
    MAX_ARTIFACT_BYTES,
    MAX_REQUEST_BYTES,
    GatewayError,
    GatewayService,
    validate_gateway_security,
)
from .pipeline import run_job
from .profile import QualityProfile
from .runtime_environment import find_docker_executable
from .schema_contracts import SchemaContractError, SchemaStore
from .submission import verify_submission_manifest
from .workspace import sha256_file


TEXT_EVIDENCE_SUFFIXES = {".json", ".jsonl", ".log", ".md", ".txt"}
MAX_EVIDENCE_TEXT_BYTES = 2 * 1024 * 1024
EVIDENCE_SECRET_PATTERNS = {
    "alibaba_access_key_id": re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b"),
    "openai_style_api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    "bearer_token": re.compile(r"(?i)\bBearer\s+(?!<?redacted>?\b)[A-Za-z0-9._~+/=-]{8,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential_assignment": re.compile(
        r"(?im)[\"']?(?:DASHSCOPE_API_KEY|HICLAW_LLM_API_KEY|HICLAW_ADMIN_PASSWORD|"
        r"ALIBABA_CLOUD_ACCESS_KEY_ID|ALIBABA_CLOUD_ACCESS_KEY_SECRET|ALIYUN_ACCESS_KEY_ID|"
        r"ALIYUN_ACCESS_KEY_SECRET|SCENEGUARD_(?:API|DEMO)_TOKEN)[\"']?\s*[:=]\s*[\"']?"
        r"(?!<?redacted>?\b|\*{4,})[^\s,\"']{6,}"
    ),
    "windows_user_path": re.compile(r"(?i)\b[A-Z]:\\+Users\\+[^\\\s]+"),
    "unix_user_path": re.compile(r"(?i)(?:/Users|/home)/[^/\s]+/"),
}


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    passed: bool
    points: int
    earned: int
    summary: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "points": self.points,
            "earned": self.earned,
            "summary": self.summary,
            "evidence": self.evidence,
        }


def run_acceptance_benchmark(
    root: str | Path,
    config_path: str | Path = "benchmark/acceptance.v0.1.json",
    *,
    include_test_suite: bool = True,
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    config_file = _inside(project_root, config_path)
    config = json.loads(config_file.read_text(encoding="utf-8"))
    started = time.monotonic()
    checks: list[CheckResult] = []

    checks.append(_compile_check(project_root))
    if include_test_suite:
        checks.append(_test_check(project_root, int(config["minimum_test_count"])))
    checks.append(_golden_check(project_root, config))
    checks.append(_public_asset_check(project_root, config))
    checks.append(_pipeline_check(project_root, config))
    checks.append(_gateway_security_check())
    checks.append(_gateway_contract_check(project_root))
    checks.append(_api_contract_check(project_root, config))
    checks.append(_structure_check(project_root, config))
    checks.append(_loop_supervisor_check(project_root, config))
    checks.append(_compliance_check(project_root, config))
    checks.append(_schema_contract_check(project_root, config))
    checks.append(_contract_sync_check(project_root, config))
    checks.append(_submission_manifest_check(project_root, config))
    registry_check, requirements_registry = _requirements_registry_check(project_root, config, checks)
    checks.append(registry_check)

    total_points = sum(item.points for item in checks)
    earned_points = sum(item.earned for item in checks)
    core_passed = all(item.passed for item in checks)
    external = _external_evidence(project_root, config)
    requirements = _compile_requirement_coverage(project_root, requirements_registry, checks, external)
    core_passed = core_passed and requirements["core"]["passed"]
    release_passed = core_passed and external["passed"] and requirements["release"]["passed"]
    if release_passed:
        release_status = "PASS"
    elif core_passed:
        release_status = "BLOCKED_EXTERNAL"
    else:
        release_status = "FAIL_CORE"

    return {
        "schema_version": "0.1",
        "benchmark_id": config["benchmark_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((time.monotonic() - started) * 1000),
        "core": {
            "status": "PASS" if core_passed else "FAIL",
            "score": earned_points,
            "max_score": total_points,
            "checks": [item.to_dict() for item in checks],
        },
        "release": {
            "status": release_status,
            "external_evidence": external,
        },
        "requirements": requirements,
        "next_actions": _next_actions(checks, external),
        "stop_policy": config["stop_policy"],
    }


def write_benchmark_receipt(result: dict[str, Any], output: str | Path) -> Path:
    return atomic_write_json(output, result)


def _compile_check(root: Path) -> CheckResult:
    command = [sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"]
    completed = _run(command, root)
    passed = completed["exit_code"] == 0
    return CheckResult(
        "python.compile",
        passed,
        5,
        5 if passed else 0,
        "Python source compiles" if passed else "Python compilation failed",
        completed,
    )


def _test_check(root: Path, minimum: int) -> CheckResult:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    completed = _run(command, root)
    joined = "\n".join(completed["tail"])
    match = re.search(r"Ran (\d+) tests?", joined)
    count = int(match.group(1)) if match else 0
    passed = completed["exit_code"] == 0 and count >= minimum
    completed["test_count"] = count
    completed["minimum_test_count"] = minimum
    return CheckResult(
        "tests.regression",
        passed,
        20,
        20 if passed else 0,
        f"{count} tests passed" if passed else f"test suite failed or ran fewer than {minimum} tests",
        completed,
    )


def _golden_check(root: Path, config: dict[str, Any]) -> CheckResult:
    result = run_golden_evaluation(
        _inside(root, config["golden_manifest"]),
        root / "samples",
        _inside(root, config["profiles"]["golden"]),
    )
    metrics = result["metrics"]
    passed = bool(
        metrics["sample_gate_accuracy"] == 1.0
        and metrics["expected_rule_recall"] == 1.0
        and metrics["unexpected_error_rule_count"] == 0
        and metrics["evidence_completeness"] == 1.0
        and result["dataset"]["sample_count"] >= int(config["minimum_golden_sample_count"])
        and result["dataset"]["expected_error_rule_count"] >= int(config["minimum_expected_error_count"])
    )
    return CheckResult(
        "evaluation.golden",
        passed,
        15,
        15 if passed else 0,
        "Golden findings are exact" if passed else "Golden evaluation regressed",
        {"dataset": result["dataset"], "metrics": metrics},
    )


def _public_asset_check(root: Path, config: dict[str, Any]) -> CheckResult:
    settings = config.get("public_asset_benchmark", {})
    errors: list[str] = []
    evidence: dict[str, Any] = {}
    try:
        asset = _inside(root, settings["asset"])
        source_record_path = _inside(root, settings["source_record"])
        profile_path = _inside(root, settings["profile"])
        source_record = json.loads(source_record_path.read_text(encoding="utf-8"))
        digest = sha256_file(asset)
        asset_page = urlparse(str(source_record.get("asset_page_url", "")))
        download = urlparse(str(source_record.get("download_url", "")))
        license_evidence = urlparse(str(source_record.get("license_evidence_url", "")))
        metadata_valid = bool(
            source_record.get("source_type") == "PUBLIC_LICENSED"
            and source_record.get("license_spdx") == settings["required_license_spdx"]
            and source_record.get("license") == settings["required_license_spdx"]
            and source_record.get("redistribution_allowed") is True
            and source_record.get("modification_allowed") is True
            and source_record.get("sha256") == settings["expected_sha256"] == digest
            and source_record.get("bytes") == asset.stat().st_size
            and re.fullmatch(r"[a-f0-9]{40}", str(source_record.get("upstream_commit", ""))) is not None
            and asset_page.scheme == "https"
            and asset_page.hostname == "github.com"
            and asset_page.path.startswith("/KhronosGroup/glTF-Sample-Assets/")
            and source_record.get("source_url") == source_record.get("asset_page_url")
            and download.scheme == "https"
            and download.hostname == "raw.githubusercontent.com"
            and download.path.startswith("/KhronosGroup/glTF-Sample-Assets/")
            and license_evidence.scheme == "https"
            and license_evidence.hostname == "github.com"
            and bool(str(source_record.get("creator", "")).strip())
            and bool(str(source_record.get("asset_id", "")).strip())
            and _valid_datetime(source_record.get("retrieved_at"))
        )
        profile = QualityProfile.load(profile_path)
        report = audit_asset(asset, profile, job_id="public-asset-benchmark")
        runtime_valid = bool(
            report.gate_state.value == "PASS"
            and report.error_count == 0
            and not report.checks_incomplete
            and report.asset_sha256 == digest
        )
        manifest = json.loads((root / "samples" / "source_manifest.json").read_text(encoding="utf-8"))
        manifest_entry = manifest.get("samples", {}).get(asset.relative_to(root / "samples").as_posix(), {})
        manifest_valid = bool(
            isinstance(manifest_entry, dict)
            and manifest_entry.get("source_record") == source_record_path.relative_to(root / "samples").as_posix()
            and manifest_entry.get("license_spdx") == settings["required_license_spdx"]
            and manifest_entry.get("sha256") == digest
        )
        if not metadata_valid:
            errors.append("public asset source/license metadata is incomplete")
        if not runtime_valid:
            errors.append("public asset did not pass the dedicated read-only Profile")
        if not manifest_valid:
            errors.append("public asset is not bound into source_manifest.json")
        evidence = {
            "asset": asset.relative_to(root).as_posix(),
            "sha256": digest,
            "bytes": asset.stat().st_size,
            "license_spdx": source_record.get("license_spdx"),
            "creator": source_record.get("creator"),
            "upstream_commit": source_record.get("upstream_commit"),
            "review_status": source_record.get("review_status"),
            "human_reviewer": source_record.get("human_reviewer"),
            "metadata_valid": metadata_valid,
            "manifest_valid": manifest_valid,
            "runtime_gate": report.gate_state.value,
            "checks_complete": not report.checks_incomplete,
            "measurements": report.measurements,
            "errors": errors,
        }
    except (KeyError, OSError, TypeError, ValueError) as exc:
        errors.append(f"public asset benchmark failed: {exc}")
        evidence = {"errors": errors}
    passed = not errors
    return CheckResult(
        "evaluation.public_asset",
        passed,
        0,
        0,
        "Pinned CC0 public GLB passed a dedicated read-only Profile" if passed else "public asset evidence failed",
        evidence,
    )


def _pipeline_check(root: Path, config: dict[str, Any]) -> CheckResult:
    default_profile = QualityProfile.load(_inside(root, config["profiles"]["repair"]))
    case_results: dict[str, Any] = {}
    repair_results: dict[str, Any] = {}
    rollback_results: dict[str, Any] = {}
    all_passed = True
    with tempfile.TemporaryDirectory(prefix="sceneguard-benchmark-") as directory:
        for case_id, case in config["required_gate_cases"].items():
            source = _inside(root, case["asset"])
            profile = QualityProfile.load(_inside(root, case["profile"])) if case.get("profile") else default_profile
            source_hash = sha256_file(source)
            result = run_job(
                source,
                profile,
                directory,
                job_id=case_id,
                auto_repair=case.get("auto_repair", True),
                fault_injection=case.get("fault_injection"),
                approval_decision=case.get("approval_decision"),
                approval_actor="benchmark-reviewer",
            )
            job_root = Path(directory) / case_id
            trace_path = job_root / "artifacts" / "trace.jsonl"
            trace_events = []
            if trace_path.is_file():
                trace_events = [json.loads(line)["event"] for line in trace_path.read_text(encoding="utf-8").splitlines()]
            original_unchanged = sha256_file(source) == source_hash == result["original_sha256"]
            required_artifacts = [
                job_root / "artifacts" / "audit_report.json",
                job_root / "artifacts" / "patch_plan.json",
                job_root / "artifacts" / "gate_decision.json",
                trace_path,
                job_root / "artifacts" / "metrics.json",
            ]
            artifacts_complete = all(path.is_file() for path in required_artifacts)
            metrics = {}
            metrics_path = job_root / "artifacts" / "metrics.json"
            if metrics_path.is_file():
                metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics_complete = bool(
                metrics.get("gate_state") == result["gate_state"]
                and isinstance(metrics.get("end_to_end_duration_ms"), int)
                and metrics.get("trace_event_count") == len(trace_events)
            )
            trace_ids = {
                json.loads(line)["trace_id"]
                for line in trace_path.read_text(encoding="utf-8").splitlines()
            } if trace_path.is_file() else set()
            trace_correlated = len(trace_ids) == 1
            state_match = result["gate_state"] == case["expected_state"]
            rollback_proved = case_id != "rollback" or (
                "rollback.completed" in trace_events and result["working_sha256"] == result["original_sha256"]
            )
            approval_request_path = job_root / "artifacts" / "approval_request.json"
            approval_record_path = job_root / "artifacts" / "approval_record.json"
            approval_proved = True
            if case_id.startswith("approval_"):
                approval_proved = approval_request_path.is_file()
                if case.get("approval_decision"):
                    approval_proved = approval_proved and approval_record_path.is_file()
                    if approval_record_path.is_file():
                        record = json.loads(approval_record_path.read_text(encoding="utf-8"))
                        plan_payload = json.loads((job_root / "artifacts" / "patch_plan.json").read_text(encoding="utf-8"))
                        approval_proved = approval_proved and bool(
                            record.get("decision") == case["approval_decision"]
                            and record.get("plan_id") == plan_payload.get("plan_id")
                            and record.get("asset_sha256") == plan_payload.get("asset_sha256")
                        )
                else:
                    approval_proved = approval_proved and not approval_record_path.exists()
            case_passed = (
                state_match
                and original_unchanged
                and artifacts_complete
                and rollback_proved
                and metrics_complete
                and trace_correlated
                and approval_proved
            )
            all_passed = all_passed and case_passed
            case_results[case_id] = {
                "passed": case_passed,
                "expected_state": case["expected_state"],
                "actual_state": result["gate_state"],
                "original_unchanged": original_unchanged,
                "artifacts_complete": artifacts_complete,
                "rollback_proved": rollback_proved,
                "metrics_complete": metrics_complete,
                "trace_correlated": trace_correlated,
                "approval_proved": approval_proved,
                "trace_events": trace_events,
            }
        repair_config = config.get("repair_benchmark", {})
        repair_assets = repair_config.get("assets", []) if isinstance(repair_config, dict) else []
        for index, asset_reference in enumerate(repair_assets, start=1):
            job_id = f"repair-benchmark-{index:02d}"
            source = _inside(root, asset_reference)
            source_hash = sha256_file(source)
            result = run_job(source, default_profile, directory, job_id=job_id)
            job_root = Path(directory) / job_id
            regression_path = job_root / "artifacts" / "regression_report.json"
            regression_state = None
            if regression_path.is_file():
                regression_state = json.loads(regression_path.read_text(encoding="utf-8")).get("gate_state")
            passed = bool(
                result.get("gate_state") == "REPAIRED_PASS"
                and result.get("published") is True
                and source_hash == sha256_file(source) == result.get("original_sha256")
                and regression_state == "REPAIRED_PASS"
            )
            repair_results[asset_reference] = {
                "passed": passed,
                "gate_state": result.get("gate_state"),
                "published": result.get("published"),
                "original_unchanged": source_hash == sha256_file(source) == result.get("original_sha256"),
                "regression_state": regression_state,
            }
        rollback_config = config.get("rollback_benchmark", {})
        rollback_modes = rollback_config.get("fault_injections", []) if isinstance(rollback_config, dict) else []
        rollback_source = _inside(root, rollback_config["asset"])
        rollback_source_hash = sha256_file(rollback_source)
        for index, mode in enumerate(rollback_modes, start=1):
            job_id = f"rollback-benchmark-{index:02d}"
            result = run_job(
                rollback_source,
                default_profile,
                directory,
                job_id=job_id,
                fault_injection=mode,
            )
            job_root = Path(directory) / job_id
            trace_path = job_root / "artifacts" / "trace.jsonl"
            trace_events = [
                json.loads(line).get("event")
                for line in trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            working_hash = sha256_file(job_root / "working" / "candidate.glb")
            passed = bool(
                result.get("gate_state") == "FAILED_ROLLBACK"
                and result.get("published") is False
                and isinstance(result.get("rollback"), dict)
                and result["rollback"].get("success") is True
                and rollback_source_hash == sha256_file(rollback_source) == working_hash
                and "demo.fault_injected" in trace_events
                and "rollback.completed" in trace_events
                and not (job_root / "published" / "asset.glb").exists()
            )
            rollback_results[str(mode)] = {
                "passed": passed,
                "gate_state": result.get("gate_state"),
                "published": result.get("published"),
                "rollback_success": result.get("rollback", {}).get("success") if isinstance(result.get("rollback"), dict) else False,
                "working_restored": working_hash == rollback_source_hash,
                "trace_events": trace_events,
            }

    repair_config = config.get("repair_benchmark", {})
    configured_repair_attempts = len(repair_assets)
    repair_attempts = len(repair_results)
    repair_successes = sum(item["passed"] for item in repair_results.values())
    repair_success_rate = repair_successes / repair_attempts if repair_attempts else 0.0
    minimum_attempts = int(repair_config.get("minimum_attempts", 5))
    minimum_success_rate = float(repair_config.get("minimum_success_rate", 0.9))
    repair_threshold_met = bool(
        repair_attempts >= minimum_attempts
        and repair_attempts == configured_repair_attempts
        and repair_success_rate >= minimum_success_rate
    )
    all_passed = all_passed and repair_threshold_met
    rollback_config = config.get("rollback_benchmark", {})
    configured_rollback_attempts = len(rollback_modes)
    rollback_attempts = len(rollback_results)
    rollback_successes = sum(item["passed"] for item in rollback_results.values())
    rollback_success_rate = rollback_successes / rollback_attempts if rollback_attempts else 0.0
    minimum_failure_modes = int(rollback_config.get("minimum_failure_modes", 3))
    required_rollback_rate = float(rollback_config.get("required_success_rate", 1.0))
    rollback_threshold_met = bool(
        rollback_attempts >= minimum_failure_modes
        and rollback_attempts == configured_rollback_attempts
        and rollback_success_rate >= required_rollback_rate
    )
    all_passed = all_passed and rollback_threshold_met
    evidence_complete_count = sum(item["artifacts_complete"] and item["metrics_complete"] for item in case_results.values())
    metrics = {
        "gate_case_accuracy": sum(item["expected_state"] == item["actual_state"] for item in case_results.values()) / len(case_results),
        "auto_repair_success_rate": repair_success_rate,
        "regression_pass_rate": repair_success_rate,
        "rollback_success_rate": rollback_success_rate,
        "evidence_completeness": evidence_complete_count / len(case_results),
        "denominators": {
            "gate_cases": len(case_results),
            "repair_attempts": repair_attempts,
            "configured_repair_attempts": configured_repair_attempts,
            "distinct_repair_assets": len(repair_results),
            "minimum_repair_attempts": minimum_attempts,
            "minimum_repair_success_rate": minimum_success_rate,
            "rollback_attempts": rollback_attempts,
            "configured_rollback_attempts": configured_rollback_attempts,
            "minimum_failure_modes": minimum_failure_modes,
            "required_rollback_success_rate": required_rollback_rate,
            "evidence_jobs": len(case_results),
        },
    }
    return CheckResult(
        "pipeline.five_gate_states",
        all_passed,
        25,
        25 if all_passed else 0,
        "All five gate states and rollback evidence passed" if all_passed else "one or more gate cases failed",
        {
            "cases": case_results,
            "repair_benchmark": {
                "operation": repair_config.get("operation"),
                "threshold_met": repair_threshold_met,
                "cases": repair_results,
            },
            "rollback_benchmark": {
                "threshold_met": rollback_threshold_met,
                "cases": rollback_results,
            },
            "metrics": metrics,
        },
    )


def _structure_check(root: Path, config: dict[str, Any]) -> CheckResult:
    agents = {
        name: (root / "agents" / name / "Agent.md").is_file()
        for name in config["required_agents"]
    }
    skills = {
        name: (root / "skills" / name / "SKILL.md").is_file()
        for name in config["required_core_skills"]
    }
    team_spec_valid = False
    try:
        team_spec = json.loads((root / "at" / "team_spec.json").read_text(encoding="utf-8"))
        team_spec_valid = isinstance(team_spec.get("agents"), list) and len(team_spec["agents"]) == 4
    except (OSError, ValueError):
        pass
    passed = all(agents.values()) and all(skills.values()) and team_spec_valid
    return CheckResult(
        "agent_skill.structure",
        passed,
        5,
        5 if passed else 0,
        "5 Agent identities and core Skill specs are present" if passed else "Agent/Skill structure is incomplete",
        {"agents": agents, "skills": skills, "team_spec_valid": team_spec_valid},
    )


def _loop_supervisor_check(root: Path, config: dict[str, Any]) -> CheckResult:
    required_files = {
        relative: (root / relative).is_file()
        for relative in (
            "src/sceneguard/io_utils.py",
            "src/sceneguard/loop_control.py",
            "src/sceneguard/loop_session.py",
            "benchmark/loop-supervisor-contract.v0.1.json",
            "scripts/run_loop_iteration.py",
            "scripts/run_loop_supervisor.py",
            "scripts/preflight.py",
            "tests/test_loop_control.py",
            "tests/test_loop_session.py",
            "tests/test_preflight.py",
        )
    }
    policy = config.get("stop_policy", {})
    policy_valid = bool(
        policy.get("max_iterations") == 50
        and policy.get("max_consecutive_no_improvement") == 3
        and policy.get("max_consecutive_same_failure") == 3
        and policy.get("default_session_hours") == 10
        and policy.get("max_session_hours") == 24
        and policy.get("external_blockers_require_human_or_environment_change") is True
    )
    source = (root / "src" / "sceneguard" / "loop_session.py").read_text(encoding="utf-8") if required_files["src/sceneguard/loop_session.py"] else ""
    safety_markers = {
        marker: marker in source
        for marker in (
            "LoopSessionLock",
            "STOP_TIME_BUDGET",
            "AGENT_ACTION_REQUIRED",
            "REGRESSION_DETECTED",
            "shell=False",
            "build_submission_archive",
            "do_not_fabricate_external_evidence",
        )
    }
    contract_valid = False
    contract_evidence: dict[str, Any] = {}
    try:
        contract = json.loads((root / "benchmark" / "loop-supervisor-contract.v0.1.json").read_text(encoding="utf-8"))
        enforced = contract.get("enforced_controls", {})
        limitations = contract.get("honest_limitations", {})
        worker = contract.get("worker_interface", {})
        time_budget = contract.get("time_budget", {})
        expected_outcomes = {
            "COMPLETE",
            "AWAIT_EXTERNAL_EVIDENCE",
            "STOP_ITERATION_LIMIT",
            "STOP_TIME_BUDGET",
            "AGENT_ACTION_REQUIRED",
            "WORKER_FAILED",
            "REGRESSION_DETECTED",
        }
        required_true_controls = {
            "exclusive_session_lock",
            "atomic_latest_receipt_and_state",
            "immutable_iteration_receipts",
            "pre_worker_recovery_archive",
            "stop_on_lower_core_score",
            "external_watch_without_benchmark_spin",
        }
        contract_valid = bool(
            contract.get("schema_version") == "0.1"
            and time_budget.get("default_hours") == 10
            and time_budget.get("maximum_hours") == 24
            and worker.get("explicit_argv") is True
            and worker.get("shell") is False
            and worker.get("stdout_stderr_persisted") is False
            and all(enforced.get(name) is True for name in required_true_controls)
            and enforced.get("fabricated_external_evidence_allowed") is False
            and all(value is False for value in limitations.values())
            and set(contract.get("terminal_outcomes", [])) == expected_outcomes
        )
        contract_evidence = {
            "contract_id": contract.get("contract_id"),
            "limitations_disclosed": limitations,
            "terminal_outcomes": contract.get("terminal_outcomes", []),
        }
    except (OSError, ValueError):
        contract_evidence = {"error": "contract missing or invalid JSON"}
    passed = all(required_files.values()) and policy_valid and all(safety_markers.values()) and contract_valid
    return CheckResult(
        "loop.supervision",
        passed,
        0,
        0,
        "Bounded long-running loop supervision is fail-closed" if passed else "Loop supervisor safety contract is incomplete",
        {
            "required_files": required_files,
            "stop_policy_valid": policy_valid,
            "safety_markers": safety_markers,
            "machine_contract_valid": contract_valid,
            "machine_contract": contract_evidence,
            "capabilities": {
                "atomic_receipts": True,
                "exclusive_session_lock": True,
                "wall_clock_budget": True,
                "immutable_iteration_receipts": True,
                "explicit_worker_argv_without_shell": True,
                "pre_worker_recovery_archive": True,
                "regression_stop_without_destructive_restore": True,
                "external_evidence_watch_without_test_spin": True,
            },
        },
    )


def _compliance_check(root: Path, config: dict[str, Any]) -> CheckResult:
    required = {
        name: (root / name).is_file()
        for name in ("THIRD_PARTY_NOTICES.md", "DATA_SOURCES.md", "MODEL_DISCLOSURE.md", "SECURITY.md")
    }
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    manifest = json.loads((root / "samples" / "source_manifest.json").read_text(encoding="utf-8"))
    golden = json.loads(_inside(root, config["golden_manifest"]).read_text(encoding="utf-8"))
    notices = (root / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    dependency_policy_valid = (
        'dependencies = ["Pillow==11.3.0"]' in pyproject
        and "Pillow" in notices
        and "11.3.0" in notices
    )
    source_samples = set(manifest.get("samples", {})) if isinstance(manifest.get("samples"), dict) else set()
    golden_samples = set(golden.get("samples", {})) if isinstance(golden.get("samples"), dict) else set()
    minimum_samples = int(config["minimum_golden_sample_count"])
    self_created_count = sum(
        1
        for item in manifest.get("samples", {}).values()
        if isinstance(item, dict) and item.get("source_type", "SELF_CREATED") == "SELF_CREATED"
    )
    source_registry_valid = bool(
        manifest.get("source_type") in {"SELF_CREATED", "MIXED_SELF_CREATED_AND_LICENSED_PUBLIC"}
        and len(source_samples) >= minimum_samples
        and self_created_count >= 11
        and source_samples == golden_samples
    )
    secret_files_absent = not any((root / name).exists() for name in (".env", "credentials.json", "secrets.json"))
    passed = all(required.values()) and dependency_policy_valid and source_registry_valid and secret_files_absent
    return CheckResult(
        "compliance.disclosure",
        passed,
        5,
        5 if passed else 0,
        "dependency, data, model and security disclosures are present" if passed else "release disclosures are incomplete",
        {
            "documents": required,
            "runtime_dependencies_locked_and_disclosed": dependency_policy_valid,
            "registered_sample_count": len(manifest.get("samples", {})),
            "actual_self_created_sample_count": self_created_count,
            "minimum_sample_count": minimum_samples,
            "source_and_golden_names_match": source_samples == golden_samples,
            "secret_files_absent": secret_files_absent,
        },
    )


def _schema_contract_check(root: Path, config: dict[str, Any]) -> CheckResult:
    registry_path = _inside(root, config.get("schema_registry", "schemas/registry.v0.1.json"))
    errors: list[str] = []
    validated_examples: dict[str, list[str]] = {}
    skill_contracts: dict[str, bool] = {}
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        store = SchemaStore(root / "schemas")
        contract_paths: set[str] = set()
        for contract in registry.get("contracts", []):
            if not isinstance(contract, dict) or not isinstance(contract.get("path"), str):
                errors.append("schema registry contains an invalid contract entry")
                continue
            relative = contract["path"]
            try:
                path = _inside(root, relative)
                store.load(path)
                contract_paths.add(relative)
            except (OSError, ValueError, SchemaContractError) as exc:
                errors.append(f"invalid contract {relative}: {exc}")

        registered_skills: set[str] = set()
        for skill in registry.get("skills", []):
            if not isinstance(skill, dict) or not isinstance(skill.get("id"), str):
                errors.append("schema registry contains an invalid skill entry")
                continue
            skill_id = skill["id"]
            registered_skills.add(skill_id)
            document = root / "skills" / skill_id / "SKILL.md"
            metadata = _skill_contract_metadata(document)
            expected = {
                name: str(skill.get(name, ""))
                for name in ("input_schema", "output_schema", "dependency", "dependency_version", "timeout_seconds")
            }
            matches = all(metadata.get(name) == value for name, value in expected.items())
            timeout_valid = isinstance(skill.get("timeout_seconds"), int) and 0 < skill["timeout_seconds"] <= 300
            schemas_known = all(skill.get(name) in contract_paths for name in ("input_schema", "output_schema"))
            skill_contracts[skill_id] = matches and timeout_valid and schemas_known
            if not skill_contracts[skill_id]:
                errors.append(f"Skill contract metadata is missing or stale: {skill_id}")

        required_skills = set(config.get("required_core_skills", []))
        if registered_skills != required_skills:
            errors.append("schema registry Skill ids do not exactly match required_core_skills")

        for profile_path in sorted((root / "profiles").glob("*.json")):
            payload = json.loads(profile_path.read_text(encoding="utf-8"))
            issues = store.validate(payload, root / "schemas" / "goal-contract.schema.json")
            validated_examples.setdefault("GoalContract", []).append(profile_path.relative_to(root).as_posix())
            errors.extend(_schema_issue_messages(profile_path.relative_to(root).as_posix(), issues))

        with tempfile.TemporaryDirectory(prefix="sceneguard-schema-contract-") as directory:
            result = run_job(
                root / "samples" / "degenerate_triangle.glb",
                QualityProfile.load(_inside(root, config["profiles"]["repair"])),
                directory,
                job_id="schema-contract",
            )
            artifacts = Path(directory) / "schema-contract" / "artifacts"
            examples = {
                "AuditReport": (artifacts / "audit_report.json", "audit-report.schema.json"),
                "PatchPlan": (artifacts / "patch_plan.json", "patch-plan.schema.json"),
                "ExecutionReport": (artifacts / "execution_report.json", "execution-report.schema.json"),
                "RegressionAudit": (artifacts / "regression_audit.json", "audit-report.schema.json"),
                "RegressionReport": (artifacts / "regression_report.json", "regression-report.schema.json"),
                "GateDecision": (artifacts / "gate_decision.json", "gate-decision.schema.json"),
            }
            if result.get("gate_state") != "REPAIRED_PASS":
                errors.append("schema example pipeline did not reach REPAIRED_PASS")
            for contract_id, (example_path, schema_name) in examples.items():
                payload = json.loads(example_path.read_text(encoding="utf-8"))
                issues = store.validate(payload, root / "schemas" / schema_name)
                validated_examples.setdefault(contract_id, []).append(f"generated:{example_path.name}")
                errors.extend(_schema_issue_messages(contract_id, issues))
            audit_payload = json.loads((artifacts / "audit_report.json").read_text(encoding="utf-8"))
            candidate_payload = json.loads((artifacts / "regression_audit.json").read_text(encoding="utf-8"))
            plan_payload = json.loads((artifacts / "patch_plan.json").read_text(encoding="utf-8"))
            profile_payload = json.loads(_inside(root, config["profiles"]["repair"]).read_text(encoding="utf-8"))
            input_examples = {
                "AssetProfileInput": (
                    {"profile": config["profiles"]["repair"], "purpose": "web realtime"},
                    "asset-profile-input.schema.json",
                ),
                "AssetAuditInput": (
                    {
                        "asset": "degenerate_triangle.glb",
                        "profile": Path(config["profiles"]["repair"]).name,
                        "job_id": "schema-contract",
                    },
                    "asset-audit-input.schema.json",
                ),
                "PipelineRunInput": (
                    {
                        "asset": "degenerate_triangle.glb",
                        "profile": Path(config["profiles"]["repair"]).name,
                        "job_id": "schema-contract",
                        "auto_repair": True,
                    },
                    "pipeline-run-input.schema.json",
                ),
                "RepairPlanInput": (
                    {"audit_report": audit_payload, "profile": profile_payload},
                    "repair-plan-input.schema.json",
                ),
                "RepairExecutionInput": (
                    {
                        "job_id": "schema-contract",
                        "working_asset": "working/candidate.glb",
                        "patch_plan": plan_payload,
                        "step_id": "step-001",
                    },
                    "repair-execution-input.schema.json",
                ),
                "RegressionVerifyInput": (
                    {
                        "original_report": audit_payload,
                        "candidate_report": candidate_payload,
                        "target_rules": ["mesh.degenerate_triangles"],
                        "repair_attempted": True,
                    },
                    "regression-verify-input.schema.json",
                ),
            }
            for contract_id, (payload, schema_name) in input_examples.items():
                issues = store.validate(payload, root / "schemas" / schema_name)
                validated_examples.setdefault(contract_id, []).append("generated:benchmark-input")
                errors.extend(_schema_issue_messages(contract_id, issues))
            for finding in audit_payload.get("findings", []):
                issues = store.validate(finding, root / "schemas" / "finding.schema.json")
                validated_examples.setdefault("Finding", []).append(f"generated:{finding.get('finding_id')}")
                errors.extend(_schema_issue_messages("Finding", issues))
    except (OSError, ValueError, SchemaContractError) as exc:
        errors.append(f"schema contract check failed: {exc}")

    passed = not errors
    return CheckResult(
        "contracts.schemas",
        passed,
        0,
        0,
        "JSON Schemas, Skill metadata and runtime artifacts agree" if passed else "Schema contracts are incomplete or stale",
        {
            "registry": registry_path.relative_to(root).as_posix(),
            "skill_contracts": skill_contracts,
            "validated_examples": validated_examples,
            "errors": errors,
        },
    )


def _skill_contract_metadata(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    metadata: dict[str, str] = {}
    for line in text[4:end].splitlines():
        match = re.match(r"^\s{2}(input_schema|output_schema|dependency|dependency_version|timeout_seconds):\s*(.+?)\s*$", line)
        if match:
            metadata[match.group(1)] = match.group(2).strip('"\'')
    interface = path.parent / "agents" / "openai.yaml"
    if interface.is_file():
        for line in interface.read_text(encoding="utf-8").splitlines():
            match = re.match(
                r"^\s{2}(input_schema|output_schema|dependency|dependency_version|timeout_seconds):\s*(.+?)\s*$",
                line,
            )
            if match:
                metadata.setdefault(match.group(1), match.group(2).strip('"\''))
    return metadata


def _schema_issue_messages(label: str, issues: list[Any]) -> list[str]:
    return [f"{label} {issue.instance_path}: {issue.message}" for issue in issues]


def _gateway_security_check() -> CheckResult:
    local_allowed = True
    remote_denied = False
    remote_with_token_allowed = True
    try:
        validate_gateway_security("127.0.0.1", None)
    except ValueError:
        local_allowed = False
    try:
        validate_gateway_security("0.0.0.0", None)
    except ValueError:
        remote_denied = True
    try:
        validate_gateway_security("0.0.0.0", "benchmark-token")
    except ValueError:
        remote_with_token_allowed = False
    passed = local_allowed and remote_denied and remote_with_token_allowed
    return CheckResult(
        "gateway.security",
        passed,
        10,
        10 if passed else 0,
        "Gateway fails closed for unauthenticated non-loopback binding" if passed else "Gateway binding policy is unsafe",
        {
            "local_without_token_allowed": local_allowed,
            "remote_without_token_denied": remote_denied,
            "remote_with_token_allowed": remote_with_token_allowed,
        },
    )


def _gateway_contract_check(root: Path) -> CheckResult:
    replayed = False
    conflict_denied = False
    one_execution = False
    hashes_present = False
    with tempfile.TemporaryDirectory(prefix="sceneguard-gateway-contract-") as directory:
        service = GatewayService(root / "samples", root / "profiles", directory)
        payload = {
            "asset": "clean_triangle.glb",
            "profile": "web-realtime-v0.2.json",
            "job_id": "benchmark-idempotent",
        }
        first = service.run_pipeline_request(
            payload,
            request_id="benchmark-request-1",
            idempotency_key="benchmark-idempotency-key",
        )
        replay = service.run_pipeline_request(
            payload,
            request_id="benchmark-request-2",
            idempotency_key="benchmark-idempotency-key",
        )
        replayed = bool(replay["meta"]["replayed"] and first["result"] == replay["result"])
        hashes_present = all(
            isinstance(first["meta"].get(name), str) and len(first["meta"][name]) == 64
            for name in ("input_sha256", "output_sha256")
        )
        trace = Path(directory) / "benchmark-idempotent" / "artifacts" / "trace.jsonl"
        one_execution = trace.read_text(encoding="utf-8").count("gateway.request.accepted") == 1
        try:
            service.run_pipeline_request(
                {**payload, "asset": "degenerate_triangle.glb"},
                request_id="benchmark-request-3",
                idempotency_key="benchmark-idempotency-key",
            )
        except GatewayError as exc:
            conflict_denied = exc.code == "IDEMPOTENCY_CONFLICT"
    passed = replayed and conflict_denied and one_execution and hashes_present
    return CheckResult(
        "gateway.request_contract",
        passed,
        5,
        5 if passed else 0,
        "Request hashes and persistent idempotency contract passed" if passed else "Gateway request contract failed",
        {
            "same_key_same_input_replayed": replayed,
            "same_key_different_input_denied": conflict_denied,
            "pipeline_executed_once": one_execution,
            "input_output_hashes_present": hashes_present,
        },
    )


def _api_contract_check(root: Path, config: dict[str, Any]) -> CheckResult:
    contract_path = _inside(root, config.get("api_contract", "at/http_api.v0.1.json"))
    errors: list[str] = []
    route_details: dict[str, bool] = {}
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
        routes = payload.get("routes")
        if not isinstance(routes, list):
            routes = []
            errors.append("routes must be an array")
        actual: list[tuple[str, str]] = []
        store = SchemaStore(root / "schemas")
        for index, item in enumerate(routes):
            if not isinstance(item, dict):
                errors.append(f"routes[{index}] must be an object")
                continue
            method = item.get("method")
            path = item.get("path")
            if not isinstance(method, str) or not isinstance(path, str):
                errors.append(f"routes[{index}] needs method and path")
                continue
            pair = (method, path)
            actual.append(pair)
            auth_valid = item.get("auth") == ("public" if path == "/health" else "bearer_if_configured")
            description_valid = bool(str(item.get("function", "")).strip()) and bool(
                str(item.get("future_mcp", "")).strip()
            )
            schema_valid = True
            if item.get("input_schema") is not None:
                try:
                    schema_path = _inside(root, item["input_schema"])
                    store.load(schema_path)
                except (OSError, TypeError, ValueError, SchemaContractError):
                    schema_valid = False
            route_details[f"{method} {path}"] = auth_valid and description_valid and schema_valid
        expected = set(HTTP_API_ROUTES)
        if set(actual) != expected or len(actual) != len(set(actual)):
            errors.append("machine API routes do not exactly match the implemented route registry")
        if not all(route_details.values()) or len(route_details) != len(expected):
            errors.append("one or more route metadata entries are incomplete")
        pipeline = next((item for item in routes if item.get("path") == "/v1/pipeline/run"), {})
        if pipeline.get("idempotency_key_supported") is not True:
            errors.append("pipeline route must declare Idempotency-Key support")
        limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
        if limits.get("request_body_bytes") != MAX_REQUEST_BYTES:
            errors.append("request body limit is stale")
        if limits.get("artifact_read_bytes") != MAX_ARTIFACT_BYTES:
            errors.append("artifact read limit is stale")
        if limits.get("hard_execution_timeout_implemented") is not False:
            errors.append("hard timeout capability must remain honestly disclosed as false")
        mapping = (root / "at" / "TOOL_MAPPING.md").read_text(encoding="utf-8")
        missing_docs = [f"{method} {path}" for method, path in expected if path not in mapping]
        if missing_docs:
            errors.append("TOOL_MAPPING is missing routes: " + ", ".join(sorted(missing_docs)))
    except (OSError, ValueError) as exc:
        payload = {}
        errors.append(f"invalid API contract: {exc}")
    passed = not errors
    return CheckResult(
        "contracts.api_docs",
        passed,
        0,
        0,
        "HTTP route registry, schemas, limits and MCP mapping agree" if passed else "HTTP API contract is stale",
        {
            "contract_id": payload.get("contract_id"),
            "route_count": len(payload.get("routes", [])) if isinstance(payload.get("routes"), list) else 0,
            "route_details": route_details,
            "errors": errors,
        },
    )


def _contract_sync_check(root: Path, config: dict[str, Any]) -> CheckResult:
    team_spec = json.loads((root / "at" / "team_spec.json").read_text(encoding="utf-8"))
    profile_operations: set[str] = set()
    for profile_path in sorted((root / "profiles").glob("*.json")):
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile_operations.update(profile.get("repair_policy", {}).get("allowed_operations", []))
    team_operations = set(team_spec.get("risk_policy", {}).get("current_repair_whitelist", []))
    executor = next((item for item in team_spec.get("agents", []) if item.get("id") == "repair_executor"), {})
    executor_enabled = executor.get("status") != "disabled until repair whitelist passes technical spike"
    readme = (root / "README.md").read_text(encoding="utf-8")
    readme_current = (
        "退化三角形最小索引修改" in readme
        and "内嵌纹理等比缩放" in readme
        and "REPAIRED_PASS" in readme
        and "FAILED_ROLLBACK" in readme
        and "尚未实现：自动修复" not in readme
    )
    passed = profile_operations == team_operations and bool(profile_operations) and executor_enabled and readme_current
    return CheckResult(
        "contracts.material_sync",
        passed,
        5,
        5 if passed else 0,
        "runtime contracts and README match implemented repair policy" if passed else "runtime contracts or README are stale",
        {
            "profile_operations": sorted(profile_operations),
            "team_operations": sorted(team_operations),
            "executor_enabled": executor_enabled,
            "readme_current": readme_current,
        },
    )


def _submission_manifest_check(root: Path, config: dict[str, Any]) -> CheckResult:
    manifest_path = Path(config.get("submission_manifest", "reports/submission-manifest.json"))
    if not (root / manifest_path).is_file() and (root / "SUBMISSION_MANIFEST.json").is_file():
        manifest_path = Path("SUBMISSION_MANIFEST.json")
    result = verify_submission_manifest(root, manifest_path)
    passed = bool(result["passed"])
    return CheckResult(
        "submission.manifest",
        passed,
        5,
        5 if passed else 0,
        "Submission file hashes and scope are current" if passed else "Submission manifest is missing or stale",
        result,
    )


def _requirements_registry_check(
    root: Path,
    config: dict[str, Any],
    checks: list[CheckResult],
) -> tuple[CheckResult, dict[str, Any]]:
    path = _inside(root, config.get("requirements_registry", "benchmark/requirements.v0.1.json"))
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        payload = {"requirements": []}
        errors.append(f"invalid registry JSON: {exc}")
    requirements = payload.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        errors.append("requirements must be a non-empty list")
        requirements = []
    known_checks = {item.check_id for item in checks} | {"tests.regression"}
    known_external = set(config.get("required_release_evidence", []))
    ids: set[str] = set()
    for index, item in enumerate(requirements):
        prefix = f"requirements[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} must be an object")
            continue
        requirement_id = item.get("id")
        if not isinstance(requirement_id, str) or not requirement_id:
            errors.append(f"{prefix}.id is required")
        elif requirement_id in ids:
            errors.append(f"duplicate requirement id: {requirement_id}")
        else:
            ids.add(requirement_id)
        if item.get("stage") not in {"core", "release"}:
            errors.append(f"{prefix}.stage must be core or release")
        check_refs = item.get("benchmark_checks", [])
        file_refs = item.get("file_refs", [])
        external_refs = item.get("external_evidence", [])
        if not any((check_refs, file_refs, external_refs)):
            errors.append(f"{prefix} has no evidence binding")
        if not isinstance(check_refs, list) or any(ref not in known_checks for ref in check_refs):
            errors.append(f"{prefix}.benchmark_checks contains an unknown check")
        if not isinstance(external_refs, list) or any(ref not in known_external for ref in external_refs):
            errors.append(f"{prefix}.external_evidence contains an unknown release evidence id")
        if not isinstance(file_refs, list):
            errors.append(f"{prefix}.file_refs must be a list")
        else:
            for reference in file_refs:
                try:
                    candidate = _inside(root, reference)
                except (TypeError, ValueError):
                    errors.append(f"{prefix}.file_refs contains an unsafe path")
                    continue
                if not candidate.is_file():
                    errors.append(f"{prefix}.file_refs is missing: {reference}")
    passed = not errors
    result = CheckResult(
        "requirements.registry",
        passed,
        0,
        0,
        "Formal requirements are traceable to executable evidence" if passed else "Requirements registry is invalid",
        {"registry_id": payload.get("registry_id"), "requirement_count": len(requirements), "errors": errors},
    )
    return result, payload


def _compile_requirement_coverage(
    root: Path,
    registry: dict[str, Any],
    checks: list[CheckResult],
    external: dict[str, Any],
) -> dict[str, Any]:
    check_status = {item.check_id: item.passed for item in checks}
    external_status = external.get("evidence_paths", {})
    items: list[dict[str, Any]] = []
    for requirement in registry.get("requirements", []):
        check_refs = requirement.get("benchmark_checks", [])
        file_refs = requirement.get("file_refs", [])
        external_refs = requirement.get("external_evidence", [])
        checks_passed = all(check_status.get(reference) is not False for reference in check_refs)
        files_passed = all((root / reference).resolve().is_relative_to(root) and (root / reference).is_file() for reference in file_refs)
        external_passed = all(bool(external_status.get(reference, {}).get("valid")) for reference in external_refs)
        passed = checks_passed and files_passed and external_passed
        items.append(
            {
                "id": requirement.get("id"),
                "title": requirement.get("title"),
                "stage": requirement.get("stage"),
                "passed": passed,
                "benchmark_checks": {reference: check_status.get(reference) for reference in check_refs},
                "file_refs": {reference: (root / reference).is_file() for reference in file_refs},
                "external_evidence": {
                    reference: bool(external_status.get(reference, {}).get("valid")) for reference in external_refs
                },
            }
        )
    summary: dict[str, Any] = {"registry_id": registry.get("registry_id"), "items": items}
    for stage in ("core", "release"):
        stage_items = [item for item in items if item["stage"] == stage]
        summary[stage] = {
            "passed": bool(stage_items) and all(item["passed"] for item in stage_items),
            "passed_count": sum(item["passed"] for item in stage_items),
            "total_count": len(stage_items),
            "failed_ids": [item["id"] for item in stage_items if not item["passed"]],
        }
    return summary


def _external_evidence(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for item in config["required_release_evidence"]:
        path = root / item
        validation = _validate_release_evidence(path, item, root)
        paths[item] = validation
    docker_available = find_docker_executable() is not None
    missing = [name for name, validation in paths.items() if not validation["valid"]]
    agentteams_path = "evidence/agentteams/runtime.json"
    if agentteams_path in missing and not docker_available:
        missing.append("docker runtime or externally captured AgentTeams runtime evidence")
    return {
        "passed": not missing,
        "docker_available": docker_available,
        "evidence_paths": paths,
        "missing": missing,
    }


def _validate_release_evidence(
    path: Path,
    evidence_id: str,
    project_root: Path | None = None,
) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False, "valid": False, "reason": "file missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"present": True, "valid": False, "reason": f"invalid JSON: {exc}"}
    root = project_root.resolve() if project_root is not None else path.resolve().parent
    ref_validation = _validate_evidence_refs(payload.get("trace_refs"), root)
    secret_scan = _scan_release_evidence(path, payload.get("trace_refs"), root)
    confirmed_by = payload.get("confirmed_by")
    placeholder_paths = _placeholder_paths(payload)
    if evidence_id.endswith("agentteams/runtime.json"):
        workers = payload.get("workers")
        worker_names = workers if _nonempty_string_list(workers) else []
        host = payload.get("host") if isinstance(payload.get("host"), dict) else {}
        gateway = payload.get("gateway") if isinstance(payload.get("gateway"), dict) else {}
        cases = payload.get("cases") if isinstance(payload.get("cases"), dict) else {}
        clean_case = cases.get("clean") if isinstance(cases.get("clean"), dict) else {}
        repair_case = cases.get("repair") if isinstance(cases.get("repair"), dict) else {}
        trace_refs = payload.get("trace_refs") if isinstance(payload.get("trace_refs"), list) else []
        required = {
            "status": payload.get("status") == "PASS",
            "no_placeholders": not placeholder_paths,
            "framework": "agentteams" in str(payload.get("framework", "")).lower()
            or "hiclaw" in str(payload.get("framework", "")).lower(),
            "framework_version": bool(payload.get("framework_version")),
            "observed_at": _valid_datetime(payload.get("observed_at")),
            "host": bool(str(host.get("os", "")).strip())
            and bool(str(host.get("cpu", "")).strip())
            and isinstance(host.get("memory_gb"), (int, float))
            and not isinstance(host.get("memory_gb"), bool)
            and host["memory_gb"] > 0
            and bool(str(host.get("docker_version", "")).strip()),
            "worker_runtime": bool(str(payload.get("worker_runtime", "")).strip()),
            "model": bool(str(payload.get("model_provider", "")).strip())
            and bool(str(payload.get("model_name", "")).strip()),
            "worker_count": isinstance(payload.get("worker_count"), int)
            and payload["worker_count"] >= 4
            and payload["worker_count"] == len(set(worker_names)),
            "workers": len(worker_names) >= 4 and len(worker_names) == len(set(worker_names)),
            "team_leader": bool(payload.get("team_leader")),
            "gateway": gateway.get("health_http_status") == 200
            and bool(str(gateway.get("reachable_url_redacted", "")).strip()),
            "clean_case": clean_case.get("gate_state") == "PASS"
            and bool(clean_case.get("job_id"))
            and clean_case.get("trace_ref") in trace_refs,
            "repair_case": repair_case.get("gate_state") == "REPAIRED_PASS"
            and bool(repair_case.get("job_id"))
            and repair_case.get("trace_ref") in trace_refs,
            "trace_refs": ref_validation["valid"],
            "secret_scan_passed": payload.get("secret_scan_passed") is True,
            "secret_scan_verified": secret_scan["passed"],
            "confirmed_by": _nonempty_string_list(confirmed_by),
        }
    elif evidence_id.endswith("agentteams/five-agent-supervisor-20260901.json"):
        trace_refs = payload.get("trace_refs") if isinstance(payload.get("trace_refs"), list) else []
        run_ref = str(payload.get("run_result_ref", ""))
        stability_ref = str(payload.get("stability_report_ref", ""))
        run_path = (root / run_ref).resolve()
        stability_path = (root / stability_ref).resolve()
        run_payload: dict[str, Any] = {}
        stability_payload: dict[str, Any] = {}
        refs_safe = (
            bool(run_ref)
            and bool(stability_ref)
            and run_path.is_relative_to(root)
            and stability_path.is_relative_to(root)
            and run_path.is_file()
            and stability_path.is_file()
        )
        if refs_safe:
            try:
                run_payload = json.loads(run_path.read_text(encoding="utf-8"))
                stability_payload = json.loads(stability_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                refs_safe = False
        run_hash = hashlib.sha256(run_path.read_bytes()).hexdigest() if refs_safe else ""
        stability_hash = hashlib.sha256(stability_path.read_bytes()).hexdigest() if refs_safe else ""
        required = {
            "status": payload.get("status") == "PASS",
            "no_placeholders": not placeholder_paths,
            "observed_at": _valid_datetime(payload.get("observed_at")),
            "mode": "five-agent" in str(payload.get("mode", "")).lower(),
            "five_agents": payload.get("agent_count") == 5,
            "four_workers": payload.get("worker_count") == 4,
            "zero_operator_actions": payload.get("operator_actions_after_dispatch") == 0,
            "repaired_pass": payload.get("gate_state") == "REPAIRED_PASS",
            "four_tasks": isinstance(payload.get("task_ids"), list)
            and len(set(payload["task_ids"])) == 4,
            "necessary_l1_skills": isinstance(payload.get("skill_ids"), list)
            and len(set(payload["skill_ids"])) == 6,
            "cross_report_invariants": payload.get("cross_report_invariants_passed") is True,
            "bound_refs": refs_safe,
            "run_result_hash": refs_safe
            and run_hash == payload.get("run_result_sha256")
            and run_payload.get("status") == "COMPLETED"
            and run_payload.get("operator_actions_after_dispatch") == 0
            and run_payload.get("invariants", {}).get("passed") is True,
            "stability_report_hash": refs_safe
            and stability_hash == payload.get("stability_report_sha256")
            and stability_payload.get("status") == "PASS"
            and stability_payload.get("sample_count", 0) >= 5
            and stability_payload.get("passed_count") == stability_payload.get("sample_count")
            and stability_payload.get("success_rate") == 1.0,
            "trace_refs": ref_validation["valid"] and len(trace_refs) >= 12,
            "secret_scan_passed": payload.get("secret_scan_passed") is True,
            "secret_scan_verified": secret_scan["passed"],
        }
    elif evidence_id.endswith("official-skill/integration.json"):
        official_url = str(payload.get("official_source_url", ""))
        parsed_source = urlparse(official_url)
        quickstart_url = urlparse(str(payload.get("official_quickstart_url", "")))
        successful_call = payload.get("successful_call") if isinstance(payload.get("successful_call"), dict) else {}
        failure_case = payload.get("failure_case") if isinstance(payload.get("failure_case"), dict) else {}
        trace_refs = payload.get("trace_refs") if isinstance(payload.get("trace_refs"), list) else []
        required = {
            "status": payload.get("status") == "PASS",
            "no_placeholders": not placeholder_paths,
            "skill_name": bool(payload.get("skill_name")),
            "skill_version": bool(payload.get("skill_version")),
            "official_source_url": parsed_source.scheme == "https"
            and parsed_source.hostname in {"skills.aliyun.com", "help.aliyun.com"},
            "official_quickstart_url": quickstart_url.scheme == "https" and quickstart_url.hostname == "help.aliyun.com",
            "observed_at": _valid_datetime(payload.get("observed_at")),
            "auth_mode": bool(payload.get("auth_mode")),
            "necessity": bool(str(payload.get("necessity_in_sceneguard", "")).strip()),
            "successful_call": bool(successful_call.get("operation"))
            and bool(successful_call.get("sanitized_result_summary"))
            and successful_call.get("trace_ref") in trace_refs,
            "failure_tested": payload.get("failure_tested") is True,
            "failure_case": bool(failure_case.get("mode"))
            and bool(failure_case.get("observed_error_code"))
            and bool(failure_case.get("fallback"))
            and failure_case.get("trace_ref") in trace_refs,
            "replacement_strategy": bool(payload.get("replacement_strategy")),
            "trace_refs": ref_validation["valid"],
            "secret_scan_passed": payload.get("secret_scan_passed") is True,
            "secret_scan_verified": secret_scan["passed"],
            "confirmed_by": _nonempty_string_list(confirmed_by),
        }
    elif evidence_id.endswith("team/release-decisions.json"):
        members = payload.get("members_confirmed")
        member_names = members if _nonempty_string_list(members) else []
        license_spdx = str(payload.get("license_spdx", ""))
        license_path = root / str(payload.get("license_file", "LICENSE"))
        required = {
            "status": payload.get("status") == "PASS",
            "no_placeholders": not placeholder_paths,
            "project_name": bool(str(payload.get("project_name", "")).strip()),
            "project_name_confirmed": payload.get("project_name_confirmed") is True,
            "license_spdx": re.fullmatch(r"[A-Za-z0-9.+-]+", license_spdx) is not None,
            "license_file": license_path.resolve().is_relative_to(root) and license_path.is_file(),
            "members_confirmed": len(set(member_names)) >= 3,
            "roles_confirmed": payload.get("roles_confirmed") is True,
            "public_bios_authorized": payload.get("public_bios_authorized") is True,
            "public_asset_license_reviewed": payload.get("public_asset_license_reviewed") is True,
            "confirmed_at": _valid_datetime(payload.get("confirmed_at")),
            "confirmed_by": _nonempty_string_list(confirmed_by)
            and len(set(confirmed_by)) >= 3
            and set(confirmed_by) == set(member_names),
        }
        ref_validation = {"valid": True, "checked": 0, "missing": [], "invalid": []}
    else:
        required = {"status": payload.get("status") == "PASS", "trace_refs": bool(payload.get("trace_refs"))}
    failed_fields = sorted(name for name, valid in required.items() if not valid)
    return {
        "present": True,
        "valid": not failed_fields,
        "reason": "valid" if not failed_fields else "missing or invalid fields: " + ", ".join(failed_fields),
        "trace_ref_validation": ref_validation,
        "secret_scan": secret_scan,
        "placeholder_paths": placeholder_paths,
    }


def _validate_evidence_refs(value: Any, project_root: Path) -> dict[str, Any]:
    if not _nonempty_string_list(value):
        return {"valid": False, "checked": 0, "missing": [], "invalid": ["trace_refs must be non-empty strings"]}
    evidence_root = (project_root / "evidence").resolve()
    missing: list[str] = []
    invalid: list[str] = []
    for reference in value:
        relative = Path(reference)
        candidate = (project_root / relative).resolve()
        if relative.is_absolute() or not candidate.is_relative_to(evidence_root):
            invalid.append(reference)
            continue
        if candidate.suffix.lower() not in TEXT_EVIDENCE_SUFFIXES:
            invalid.append(reference)
            continue
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            missing.append(reference)
    return {
        "valid": not missing and not invalid,
        "checked": len(value),
        "missing": sorted(missing),
        "invalid": sorted(invalid),
    }


def _scan_release_evidence(path: Path, trace_refs: Any, project_root: Path) -> dict[str, Any]:
    """Fail closed on common credentials and personal host paths in retained text evidence."""
    targets: list[tuple[str, Path]] = [(path.name, path)]
    if isinstance(trace_refs, list):
        for reference in trace_refs:
            if not isinstance(reference, str) or not reference:
                continue
            relative = Path(reference)
            candidate = (project_root / relative).resolve()
            if relative.is_absolute() or not candidate.is_relative_to((project_root / "evidence").resolve()):
                continue
            if candidate.is_file():
                targets.append((reference, candidate))

    findings: list[dict[str, str]] = []
    scanned: list[str] = []
    seen: set[Path] = set()
    for display, target in targets:
        resolved = target.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if target.suffix.lower() not in TEXT_EVIDENCE_SUFFIXES:
            findings.append({"path": display, "kind": "unsupported_non_text_evidence"})
            continue
        if target.stat().st_size > MAX_EVIDENCE_TEXT_BYTES:
            findings.append({"path": display, "kind": "evidence_file_too_large_to_scan"})
            continue
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.append({"path": display, "kind": "evidence_not_utf8_text"})
            continue
        scanned.append(display)
        for kind, pattern in EVIDENCE_SECRET_PATTERNS.items():
            if pattern.search(content):
                findings.append({"path": display, "kind": kind})

    return {
        "passed": not findings,
        "scanned": sorted(scanned),
        "findings": sorted(findings, key=lambda item: (item["path"], item["kind"])),
    }


def _nonempty_string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and bool(item.strip()) for item in value)


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _placeholder_paths(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(_placeholder_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_placeholder_paths(child, f"{path}[{index}]"))
    elif isinstance(value, str) and re.search(r"(?:^|[^A-Z0-9])(?:TODO|TBD|PLACEHOLDER|REPLACE_ME)(?:[^A-Z0-9]|$)", value.upper()):
        found.append(path)
    return found


def _next_actions(checks: list[CheckResult], external: dict[str, Any]) -> list[dict[str, str]]:
    actions = [
        {"type": "CORE_GAP", "check_id": item.check_id, "action": item.summary}
        for item in checks
        if not item.passed
    ]
    actions.extend(
        {"type": "EXTERNAL_BLOCKER", "check_id": "release.external", "action": f"provide {item}"}
        for item in external["missing"]
    )
    return actions


def _run(command: list[str], cwd: Path) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    output = (completed.stdout + "\n" + completed.stderr).splitlines()
    return {
        "command": command,
        "exit_code": completed.returncode,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "tail": output[-20:],
    }


def _inside(root: Path, value: str | Path) -> Path:
    candidate = (root / value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"path escapes benchmark root: {value}")
    return candidate
