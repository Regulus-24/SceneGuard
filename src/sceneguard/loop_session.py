from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from .benchmark import run_acceptance_benchmark, write_benchmark_receipt
from .io_utils import atomic_write_json
from .loop_control import update_loop_state
from .runtime_environment import find_docker_executable
from .submission import build_submission_archive, build_submission_manifest, write_submission_manifest


SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
TERMINAL_DECISIONS = {"COMPLETE", "STOP_ITERATION_LIMIT"}


class LoopSessionAlreadyRunning(RuntimeError):
    pass


class LoopSessionLock(AbstractContextManager["LoopSessionLock"]):
    """A crash-releasing, cross-platform advisory lock for one loop supervisor."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._stream: Any = None

    def __enter__(self) -> "LoopSessionLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            stream.close()
            raise LoopSessionAlreadyRunning(f"loop supervisor lock is held: {self.path}") from exc
        self._stream = stream
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._stream is None:
            return
        self._stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()
        self._stream = None


def run_loop_session(
    project_root: str | Path,
    *,
    config_path: str | Path = "benchmark/acceptance.v0.1.json",
    latest_receipt_path: str | Path = "reports/benchmark-latest.json",
    state_path: str | Path = "reports/loop-state.json",
    sessions_path: str | Path = "reports/loop-sessions",
    lock_path: str | Path = "reports/loop-supervisor.lock",
    target: str = "release",
    max_duration_seconds: float = 10 * 60 * 60,
    poll_interval_seconds: float = 60,
    watch_external: bool = False,
    include_tests: bool = True,
    worker_command: Sequence[str] | None = None,
    worker_timeout_seconds: float = 60 * 60,
    session_id: str | None = None,
    benchmark_runner: Callable[..., dict[str, Any]] = run_acceptance_benchmark,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    checkpoint_builder: Callable[[Path, Path, int], Path] | None = None,
    worker_runner: Callable[[Path, tuple[str, ...], Path, str, Path, float], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a bounded, resumable benchmark session around an explicitly supplied worker.

    The supervisor never uses a shell, never fabricates external evidence and never
    overwrites a regressed workspace. Before every worker invocation it writes a
    reproducible recovery archive and stops on a lower core score.
    """
    root = Path(project_root).resolve()
    if target not in {"core", "release"}:
        raise ValueError("target must be core or release")
    if not 0 < max_duration_seconds <= 24 * 60 * 60:
        raise ValueError("max_duration_seconds must be in (0, 86400]")
    if not 0 < poll_interval_seconds <= 60 * 60:
        raise ValueError("poll_interval_seconds must be in (0, 3600]")
    if not 0 < worker_timeout_seconds <= 4 * 60 * 60:
        raise ValueError("worker_timeout_seconds must be in (0, 14400]")
    command = tuple(str(item) for item in (worker_command or ()))
    if any(not item for item in command):
        raise ValueError("worker command arguments must be non-empty")
    current_session_id = session_id or _new_session_id()
    if not SESSION_ID.fullmatch(current_session_id):
        raise ValueError("invalid session id")

    session_dir = _inside(root, sessions_path) / current_session_id
    started_wall = datetime.now(UTC).isoformat()
    started = monotonic()
    deadline = started + max_duration_seconds
    status_path = session_dir / "session.json"
    work_item_path = session_dir / "work-item.json"
    baseline_score: int | None = None
    session_iterations = 0
    build_checkpoint = checkpoint_builder or _checkpoint
    invoke_worker = worker_runner or _run_worker

    with LoopSessionLock(_inside(root, lock_path)):
        if session_dir.exists():
            raise ValueError(f"session already exists: {current_session_id}")
        session_dir.mkdir(parents=True)
        while True:
            benchmark = benchmark_runner(root, _inside(root, config_path), include_test_suite=include_tests)
            write_benchmark_receipt(benchmark, _inside(root, latest_receipt_path))
            state = update_loop_state(benchmark, _inside(root, state_path), target=target)
            iteration = int(state["iteration"])
            session_iterations += 1
            immutable_receipt = session_dir / f"benchmark-iteration-{iteration:03d}.json"
            if immutable_receipt.exists():
                raise RuntimeError(f"immutable receipt already exists: {immutable_receipt}")
            write_benchmark_receipt(benchmark, immutable_receipt)
            score = int(benchmark["core"]["score"])
            if baseline_score is not None and score < baseline_score:
                return _finish(
                    status_path,
                    current_session_id,
                    started_wall,
                    session_iterations,
                    iteration,
                    "REGRESSION_DETECTED",
                    benchmark,
                    recovery_archive=_latest_checkpoint(session_dir),
                )
            baseline_score = score if baseline_score is None else max(baseline_score, score)
            decision = str(state["decision"])
            _heartbeat(
                status_path,
                current_session_id,
                started_wall,
                session_iterations,
                iteration,
                decision,
                benchmark,
            )

            if decision in TERMINAL_DECISIONS:
                return _finish(
                    status_path,
                    current_session_id,
                    started_wall,
                    session_iterations,
                    iteration,
                    decision,
                    benchmark,
                )
            if monotonic() >= deadline:
                return _finish(
                    status_path,
                    current_session_id,
                    started_wall,
                    session_iterations,
                    iteration,
                    "STOP_TIME_BUDGET",
                    benchmark,
                )
            if decision == "AWAIT_EXTERNAL_EVIDENCE":
                if not watch_external:
                    return _finish(
                        status_path,
                        current_session_id,
                        started_wall,
                        session_iterations,
                        iteration,
                        decision,
                        benchmark,
                    )
                snapshot = _external_snapshot(root, _inside(root, config_path))
                while monotonic() < deadline:
                    sleeper(min(poll_interval_seconds, max(0.0, deadline - monotonic())))
                    if _external_snapshot(root, _inside(root, config_path)) != snapshot:
                        break
                    _heartbeat(
                        status_path,
                        current_session_id,
                        started_wall,
                        session_iterations,
                        iteration,
                        "WATCHING_EXTERNAL_EVIDENCE",
                        benchmark,
                    )
                else:
                    return _finish(
                        status_path,
                        current_session_id,
                        started_wall,
                        session_iterations,
                        iteration,
                        "STOP_TIME_BUDGET",
                        benchmark,
                    )
                if monotonic() >= deadline:
                    return _finish(
                        status_path,
                        current_session_id,
                        started_wall,
                        session_iterations,
                        iteration,
                        "STOP_TIME_BUDGET",
                        benchmark,
                    )
                continue

            work_item = {
                "schema_version": "0.1",
                "session_id": current_session_id,
                "iteration": iteration,
                "decision": decision,
                "target": target,
                "core_score": score,
                "core_status": benchmark["core"]["status"],
                "release_status": benchmark["release"]["status"],
                "next_actions": benchmark["next_actions"],
                "benchmark_receipt": immutable_receipt.relative_to(root).as_posix(),
                "safety": {
                    "do_not_fabricate_external_evidence": True,
                    "preserve_user_changes": True,
                    "run_benchmark_after_minimal_change": True,
                    "stop_on_core_score_regression": True,
                },
            }
            atomic_write_json(work_item_path, work_item)
            if not command:
                return _finish(
                    status_path,
                    current_session_id,
                    started_wall,
                    session_iterations,
                    iteration,
                    "AGENT_ACTION_REQUIRED",
                    benchmark,
                    work_item=work_item_path.relative_to(root).as_posix(),
                )
            if monotonic() >= deadline:
                return _finish(
                    status_path,
                    current_session_id,
                    started_wall,
                    session_iterations,
                    iteration,
                    "STOP_TIME_BUDGET",
                    benchmark,
                )
            checkpoint = build_checkpoint(root, session_dir, iteration)
            result = invoke_worker(
                root,
                command,
                work_item_path,
                current_session_id,
                checkpoint,
                min(worker_timeout_seconds, max(0.001, deadline - monotonic())),
            )
            atomic_write_json(session_dir / f"worker-iteration-{iteration:03d}.json", result)
            if result["status"] != "PASS":
                return _finish(
                    status_path,
                    current_session_id,
                    started_wall,
                    session_iterations,
                    iteration,
                    "WORKER_FAILED",
                    benchmark,
                    recovery_archive=checkpoint.relative_to(root).as_posix(),
                )
            if monotonic() >= deadline:
                return _finish(
                    status_path,
                    current_session_id,
                    started_wall,
                    session_iterations,
                    iteration,
                    "STOP_TIME_BUDGET",
                    benchmark,
                    recovery_archive=checkpoint.relative_to(root).as_posix(),
                )


