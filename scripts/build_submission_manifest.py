from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.submission import (  # noqa: E402
    build_submission_archive,
    build_submission_manifest,
    verify_submission_manifest,
    verify_submission_archive,
    write_submission_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify the SceneGuard submission manifest.")
    parser.add_argument("--output", default="reports/submission-manifest.json")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--archive", help="build a reproducible ZIP after manifest verification")
    parser.add_argument("--verify-archive", help="verify a previously generated submission ZIP")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if args.verify_archive:
        result = verify_submission_archive((ROOT / args.verify_archive).resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    if args.archive:
        result = build_submission_archive(ROOT, output, (ROOT / args.archive).resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.verify:
        if not output.is_file() and (ROOT / "SUBMISSION_MANIFEST.json").is_file():
            output = ROOT / "SUBMISSION_MANIFEST.json"
        result = verify_submission_manifest(ROOT, output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    payload = build_submission_manifest(ROOT)
    write_submission_manifest(payload, output)
    print(f"wrote {output} ({payload['summary']['file_count']} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
