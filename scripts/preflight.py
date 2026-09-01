from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sceneguard.runtime_environment import find_aliyun_executable, find_docker_executable, find_node_executable


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def collect_preflight(
    root: str | Path = ROOT,
    *,
    docker_command: str | None = None,
    port_check=port_available,
) -> dict:
    project_root = Path(root).resolve()
    config_path = project_root / "benchmark" / "acceptance.v0.1.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    sample_ids = sorted(
        path.relative_to(project_root / "samples").as_posix()
        for path in (project_root / "samples").rglob("*.glb")
        if path.is_file() and path.resolve().is_relative_to(project_root)
    )
    sample_paths = [f"samples/{sample_id}" for sample_id in sample_ids]
    source_manifest = json.loads((project_root / "samples" / "source_manifest.json").read_text(encoding="utf-8"))
    golden_manifest = json.loads((project_root / config["golden_manifest"]).read_text(encoding="utf-8"))
    source_names = set(source_manifest.get("samples", {}))
    golden_names = set(golden_manifest.get("samples", {}))
    profile_status = {
        name: (project_root / relative).is_file()
        for name, relative in config.get("profiles", {}).items()
    }
    public_config = config.get("public_asset_benchmark", {})
    public_asset = project_root / str(public_config.get("asset", ""))
    docker = find_docker_executable() if docker_command is None else docker_command
    node = find_node_executable()
    aliyun = find_aliyun_executable()
    official_skill = project_root / ".codex" / "skills" / "alibabacloud-resourcecenter-search" / "SKILL.md"
    return {
        "python": {
            "version": ".".join(map(str, sys.version_info[:3])),
            "supported": sys.version_info >= (3, 11),
            "executable": sys.executable,
        },
        "deterministic_core": {
            "benchmark_config_exists": config_path.is_file(),
            "profiles": profile_status,
            "golden_manifest_exists": (project_root / config["golden_manifest"]).is_file(),
            "sample_count": len(sample_paths),
            "sample_paths": sample_paths,
            "registered_sample_count": len(source_names),
            "golden_sample_count": len(golden_names),
            "minimum_sample_count": int(config["minimum_golden_sample_count"]),
            "source_golden_and_disk_match": source_names == golden_names == set(sample_ids),
            "public_asset_exists": public_asset.is_file(),
            "gateway_port_18091_available": bool(port_check("127.0.0.1", 18091)),
        },
        "agentteams": {
            "docker_command": docker,
            "docker_available": docker is not None,
            "ready_to_install": docker is not None,
            "note": "AgentTeams/HiClaw requires Docker Desktop/Engine; absence does not block the deterministic core.",
        },
        "official_skill": {
            "node_command": node,
            "node_available": node is not None,
            "aliyun_command": aliyun,
            "aliyun_cli_available": aliyun is not None,
            "skill_spec": str(official_skill) if official_skill.is_file() else None,
            "skill_installed": official_skill.is_file(),
            "ready_for_user_credential_configuration": node is not None
            and aliyun is not None
            and official_skill.is_file(),
            "credentials_inspected": False,
            "note": "Credential readiness is checked only through the official Skill flow and is never inferred from local files.",
        },
    }


def core_ready(result: dict) -> bool:
    core = result["deterministic_core"]
    return all(
        [
            result["python"]["supported"],
            core["benchmark_config_exists"],
            all(core["profiles"].values()),
            core["golden_manifest_exists"],
            core["sample_count"] >= core["minimum_sample_count"],
            core["source_golden_and_disk_match"],
            core["public_asset_exists"],
            result.get("tests", {"passed": True})["passed"],
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SceneGuard PoC and AgentTeams prerequisites")
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args()

    result = collect_preflight()
    if args.run_tests:
        process = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        result["tests"] = {
            "exit_code": process.returncode,
            "passed": process.returncode == 0,
            "summary": (process.stderr or process.stdout).splitlines()[-4:],
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if core_ready(result) else 2


if __name__ == "__main__":
    raise SystemExit(main())
