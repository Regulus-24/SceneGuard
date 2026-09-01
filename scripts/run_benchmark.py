from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.benchmark import run_acceptance_benchmark, write_benchmark_receipt  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded SceneGuard acceptance benchmark")
    parser.add_argument("--config", default=Path("benchmark/acceptance.v0.1.json"), type=Path)
    parser.add_argument("--output", default=Path("reports/benchmark-latest.json"), type=Path)
    parser.add_argument("--target", choices=("core", "release"), default="core")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    result = run_acceptance_benchmark(ROOT, args.config, include_test_suite=not args.skip_tests)
    write_benchmark_receipt(result, ROOT / args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = result["core"]["status"] if args.target == "core" else result["release"]["status"]
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
