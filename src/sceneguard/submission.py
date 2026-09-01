from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io_utils import atomic_write_json


INCLUDED_DIRECTORIES = (
    "agents",
    "at",
    "benchmark",
    "evaluation",
    "evidence",
    "profiles",
    "samples",
    "schemas",
    "scripts",
    "skills",
    "src",
    "submission",
    "tests",
)
INCLUDED_ROOT_FILES = (
    ".gitignore",
    "DATA_SOURCES.md",
    "LICENSE",
    "MODEL_DISCLOSURE.md",
    "NOTICE",
    "README.md",
    "SECURITY.md",
    "SEMIFINAL_ACCEPTANCE_MATRIX.zh-CN.md",
    "SEMIFINAL_SUBMISSION_CHECKLIST.zh-CN.md",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "release-facts.v0.1.json",
    "skills-lock.json",
)
INCLUDED_FIXED_JOB_DIRECTORIES = (
    "jobs/delivery-clean",
    "jobs/delivery-repair",
    "jobs/delivery-rollback",
)
INCLUDED_FIXED_REPORT_FILES = (
    "reports/agentteams-stability-latest.json",
    "reports/public-asset-sync-latest.json",
)
IGNORED_PARTS = {"__pycache__", ".pytest_cache"}
IGNORED_DIRECTORY_SUFFIXES = {".egg-info", ".dist-info"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
SENSITIVE_NAME = re.compile(
    r"(?:^\.env(?:\..+)?$|credential|secret|token|^id_rsa$|\.(?:pem|key|p12|pfx)$)",
    re.IGNORECASE,
)


class SubmissionManifestError(ValueError):
    pass


def build_submission_manifest(root: str | Path) -> dict[str, Any]:
    project_root = Path(root).resolve()
    paths = _discover_deliverables(project_root)
    sensitive = [path.relative_to(project_root).as_posix() for path in paths if SENSITIVE_NAME.search(path.name)]
    if sensitive:
        raise SubmissionManifestError("sensitive-looking files must not be packaged: " + ", ".join(sensitive))

    files = [_file_record(project_root, path) for path in paths]
    return {
        "schema_version": "0.1",
        "manifest_type": "sceneguard-submission",
        "generated_at": datetime.now(UTC).isoformat(),
        "hash_algorithm": "SHA-256",
        "scope": {
            "included_directories": list(INCLUDED_DIRECTORIES),
            "included_root_files": list(INCLUDED_ROOT_FILES),
            "fixed_evidence_job_directories": list(INCLUDED_FIXED_JOB_DIRECTORIES),
            "fixed_report_files": list(INCLUDED_FIXED_REPORT_FILES),
            "excluded_runtime_paths": [
                "jobs/* except fixed_evidence_job_directories",
                "reports/* except fixed_report_files",
                ".http-demo-jobs/",
                "__pycache__/",
            ],
        },
        "summary": {
            "file_count": len(files),
            "total_bytes": sum(item["bytes"] for item in files),
        },
        "files": files,
    }


def write_submission_manifest(payload: dict[str, Any], output: str | Path) -> Path:
    return atomic_write_json(output, payload)


def verify_submission_manifest(root: str | Path, manifest_path: str | Path) -> dict[str, Any]:
    project_root = Path(root).resolve()
    manifest_file = Path(manifest_path)
    if not manifest_file.is_absolute():
        manifest_file = (project_root / manifest_file).resolve()
    if not manifest_file.is_file():
        return _verification(False, ["manifest file missing"], [], [])
    try:
        payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _verification(False, [f"invalid manifest JSON: {exc}"], [], [])

    errors: list[str] = []
    declared: dict[str, dict[str, Any]] = {}
    for item in payload.get("files", []):
        relative = item.get("path") if isinstance(item, dict) else None
        if not isinstance(relative, str) or not relative:
            errors.append("manifest contains a file with no relative path")
            continue
        candidate = (project_root / relative).resolve()
        if Path(relative).is_absolute() or not candidate.is_relative_to(project_root):
            errors.append(f"path escapes project root: {relative}")
            continue
        if relative in declared:
            errors.append(f"duplicate manifest path: {relative}")
            continue
        declared[relative] = item

    current_paths = _discover_deliverables(project_root)
    current = {path.relative_to(project_root).as_posix(): path for path in current_paths}
    missing = sorted(set(declared) - set(current))
    unexpected = sorted(set(current) - set(declared))
    changed: list[str] = []
    for relative in sorted(set(declared) & set(current)):
        item = declared[relative]
        path = current[relative]
        if item.get("bytes") != path.stat().st_size or item.get("sha256") != _sha256(path):
            changed.append(relative)

    sensitive = sorted(relative for relative, path in current.items() if SENSITIVE_NAME.search(path.name))
    if payload.get("schema_version") != "0.1" or payload.get("manifest_type") != "sceneguard-submission":
        errors.append("unsupported manifest schema or type")
    if sensitive:
        errors.append("sensitive-looking deliverables detected: " + ", ".join(sensitive))
    passed = not errors and not missing and not unexpected and not changed
    return _verification(passed, errors, missing, unexpected, changed)


def build_submission_archive(
    root: str | Path,
    manifest_path: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    manifest_file = _manifest_file(project_root, manifest_path)
    verification = verify_submission_manifest(project_root, manifest_file)
    if not verification["passed"]:
        raise SubmissionManifestError("submission manifest must verify before packaging")
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    target = Path(output).resolve()
    if target == manifest_file:
        raise SubmissionManifestError("archive output must not overwrite the submission manifest")
    if target.is_relative_to(project_root) and not target.is_relative_to(project_root / "reports"):
        raise SubmissionManifestError("archive output inside the project must remain under reports/")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        for item in payload["files"]:
            source = (project_root / item["path"]).resolve()
            _write_reproducible_zip_entry(archive, item["path"], source.read_bytes())
        _write_reproducible_zip_entry(archive, "SUBMISSION_MANIFEST.json", manifest_file.read_bytes())
    result = verify_submission_archive(target)
    if not result["passed"]:
        target.unlink(missing_ok=True)
        raise SubmissionManifestError("created submission archive failed self-verification")
    return {
        **result,
        "archive": str(target),
        "bytes": target.stat().st_size,
        "sha256": _sha256(target),
    }


def verify_submission_archive(archive_path: str | Path) -> dict[str, Any]:
    path = Path(archive_path).resolve()
    errors: list[str] = []
    if not path.is_file():
        return {"passed": False, "errors": ["archive file missing"], "file_count": 0}
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                errors.append("archive contains duplicate paths")
            for name in names:
                pure = Path(name)
                if pure.is_absolute() or ".." in pure.parts or "\\" in name:
                    errors.append(f"unsafe archive path: {name}")
                if name != "SUBMISSION_MANIFEST.json" and not _is_deliverable_name(name):
                    errors.append(f"archive path is outside declared delivery scope: {name}")
                if name != "SUBMISSION_MANIFEST.json" and SENSITIVE_NAME.search(pure.name):
                    errors.append(f"sensitive-looking archive path: {name}")
            if "SUBMISSION_MANIFEST.json" not in names:
                errors.append("archive manifest is missing")
                return {"passed": False, "errors": errors, "file_count": len(names)}
            payload = json.loads(archive.read("SUBMISSION_MANIFEST.json").decode("utf-8"))
            declared = {item["path"]: item for item in payload.get("files", [])}
            actual = set(names) - {"SUBMISSION_MANIFEST.json"}
            missing = sorted(set(declared) - actual)
            unexpected = sorted(actual - set(declared))
            if missing:
                errors.append("archive files missing: " + ", ".join(missing))
            if unexpected:
                errors.append("archive files unexpected: " + ", ".join(unexpected))
            for name in sorted(set(declared) & actual):
                content = archive.read(name)
                digest = hashlib.sha256(content).hexdigest()
                if len(content) != declared[name].get("bytes") or digest != declared[name].get("sha256"):
                    errors.append(f"archive content hash mismatch: {name}")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid submission archive: {exc}")
        names = []
    return {"passed": not errors, "errors": errors, "file_count": max(0, len(names) - 1)}


def _discover_deliverables(root: Path) -> list[Path]:
    paths: set[Path] = set()
    for name in INCLUDED_ROOT_FILES:
        candidate = root / name
        if candidate.is_file():
            paths.add(candidate.resolve())
    for name in INCLUDED_DIRECTORIES:
        directory = root / name
        if not directory.is_dir():
            continue
        for candidate in directory.rglob("*"):
            if not candidate.is_file():
                continue
            relative_parts = candidate.relative_to(root).parts
            if any(
                part in IGNORED_PARTS
                or any(part.endswith(suffix) for suffix in IGNORED_DIRECTORY_SUFFIXES)
                for part in relative_parts
            ):
                continue
            if candidate.suffix.lower() in IGNORED_SUFFIXES:
                continue
            paths.add(candidate.resolve())
    for name in INCLUDED_FIXED_JOB_DIRECTORIES:
        directory = root / name
        if directory.is_dir():
            paths.update(candidate.resolve() for candidate in directory.rglob("*") if candidate.is_file())
    for name in INCLUDED_FIXED_REPORT_FILES:
        candidate = root / name
        if candidate.is_file():
            paths.add(candidate.resolve())
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def _manifest_file(root: Path, manifest_path: str | Path) -> Path:
    path = Path(manifest_path)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise SubmissionManifestError("manifest path must remain inside the project root")
    if not resolved.is_file():
        raise SubmissionManifestError("submission manifest is missing")
    return resolved


def _is_deliverable_name(name: str) -> bool:
    pure = Path(name)
    if len(pure.parts) == 1:
        return name in INCLUDED_ROOT_FILES
    if pure.parts[0] in INCLUDED_DIRECTORIES:
        return True
    normalized = pure.as_posix()
    if normalized in INCLUDED_FIXED_REPORT_FILES:
        return True
    return any(
        normalized == directory or normalized.startswith(directory + "/")
        for directory in INCLUDED_FIXED_JOB_DIRECTORIES
    )


def _write_reproducible_zip_entry(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verification(
    passed: bool,
    errors: list[str],
    missing: list[str],
    unexpected: list[str],
    changed: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "passed": passed,
        "errors": errors,
        "missing": missing,
        "unexpected": unexpected,
        "changed": changed or [],
    }
