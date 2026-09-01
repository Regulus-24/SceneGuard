from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .audit import audit_asset
from .evaluation import run_golden_evaluation
from .gateway import run_gateway
from .pipeline import run_job
from .profile import QualityProfile
from .workspace import create_job_workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sceneguard", description="SceneGuard deterministic GLB quality gate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="audit one GLB without modifying it")
    audit.add_argument("asset", type=Path)
    audit.add_argument("--profile", required=True, type=Path)
    audit.add_argument("--output", type=Path)
    audit.add_argument("--job-id", default="standalone")

    init_job = subparsers.add_parser("init-job", help="create an isolated job workspace and run the first audit")
    init_job.add_argument("asset", type=Path)
    init_job.add_argument("--profile", required=True, type=Path)
    init_job.add_argument("--jobs-root", default=Path("jobs"), type=Path)
    init_job.add_argument("--job-id")

    pipeline = subparsers.add_parser("run-job", help="run audit, safe repair, regression, and publish/rollback")
    pipeline.add_argument("asset", type=Path)
    pipeline.add_argument("--profile", required=True, type=Path)
    pipeline.add_argument("--jobs-root", default=Path("jobs"), type=Path)
    pipeline.add_argument("--job-id")
    pipeline.add_argument("--no-auto-repair", action="store_true")
    pipeline.add_argument(
        "--fault-injection",
        choices=["tamper_before_execute", "tool_error_after_execute", "corrupt_after_execute"],
    )
    pipeline.add_argument("--approval-decision", choices=["APPROVE", "REJECT"])
    pipeline.add_argument("--approval-actor", default="cli-user")

    serve = subparsers.add_parser("serve", help="run the local HTTP JSON Tool Gateway")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=18091, type=int)
    serve.add_argument("--asset-root", default=Path("samples"), type=Path)
    serve.add_argument("--profile-root", default=Path("profiles"), type=Path)
    serve.add_argument("--jobs-root", default=Path("jobs"), type=Path)
    serve.add_argument(
        "--api-token-env",
        default="SCENEGUARD_API_TOKEN",
        help="environment variable containing the optional Gateway Bearer token",
    )

    evaluate = subparsers.add_parser("evaluate", help="run the deterministic Golden sample evaluation")
    evaluate.add_argument("--manifest", default=Path("evaluation/golden_findings.json"), type=Path)
    evaluate.add_argument("--asset-root", default=Path("samples"), type=Path)
    evaluate.add_argument("--profile", required=True, type=Path)
    evaluate.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "serve":
        run_gateway(
            host=args.host,
            port=args.port,
            asset_root=args.asset_root,
            profile_root=args.profile_root,
            jobs_root=args.jobs_root,
            api_token=os.environ.get(args.api_token_env),
        )
        return 0

    if args.command == "evaluate":
        result = run_golden_evaluation(args.manifest, args.asset_root, args.profile)
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        metrics = result["metrics"]
        return 0 if (
            metrics["sample_gate_accuracy"] == 1.0
            and metrics["expected_rule_recall"] == 1.0
            and metrics["unexpected_error_rule_count"] == 0
        ) else 2

    profile = QualityProfile.load(args.profile)

    if args.command == "run-job":
        result = run_job(
            args.asset,
            profile=profile,
            jobs_root=args.jobs_root,
            job_id=args.job_id,
            auto_repair=not args.no_auto_repair,
            fault_injection=args.fault_injection,
            approval_decision=args.approval_decision,
            approval_actor=args.approval_actor,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["gate_state"] in {"PASS", "REPAIRED_PASS"} else 2

    if args.command == "audit":
        report = audit_asset(args.asset, profile, job_id=args.job_id)
        payload = report.to_dict()
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if report.gate_state.value == "PASS" else 2

    workspace, report = create_job_workspace(
        args.asset,
        jobs_root=args.jobs_root,
        profile=profile,
        job_id=args.job_id,
    )
    print(
        json.dumps(
            {
                "job_id": workspace.job_id,
                "workspace": str(workspace.root),
                "audit_report": str(workspace.audit_report),
                "gate_state": report["summary"]["gate_state"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["summary"]["gate_state"] == "PASS" else 2
