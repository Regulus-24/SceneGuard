from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sceneguard.runtime_environment import find_aliyun_executable, find_docker_executable, find_node_executable


class RuntimeEnvironmentTests(unittest.TestCase):
    def test_prefers_docker_from_path(self) -> None:
        self.assertEqual(
            find_docker_executable(which=lambda command: "/usr/bin/docker"),
            "/usr/bin/docker",
        )

    @unittest.skipUnless(os.name == "nt", "Windows Docker Desktop fallback")
    def test_finds_docker_desktop_when_path_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch("sceneguard.runtime_environment.os.name", "nt"):
                found = find_docker_executable(
                    which=lambda command: None,
                    environment={"ProgramFiles": directory},
                )
            self.assertEqual(found, str(executable))

    @unittest.skipUnless(os.name == "nt", "Windows Node.js fallback")
    def test_finds_node_when_path_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "nodejs" / "node.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch("sceneguard.runtime_environment.os.name", "nt"):
                found = find_node_executable(
                    which=lambda command: None,
                    environment={"ProgramFiles": directory},
                )
            self.assertEqual(found, str(executable))

    @unittest.skipUnless(os.name == "nt", "Windows Alibaba Cloud CLI fallback")
    def test_finds_aliyun_cli_when_path_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "AliyunCLI" / "aliyun.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch("sceneguard.runtime_environment.os.name", "nt"):
                found = find_aliyun_executable(
                    which=lambda command: None,
                    environment={"LOCALAPPDATA": directory},
                )
            self.assertEqual(found, str(executable))


if __name__ == "__main__":
    unittest.main()
