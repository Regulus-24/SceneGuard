from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .audit import audit_asset
from .profile import QualityProfile


@dataclass(frozen=True)
class JobWorkspace:
    job_id: str
    root: Path
    original: Path
    working: Path
    artifacts: Path
    checkpoints: Path
    published: Path
    audit_report: Path
    trace: Path


CHECKPOINT_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_job_workspace(
    source: str | Path,
    jobs_root: str | Path,
    profile: QualityProfile,
    job_id: str | None = None,
) -> tuple[JobWorkspace, dict]:
    source_path = Path(source).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path.suffix.lower() != ".glb":
        raise ValueError("SceneGuard MVP only accepts .glb files")

    actual_job_id = job_id or f"job-{uuid4().hex[:12]}"
    if not isinstance(actual_job_id, str) or JOB_ID_PATTERN.fullmatch(actual_job_id) is None:
        raise ValueError("job id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}")

    jobs_base = Path(jobs_root).resolve()
    root = (jobs_base / actual_job_id).resolve()
    if not root.is_relative_to(jobs_base):
        raise ValueError("job workspace must remain inside jobs root")
    if root.exists():
        raise FileExistsError(f"job workspace already exists: {root}")

    original_dir = root / "original"
    working_dir = root / "working"
    artifacts = root / "artifacts"
    checkpoints = root / "checkpoints"
    published = root / "published"
    for directory in (original_dir, working_dir, artifacts, checkpoints, published):
        directory.mkdir(parents=True, exist_ok=False)

    original = original_dir / "asset.glb"
    working = working_dir / "candidate.glb"
    shutil.copy2(source_path, original)
    shutil.copy2(source_path, working)
    original.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)

    original_hash = sha256_file(original)
    working_hash = sha256_file(working)
    manifest = {
        "schema_version": "0.1",
        "job_id": actual_job_id,
        "trace_id": trace_id_for_job(actual_job_id),
        "source_name": source_path.name,
        "profile": f"{profile.profile_id}@{profile.version}",
        "original": {"path": "original/asset.glb", "sha256": original_hash, "read_only": True},
        "working": {"path": "working/candidate.glb", "sha256": working_hash},
        "created_at": datetime.now(UTC).isoformat(),
    }
    (root / "job_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    trace = artifacts / "trace.jsonl"
    append_trace(
        trace,
        event="job.created",
        job_id=actual_job_id,
        details={"original_sha256": original_hash, "working_sha256": working_hash},
    )
    report = audit_asset(working, profile, job_id=actual_job_id)
    audit_report = artifacts / "audit_report.json"
    audit_report.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    append_trace(
        trace,
        event="audit.completed",
        job_id=actual_job_id,
        details={
            "gate_state": report.gate_state.value,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "report": "artifacts/audit_report.json",
        },
    )

    workspace = JobWorkspace(
        job_id=actual_job_id,
        root=root,
        original=original,
        working=working,
        artifacts=artifacts,
        checkpoints=checkpoints,
        published=published,
        audit_report=audit_report,
        trace=trace,
    )
    return workspace, report.to_dict()


def load_job_workspace(jobs_root: str | Path, job_id: str) -> JobWorkspace:
    """Load an existing job without recreating or mutating its workspace."""
    if not isinstance(job_id, str) or JOB_ID_PATTERN.fullmatch(job_id) is None:
        raise ValueError("job id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}")
    jobs_base = Path(jobs_root).resolve()
    root = (jobs_base / job_id).resolve()
    if not root.is_relative_to(jobs_base):
        raise ValueError("job workspace must remain inside jobs root")
    paths = {
        "original": root / "original" / "asset.glb",
        "working": root / "working" / "candidate.glb",
        "artifacts": root / "artifacts",
        "checkpoints": root / "checkpoints",
        "published": root / "published",
        "audit_report": root / "artifacts" / "audit_report.json",
        "trace": root / "artifacts" / "trace.jsonl",
    }
    required = ("original", "working", "artifacts", "checkpoints", "published", "audit_report", "trace")
    if not root.is_dir() or any(not paths[name].exists() for name in required):
        raise FileNotFoundError(f"job workspace is incomplete or missing: {job_id}")
    return JobWorkspace(job_id=job_id, root=root, **paths)


def create_checkpoint(
    workspace: JobWorkspace,
    label: str,
    expected_working_hash: str | None = None,
) -> dict:
    _validate_checkpoint_label(label)
    current_hash = sha256_file(workspace.working)
    if expected_working_hash is not None and current_hash != expected_working_hash:
        raise ValueError("working copy hash does not match the expected Patch Plan hash")
    checkpoint = workspace.checkpoints / f"{label}.glb"
    metadata = workspace.checkpoints / f"{label}.json"
    if checkpoint.exists() or metadata.exists():
        raise FileExistsError(f"checkpoint already exists: {label}")
    shutil.copy2(workspace.working, checkpoint)
    payload = {
        "schema_version": "0.1",
        "job_id": workspace.job_id,
        "label": label,
        "path": f"checkpoints/{label}.glb",
        "sha256": current_hash,
        "created_at": datetime.now(UTC).isoformat(),
    }
    metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_trace(
        workspace.trace,
        event="checkpoint.created",
        job_id=workspace.job_id,
        details={"label": label, "sha256": current_hash},
    )
    return payload


def rollback_to_checkpoint(
    workspace: JobWorkspace,
    label: str,
    expected_checkpoint_hash: str | None = None,
) -> dict:
    _validate_checkpoint_label(label)
    checkpoint = workspace.checkpoints / f"{label}.glb"
    if not checkpoint.is_file():
        raise FileNotFoundError(f"checkpoint not found: {label}")
    checkpoint_hash = sha256_file(checkpoint)
    if expected_checkpoint_hash is not None and checkpoint_hash != expected_checkpoint_hash:
        raise ValueError("checkpoint hash does not match the expected rollback hash")

    before_hash = sha256_file(workspace.working)
    temporary = workspace.working.with_suffix(".rollback.tmp")
    shutil.copy2(checkpoint, temporary)
    if sha256_file(temporary) != checkpoint_hash:
        temporary.unlink(missing_ok=True)
        raise OSError("rollback temporary copy failed hash verification")
    os.replace(temporary, workspace.working)
    after_hash = sha256_file(workspace.working)
    if after_hash != checkpoint_hash:
        raise OSError("working copy does not match checkpoint after atomic replace")
    payload = {
        "schema_version": "0.1",
        "job_id": workspace.job_id,
        "checkpoint": label,
        "before_sha256": before_hash,
        "after_sha256": after_hash,
        "checkpoint_sha256": checkpoint_hash,
        "success": True,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    rollback_report = workspace.artifacts / f"rollback-{label}.json"
    rollback_report.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_trace(
        workspace.trace,
        event="rollback.completed",
        job_id=workspace.job_id,
        details={
            "label": label,
            "before_sha256": before_hash,
            "after_sha256": after_hash,
            "report": f"artifacts/{rollback_report.name}",
        },
    )
    return payload


def publish_candidate(
    workspace: JobWorkspace,
    gate_state: str,
    profile: QualityProfile,
    regression_report: str | None = None,
) -> dict:
    if gate_state not in {"PASS", "REPAIRED_PASS"}:
        raise ValueError("only PASS or REPAIRED_PASS candidates may be published")
    candidate_hash = sha256_file(workspace.working)
    target = workspace.published / "asset.glb"
    temporary = workspace.published / "asset.publish.tmp"
    shutil.copy2(workspace.working, temporary)
    if sha256_file(temporary) != candidate_hash:
        temporary.unlink(missing_ok=True)
        raise OSError("publish temporary copy failed hash verification")
    os.replace(temporary, target)
    payload = {
        "schema_version": "0.1",
        "job_id": workspace.job_id,
        "gate_state": gate_state,
        "profile": f"{profile.profile_id}@{profile.version}",
        "original_sha256": sha256_file(workspace.original),
        "published_sha256": candidate_hash,
        "published_path": "published/asset.glb",
        "regression_report": regression_report,
        "published_at": datetime.now(UTC).isoformat(),
    }
    attestation = workspace.artifacts / "release_attestation.json"
    attestation.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_trace(
        workspace.trace,
        event="release.published",
        job_id=workspace.job_id,
        details={
            "gate_state": gate_state,
            "published_sha256": candidate_hash,
            "attestation": "artifacts/release_attestation.json",
        },
    )
    return payload


def _validate_checkpoint_label(label: str) -> None:
    if not isinstance(label, str) or CHECKPOINT_LABEL.fullmatch(label) is None:
        raise ValueError("checkpoint label must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def append_trace(path: Path, event: str, job_id: str, details: dict) -> None:
    payload = {
        "schema_version": "0.1",
        "timestamp": datetime.now(UTC).isoformat(),
        "trace_id": trace_id_for_job(job_id),
        "job_id": job_id,
        "event": event,
        "details": details,
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")


def trace_id_for_job(job_id: str) -> str:
    """Return one stable correlation id for every event emitted by a Job."""
    return "trace-" + hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:16]
