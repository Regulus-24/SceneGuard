from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATERIALS = ROOT.parents[1] / "初赛交付_20260816"
DEFAULT_OUTPUT = DEFAULT_MATERIALS / "SceneGuard_初赛正式提交包.zip"


def _load_checker():
    path = ROOT / "scripts" / "initial_submission_check.py"
    spec = importlib.util.spec_from_file_location("sceneguard_initial_submission_check", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_zip_entry(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


def _selected_path(check: dict, check_id: str, materials: Path) -> Path:
    item = next(entry for entry in check["checks"] if entry["check_id"] == check_id)
    return materials / item["detail"]


def build_package(materials: str | Path, output: str | Path) -> dict:
    materials_root = Path(materials).resolve()
    target = Path(output).resolve()
    check = CHECKER.collect_initial_submission(materials_root)
    if check["status"] != "PASS":
        raise ValueError("initial submission check must be PASS before formal packaging")

    sources: list[tuple[str, Path]] = [
        ("01_官方必交/SceneGuard_初赛作品简介_500字内.txt", materials_root / "SceneGuard_初赛作品简介_500字内.txt"),
        ("01_官方必交/SceneGuard_初赛方案v3_正式版.pptx", _selected_path(check, "required.pptx", materials_root)),
        ("01_官方必交/SceneGuard_初赛方案v3_正式版.pdf", _selected_path(check, "required.pdf", materials_root)),
        ("02_内部确认/TEAM_CONFIRMATION.json", materials_root / "TEAM_CONFIRMATION.json"),
    ]
    optional_files = [
        ("03_演示辅助/SceneGuard_Demo彩排与录屏脚本.txt", materials_root / "SceneGuard_Demo彩排与录屏脚本.txt"),
    ]
    screenshots = materials_root / "demo_screenshots"
    if screenshots.is_dir():
        optional_files.extend(
            (f"03_演示辅助/demo_screenshots/{path.name}", path)
            for path in sorted(screenshots.glob("*.png"))
        )
    sources.extend((name, path) for name, path in optional_files if path.is_file())

    records = []
    entries: list[tuple[str, bytes]] = []
    for name, path in sources:
        if not path.is_file():
            raise ValueError(f"required package source is missing: {path.name}")
        content = path.read_bytes()
        entries.append((name, content))
        records.append({"path": name, "bytes": len(content), "sha256": _sha256_bytes(content)})

    check_bytes = (json.dumps(check, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    entries.append(("SUBMISSION_CHECK.json", check_bytes))
    records.append(
        {"path": "SUBMISSION_CHECK.json", "bytes": len(check_bytes), "sha256": _sha256_bytes(check_bytes)}
    )
    manifest = {
        "schema_version": "0.1",
        "package_type": "sceneguard-initial-formal",
        "generated_at": datetime.now(UTC).isoformat(),
        "official_required_directory": "01_官方必交/",
        "file_count": len(records),
        "files": records,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w") as archive:
        for name, content in entries:
            _write_zip_entry(archive, name, content)
        _write_zip_entry(archive, "MATERIALS_MANIFEST.json", manifest_bytes)
    verification = verify_package(target)
    if not verification["passed"]:
        target.unlink(missing_ok=True)
        raise ValueError("created formal package failed self-verification")
    return {
        **verification,
        "archive": str(target),
        "bytes": target.stat().st_size,
        "sha256": _sha256_bytes(target.read_bytes()),
    }


def verify_package(path: str | Path) -> dict:
    archive_path = Path(path).resolve()
    errors: list[str] = []
    if not archive_path.is_file():
        return {"passed": False, "errors": ["archive file missing"], "file_count": 0}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                errors.append("duplicate archive paths")
            if "MATERIALS_MANIFEST.json" not in names:
                return {"passed": False, "errors": ["materials manifest missing"], "file_count": len(names)}
            manifest = json.loads(archive.read("MATERIALS_MANIFEST.json").decode("utf-8"))
            declared = {item["path"]: item for item in manifest.get("files", [])}
            actual = set(names) - {"MATERIALS_MANIFEST.json"}
            if set(declared) != actual:
                errors.append("manifest paths do not match archive paths")
            if manifest.get("package_type") != "sceneguard-initial-formal":
                errors.append("unexpected package type")
            required_suffixes = {".txt", ".pptx", ".pdf"}
            official = [name for name in names if name.startswith("01_官方必交/")]
            if len(official) != 3 or {Path(name).suffix for name in official} != required_suffixes:
                errors.append("official required directory must contain intro, PPTX and PDF")
            if any("待团队确认" in name or "template" in name.lower() for name in names):
                errors.append("draft or template file present")
            for name, item in declared.items():
                content = archive.read(name)
                if len(content) != item.get("bytes") or _sha256_bytes(content) != item.get("sha256"):
                    errors.append(f"hash mismatch: {name}")
            check = json.loads(archive.read("SUBMISSION_CHECK.json").decode("utf-8"))
            if check.get("status") != "PASS":
                errors.append("embedded submission check is not PASS")
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid package: {exc}")
        names = []
    return {"passed": not errors, "errors": errors, "file_count": max(0, len(names) - 1)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify the SceneGuard formal initial materials package")
    parser.add_argument("--materials", type=Path, default=DEFAULT_MATERIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    try:
        result = verify_package(args.verify) if args.verify else build_package(args.materials, args.output)
    except ValueError as exc:
        result = {"passed": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
