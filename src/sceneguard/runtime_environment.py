from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path


def find_docker_executable(
    *,
    which: Callable[[str], str | None] = shutil.which,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    """Find Docker even when the current Windows process has a stale PATH."""
    discovered = which("docker")
    if discovered:
        return discovered

    if os.name != "nt":
        return None

    env = os.environ if environment is None else environment
    program_files = env.get("ProgramFiles", r"C:\Program Files")
    candidate = Path(program_files) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
    return str(candidate) if candidate.is_file() else None


def find_node_executable(
    *,
    which: Callable[[str], str | None] = shutil.which,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    discovered = which("node")
    if discovered:
        return discovered
    if os.name != "nt":
        return None
    env = os.environ if environment is None else environment
    candidate = Path(env.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe"
    return str(candidate) if candidate.is_file() else None


def find_aliyun_executable(
    *,
    which: Callable[[str], str | None] = shutil.which,
    environment: Mapping[str, str] | None = None,
) -> str | None:
    discovered = which("aliyun")
    if discovered:
        return discovered
    if os.name != "nt":
        return None
    env = os.environ if environment is None else environment
    local_app_data = env.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    candidate = Path(local_app_data) / "AliyunCLI" / "aliyun.exe"
    return str(candidate) if candidate.is_file() else None
