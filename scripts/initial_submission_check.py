from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATERIALS = ROOT.parents[1] / "初赛交付_20260816"
TEAM_CONFIRMATION = "TEAM_CONFIRMATION.json"
FORBIDDEN_TEXT = re.compile(
    r"(?:AKID[A-Za-z0-9]{12,}|LTAI[A-Za-z0-9]{12,}|Bearer\s+[A-Za-z0-9._~+/-]{8,}|"
    r"AccessKey(?:Id|Secret)?\s*[:=]\s*\S+|(?:C:\\Users\\|/Users/|/home/)[^\s]+)",
    re.IGNORECASE,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _pptx_summary(path: Path) -> tuple[int, list[str], list[str]]:
    texts: list[str] = []
    errors: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            slide_names = sorted(
                name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            )
            for name in slide_names:
                raw = archive.read(name).decode("utf-8", errors="replace")
                texts.extend(re.findall(r"<a:t>(.*?)</a:t>", raw, flags=re.DOTALL))
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        errors.append(f"invalid PPTX: {exc}")
        slide_names = []
    return len(slide_names), texts, errors


def _pdf_page_count(path: Path) -> int:
    data = path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page\b", data))


def validate_team_confirmation(materials: Path) -> tuple[bool, str]:
    path = materials / TEAM_CONFIRMATION
    if not path.is_file():
        return False, f"{TEAM_CONFIRMATION} not present"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"invalid {TEAM_CONFIRMATION}: {exc}"
    members = payload.get("members")
    confirmed_at = payload.get("confirmed_at")
    timestamp_valid = False
    if isinstance(confirmed_at, str) and confirmed_at:
        try:
            parsed = datetime.fromisoformat(confirmed_at.replace("Z", "+00:00"))
            timestamp_valid = parsed.tzinfo is not None
        except ValueError:
            timestamp_valid = False
    valid_members = bool(
        isinstance(members, list)
        and len({item.get("name") for item in members if isinstance(item, dict)}) == 3
        and all(
            isinstance(item, dict)
            and bool(str(item.get("name", "")).strip())
            and bool(str(item.get("role", "")).strip())
            and bool(str(item.get("responsibilities", "")).strip())
            and item.get("information_accurate") is True
            and item.get("role_responsibilities_confirmed") is True
            and item.get("public_use_authorized") is True
            and item.get("initial_membership_locked") is True
            for item in members
        )
    )
    valid = bool(
        payload.get("status") == "CONFIRMED"
        and payload.get("project_name") == "SceneGuard"
        and payload.get("project_name_confirmed") is True
        and payload.get("source_license_status") == "ALL_RIGHTS_RESERVED_NOT_PUBLIC"
        and payload.get("source_license_status_confirmed") is True
        and payload.get("initial_code_policy") == "NOT_PUBLIC_WITH_VERIFIABLE_REVIEW_MATERIALS"
        and payload.get("initial_code_policy_confirmed") is True
        and payload.get("cc0_asset_reviewed") is True
        and valid_members
        and timestamp_valid
    )
    return valid, "three members confirmed" if valid else "confirmation fields are incomplete"


def _select_material(candidates: list[Path]) -> Path | None:
    """Prefer a formal artifact when draft and formal files coexist."""
    if not candidates:
        return None
    formal = [path for path in candidates if "正式版" in path.name]
    return sorted(formal or candidates)[-1]


def collect_initial_submission(materials: str | Path = DEFAULT_MATERIALS) -> dict:
    root = Path(materials).resolve()
    checks: list[dict] = []

    def record(check_id: str, passed: bool, required: bool, detail: str) -> None:
        checks.append(
            {"check_id": check_id, "passed": bool(passed), "required": bool(required), "detail": detail}
        )

    root_exists = root.is_dir()
    record("required.materials_root", root_exists, True, str(root))
    intro = root / "SceneGuard_初赛作品简介_500字内.txt"
    pptx_candidates = sorted(root.glob("SceneGuard_初赛方案*.pptx")) if root_exists else []
    pdf_candidates = sorted(root.glob("SceneGuard_初赛方案*.pdf")) if root_exists else []
    pptx = _select_material(pptx_candidates)
    pdf = _select_material(pdf_candidates)

    intro_text = intro.read_text(encoding="utf-8").strip() if intro.is_file() else ""
    record("required.introduction", intro.is_file(), True, str(intro.name))
    record("required.introduction_limit", 0 < len(intro_text) <= 500, True, f"unicode_chars={len(intro_text)}")
    record("required.pptx", pptx is not None, True, pptx.name if pptx else "missing")
    record("required.pdf", pdf is not None, True, pdf.name if pdf else "missing")

    pptx_pages = 0
    pptx_texts: list[str] = []
    pptx_errors: list[str] = []
    if pptx:
        pptx_pages, pptx_texts, pptx_errors = _pptx_summary(pptx)
    pdf_pages = _pdf_page_count(pdf) if pdf else 0
    record("required.pptx_structure", pptx_pages >= 10 and not pptx_errors, True, f"slides={pptx_pages}")
    record("required.pdf_structure", pdf_pages == pptx_pages and pdf_pages >= 10, True, f"pages={pdf_pages}")

    combined = intro_text + "\n" + "\n".join(pptx_texts)
    record("required.no_secrets", FORBIDDEN_TEXT.search(combined) is None, True, "retained text secret scan")

    team_valid, team_detail = validate_team_confirmation(root)
    record("signoff.team", team_valid, True, team_detail)
    draft_marker = any("待团队确认" in path.name for path in (pptx, pdf) if path is not None)
    record("signoff.final_filename", not draft_marker, True, "no draft marker in formal filenames")

    optional_skill = ROOT / "evidence" / "official-skill" / "integration.json"
    record("optional.aliyun_skill", optional_skill.is_file(), False, "real official Skill evidence")
    optional_demo = ROOT / "reports" / "initial-demo-smoke.json"
    demo_passed = False
    if optional_demo.is_file():
        try:
            demo_passed = json.loads(optional_demo.read_text(encoding="utf-8")).get("status") == "PASS"
        except (OSError, ValueError):
            demo_passed = False
    record("recommended.demo_smoke", demo_passed, False, "reports/initial-demo-smoke.json status PASS")

    required = [item for item in checks if item["required"]]
    technical_ids = {
        "required.materials_root",
        "required.introduction",
        "required.introduction_limit",
        "required.pptx",
        "required.pdf",
        "required.pptx_structure",
        "required.pdf_structure",
        "required.no_secrets",
    }
    technical_passed = all(item["passed"] for item in checks if item["check_id"] in technical_ids)
    signoff_passed = all(item["passed"] for item in checks if item["check_id"].startswith("signoff."))
    status = "PASS" if all(item["passed"] for item in required) else "WAITING_TEAM_CONFIRMATION" if technical_passed else "FAIL"

    files = []
    for path in sorted(candidate for candidate in root.iterdir() if candidate.is_file()) if root_exists else []:
        if path.name == TEAM_CONFIRMATION or path.suffix.lower() in {".txt", ".pptx", ".pdf"}:
            files.append({"name": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    return {
        "schema_version": "0.1",
        "check_id": "sceneguard-initial-submission-20260816",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "technical_materials_passed": technical_passed,
        "team_signoff_passed": signoff_passed,
        "materials_root": str(root),
        "checks": checks,
        "files": files,
        "next_actions": [item["detail"] for item in required if not item["passed"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the SceneGuard initial-round submission materials")
    parser.add_argument("--materials", type=Path, default=DEFAULT_MATERIALS)
    parser.add_argument("--output", type=Path, default=Path("reports/initial-submission-check.json"))
    parser.add_argument("--allow-pending-signoff", action="store_true")
    parser.add_argument("--team-only", action="store_true")
    args = parser.parse_args()
    if args.team_only:
        valid, detail = validate_team_confirmation(args.materials.resolve())
        print(json.dumps({"passed": valid, "detail": detail}, ensure_ascii=False, indent=2))
        return 0 if valid else 2
    result = collect_initial_submission(args.materials)
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "PASS":
        return 0
    if args.allow_pending_signoff and result["status"] == "WAITING_TEAM_CONFIRMATION":
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
