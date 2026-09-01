#!/usr/bin/env python3
"""Verify or reproducibly download pinned open-source GitHub assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
PUBLIC = SAMPLES / "public"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download pinned bytes after validating source and license metadata.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "public-asset-sync-latest.json",
    )
    args = parser.parse_args()
    report = sync_all(download=args.download)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


def sync_all(*, download: bool) -> dict[str, Any]:
    records = sorted(PUBLIC.glob("*.source.json"))
    results = []
    for record_path in records:
        try:
            results.append(sync_record(record_path, download=download))
        except Exception as exc:
            results.append(
                {
                    "source_record": record_path.relative_to(ROOT).as_posix(),
                    "passed": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
    passed = len(results) == 3 and all(item.get("passed") is True for item in results)
    return {
        "schema_version": "0.1",
        "status": "PASS" if passed else "FAIL",
        "mode": "download-and-verify" if download else "offline-verify",
        "source_platform": "GitHub",
        "source_project": "KhronosGroup/glTF-Sample-Assets",
        "asset_count": len(results),
        "license_policy": "CC0-1.0 with voluntary original-author credit retained",
        "assets": results,
        "claim_boundary": (
            "This is a reproducible open-source asset-platform intake. It is not "
            "claimed as a private studio, customer, or production DAM integration."
        ),
    }


def sync_record(record_path: Path, *, download: bool) -> dict[str, Any]:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    target = validate_record(record)
    if download:
        request = Request(
            record["download_url"],
            headers={"User-Agent": "SceneGuard-public-asset-sync/0.1"},
        )
        with urlopen(request, timeout=60) as response:
            data = response.read()
        verify_payload(record, data)
        temporary = target.with_suffix(target.suffix + ".verified-download")
        temporary.write_bytes(data)
        os.replace(temporary, target)
    else:
        data = target.read_bytes()
        verify_payload(record, data)
    return {
        "asset": target.relative_to(ROOT).as_posix(),
        "source_record": record_path.relative_to(ROOT).as_posix(),
        "passed": True,
        "downloaded": download,
        "upstream_commit": record["upstream_commit"],
        "creator": record["creator"],
        "license_spdx": record["license_spdx"],
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "download_url": record["download_url"],
        "attribution": record["attribution"],
    }


def validate_record(record: dict[str, Any]) -> Path:
    required_strings = [
        "local_path",
        "project",
        "creator",
        "license_spdx",
        "upstream_commit",
        "download_url",
        "attribution",
        "review_status",
    ]
    missing = [key for key in required_strings if not isinstance(record.get(key), str) or not record[key]]
    if missing:
        raise ValueError(f"missing source metadata: {missing}")
    if record.get("source_type") != "PUBLIC_LICENSED":
        raise ValueError("source_type must be PUBLIC_LICENSED")
    if record["project"] != "KhronosGroup/glTF-Sample-Assets":
        raise ValueError("unexpected GitHub source project")
    if record["license_spdx"] != "CC0-1.0":
        raise ValueError("public asset must retain CC0-1.0")
    if record.get("redistribution_allowed") is not True:
        raise ValueError("redistribution must be explicitly allowed")
    if record["review_status"] != "TEAM_REVIEWED":
        raise ValueError("source record must be team reviewed")
    commit = record["upstream_commit"]
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("upstream_commit must be a full immutable SHA")
    parsed = urlparse(record["download_url"])
    expected_prefix = f"/KhronosGroup/glTF-Sample-Assets/{commit}/"
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com":
        raise ValueError("download_url must use GitHub raw HTTPS")
    if not parsed.path.startswith(expected_prefix):
        raise ValueError("download_url must be pinned to upstream_commit")

    relative = Path(record["local_path"])
    if relative.is_absolute() or ".." in relative.parts or relative.parent != Path("public"):
        raise ValueError("local_path must be one file directly under samples/public")
    target = (SAMPLES / relative).resolve()
    if target.parent != PUBLIC.resolve() or target.suffix.lower() != ".glb":
        raise ValueError("local_path escapes the public GLB directory")
    return target


def verify_payload(record: dict[str, Any], data: bytes) -> None:
    expected_size = record.get("bytes")
    if not isinstance(expected_size, int) or len(data) != expected_size:
        raise ValueError(f"byte size mismatch: expected {expected_size}, observed {len(data)}")
    observed = hashlib.sha256(data).hexdigest()
    if observed != record.get("sha256"):
        raise ValueError(f"sha256 mismatch: expected {record.get('sha256')}, observed {observed}")


if __name__ == "__main__":
    raise SystemExit(main())