def _new_session_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def _inside(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes project root: {value}")
    return resolved


def _external_snapshot(root: Path, config_path: Path) -> str:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for relative in sorted(config.get("required_release_evidence", [])):
        path = _inside(root, relative)
        records.append(
            {
                "path": relative,
                "exists": path.is_file(),
                "bytes": path.stat().st_size if path.is_file() else None,
                "sha256": _sha256(path) if path.is_file() else None,
            }
        )
    records.append({"docker_executable": find_docker_executable()})
    return hashlib.sha256(json.dumps(records, sort_keys=True).encode("utf-8")).hexdigest()


def _checkpoint(root: Path, session_dir: Path, iteration: int) -> Path:
    checkpoint_dir = session_dir / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    manifest_path = checkpoint_dir / f"iteration-{iteration:03d}.manifest.json"
    archive_path = checkpoint_dir / f"iteration-{iteration:03d}.zip"
    write_submission_manifest(build_submission_manifest(root), manifest_path)
    result = build_submission_archive(root, manifest_path, archive_path)
    if not result.get("passed"):
        raise RuntimeError(f"failed to build recovery archive: {result.get('errors', [])}")
    return archive_path


def _run_worker(
    root: Path,
    command: tuple[str, ...],
    work_item_path: Path,
    session_id: str,
    checkpoint: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.update(
        {
            "SCENEGUARD_LOOP_WORK_ITEM": str(work_item_path),
            "SCENEGUARD_LOOP_SESSION_ID": session_id,
            "SCENEGUARD_LOOP_CHECKPOINT": str(checkpoint),
        }
    )
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "TIMEOUT",
            "executable": command[0],
            "argument_count": len(command),
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "executable": command[0],
        "argument_count": len(command),
        "exit_code": completed.returncode,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _heartbeat(
    path: Path,
    session_id: str,
    started_at: str,
    session_iterations: int,
    global_iteration: int,
    decision: str,
    benchmark: dict[str, Any],
) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": "0.1",
            "session_id": session_id,
            "started_at": started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "status": "RUNNING",
            "decision": decision,
            "session_iterations": session_iterations,
            "global_iteration": global_iteration,
            "core_score": benchmark["core"]["score"],
            "core_status": benchmark["core"]["status"],
            "release_status": benchmark["release"]["status"],
        },
    )


def _finish(
    path: Path,
    session_id: str,
    started_at: str,
    session_iterations: int,
    global_iteration: int,
    outcome: str,
    benchmark: dict[str, Any],
    **details: Any,
) -> dict[str, Any]:
    payload = {
        "schema_version": "0.1",
        "session_id": session_id,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "status": "FINISHED",
        "outcome": outcome,
        "session_iterations": session_iterations,
        "global_iteration": global_iteration,
        "core_score": benchmark["core"]["score"],
        "core_status": benchmark["core"]["status"],
        "release_status": benchmark["release"]["status"],
        **details,
    }
    atomic_write_json(path, payload)
    return payload


def _latest_checkpoint(session_dir: Path) -> str | None:
    archives = sorted((session_dir / "checkpoints").glob("iteration-*.zip"))
    return archives[-1].relative_to(session_dir.parent.parent.parent).as_posix() if archives else None
