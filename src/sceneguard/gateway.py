from __future__ import annotations

import json
import hmac
import hashlib
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from .audit import audit_asset
from .glb import GlbFormatError, parse_glb_bytes
from .pipeline import decide_pending_job, run_job
from .profile import QualityProfile
from .staged_pipeline import execute_job, plan_job, verify_job
from .ui import DASHBOARD_HTML
from .workspace import create_job_workspace


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SAFE_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(?:json|jsonl)$")
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SAFE_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
HTTP_API_ROUTES = (
    ("GET", "/health"),
    ("GET", "/v1/assets"),
    ("GET", "/v1/assets/content"),
    ("GET", "/v1/profiles"),
    ("POST", "/v1/assets/upload"),
    ("POST", "/v1/tools/asset.audit"),
    ("POST", "/v1/jobs"),
    ("POST", "/v1/tools/repair.plan"),
    ("POST", "/v1/tools/repair.execute"),
    ("POST", "/v1/tools/regression.verify"),
    ("POST", "/v1/pipeline/run"),
    ("POST", "/v1/pipeline/decide"),
    ("GET", "/v1/jobs/{job_id}/artifacts"),
    ("GET", "/v1/jobs/{job_id}/artifacts/{artifact_id}"),
    ("GET", "/v1/jobs/{job_id}/assets/{asset_kind}"),
)


class GatewayError(ValueError):
    def __init__(self, code: str, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class GatewayService:
    def __init__(self, asset_root: str | Path, profile_root: str | Path, jobs_root: str | Path) -> None:
        self.asset_root = Path(asset_root).resolve()
        self.profile_root = Path(profile_root).resolve()
        self.jobs_root = Path(jobs_root).resolve()
        self._idempotency_lock = threading.Lock()
        self._stage_lock = threading.Lock()

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "service": "sceneguard-tool-gateway",
            "version": "0.1.0",
            "write_scope": "configured_jobs_root",
        }

    def profiles(self) -> dict[str, Any]:
        items = []
        if self.profile_root.exists():
            for path in sorted(self.profile_root.glob("*.json")):
                profile = QualityProfile.load(path)
                items.append(
                    {
                        "id": profile.profile_id,
                        "version": profile.version,
                        "file": path.name,
                        "description": profile.description,
                        "rules": profile.rules,
                        "repair_policy": profile.repair_policy,
                    }
                )
        return {"profiles": items}

    def assets(self) -> dict[str, Any]:
        items = []
        manifest_path = self.asset_root / "source_manifest.json"
        manifest = {}
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")).get("samples", {})
        if self.asset_root.exists():
            for path in sorted(self.asset_root.rglob("*.glb")):
                resolved = path.resolve()
                if resolved.is_relative_to(self.asset_root):
                    name = resolved.relative_to(self.asset_root).as_posix()
                    record = manifest.get(name, {})
                    items.append(
                        {
                            "file": name,
                            "bytes": path.stat().st_size,
                            "purpose": record.get("purpose", "uploaded or built-in GLB asset"),
                            "expected_gate": record.get("expected_gate"),
                            "source_type": record.get("source_type", "SELF_CREATED"),
                        }
                    )
        return {"assets": items}

    def decide_pipeline(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_payload_keys(
            payload,
            {"job_id", "profile", "decision", "approval_actor", "fault_injection"},
        )
        profile_path = self._resolve_under(self.profile_root, self._required_string(payload, "profile"))
        actor = payload.get("approval_actor", "gateway-user")
        if not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
            raise GatewayError("INVALID_REQUEST", "'approval_actor' must be a non-empty string of at most 128 characters")
        return decide_pending_job(
            self.jobs_root,
            QualityProfile.load(profile_path),
            self._required_string(payload, "job_id"),
            self._required_string(payload, "decision"),
            approval_actor=actor,
            fault_injection=payload.get("fault_injection"),
        )

    def upload_asset(self, filename: str, data: bytes) -> dict[str, Any]:
        clean_name = filename.strip()
        if (
            not clean_name
            or len(clean_name) > 160
            or Path(clean_name).name != clean_name
            or any(ord(character) < 32 for character in clean_name)
        ):
            raise GatewayError("INVALID_FILENAME", "upload filename must be a plain file name")
        if Path(clean_name).suffix.lower() != ".glb":
            raise GatewayError("UNSUPPORTED_FORMAT", "SceneGuard MVP only accepts .glb files")
        if not data:
            raise GatewayError("INVALID_UPLOAD", "uploaded GLB is empty")
        if len(data) > MAX_UPLOAD_BYTES:
            raise GatewayError(
                "UPLOAD_TOO_LARGE",
                f"uploaded GLB exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit",
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        try:
            document = parse_glb_bytes(data)
        except GlbFormatError as exc:
            raise GatewayError("INVALID_GLB", f"uploaded file is not a valid GLB 2.0 file: {exc}") from exc

        upload_id = f"upload-{uuid4().hex[:16]}"
        directory = self.jobs_root / ".uploads"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{upload_id}.glb"
        temporary = directory / f"{upload_id}.tmp"
        temporary.write_bytes(data)
        os.replace(temporary, target)
        metadata = {
            "schema_version": "0.1",
            "upload_id": upload_id,
            "asset_ref": f"upload:{upload_id}",
            "filename": clean_name,
            "bytes": len(data),
            "sha256": document.sha256,
        }
        self._write_idempotency_receipt(directory / f"{upload_id}.json", metadata)
        return metadata

    def asset_content(self, asset_ref: str) -> tuple[bytes, str, str]:
        path = self._resolve_asset(asset_ref)
        data = path.read_bytes()
        return data, path.name, self._sha256(path)

    def job_asset_content(self, job_id: str, asset_kind: str) -> tuple[bytes, str, str]:
        if SAFE_ID.fullmatch(job_id) is None:
            raise GatewayError("INVALID_JOB_ID", "invalid job id", HTTPStatus.FORBIDDEN)
        relative_by_kind = {
            "original": Path("original/asset.glb"),
            "working": Path("working/candidate.glb"),
            "published": Path("published/asset.glb"),
        }
        relative = relative_by_kind.get(asset_kind)
        if relative is None:
            raise GatewayError("INVALID_ASSET_KIND", "asset kind must be original, working or published")
        job_root = (self.jobs_root / job_id).resolve()
        path = (job_root / relative).resolve()
        if not job_root.is_relative_to(self.jobs_root) or not path.is_relative_to(job_root):
            raise GatewayError("PATH_OUT_OF_SCOPE", "job asset path escapes jobs root", HTTPStatus.FORBIDDEN)
        if not path.is_file():
            raise GatewayError("NOT_FOUND", f"{asset_kind} asset not found", HTTPStatus.NOT_FOUND)
        data = path.read_bytes()
        return data, f"{job_id}-{asset_kind}.glb", self._sha256(path)

    def audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_payload_keys(payload, {"asset", "profile", "job_id"})
        asset = self._resolve_asset(self._required_string(payload, "asset"))
        profile_path = self._resolve_under(self.profile_root, self._required_string(payload, "profile"))
        if asset.suffix.lower() != ".glb":
            raise GatewayError("UNSUPPORTED_FORMAT", "SceneGuard MVP only accepts .glb files")
        profile = QualityProfile.load(profile_path)
        return audit_asset(asset, profile, job_id=self._optional_job_id(payload, "gateway")).to_dict()

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_payload_keys(payload, {"asset", "profile", "job_id"})
        asset = self._resolve_asset(self._required_string(payload, "asset"))
        profile_path = self._resolve_under(self.profile_root, self._required_string(payload, "profile"))
        profile = QualityProfile.load(profile_path)
        workspace, report = create_job_workspace(
            asset,
            jobs_root=self.jobs_root,
            profile=profile,
            job_id=self._optional_job_id(payload, None),
        )
        return {
            "job_id": workspace.job_id,
            "gate_state": report["summary"]["gate_state"],
            "artifacts": {
                "audit_report": f"{workspace.job_id}/artifacts/audit_report.json",
                "trace": f"{workspace.job_id}/artifacts/trace.jsonl",
            },
        }

    def plan_repair(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_payload_keys(payload, {"job_id", "profile"})
        profile = self._stage_profile(payload)
        with self._stage_lock:
            return self._run_stage(plan_job, profile, self._required_string(payload, "job_id"))

    def execute_repair(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_payload_keys(payload, {"job_id", "profile", "plan_id"})
        profile = self._stage_profile(payload)
        with self._stage_lock:
            return self._run_stage(
                execute_job,
                profile,
                self._required_string(payload, "job_id"),
                self._required_string(payload, "plan_id"),
            )

    def verify_regression(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_payload_keys(payload, {"job_id", "profile", "plan_id"})
        profile = self._stage_profile(payload)
        with self._stage_lock:
            return self._run_stage(
                verify_job,
                profile,
                self._required_string(payload, "job_id"),
                self._required_string(payload, "plan_id"),
            )

    def _stage_profile(self, payload: dict[str, Any]) -> QualityProfile:
        profile_path = self._resolve_under(self.profile_root, self._required_string(payload, "profile"))
        return QualityProfile.load(profile_path)

    def _run_stage(self, function: Any, profile: QualityProfile, job_id: str, *args: str) -> dict[str, Any]:
        if SAFE_ID.fullmatch(job_id) is None:
            raise GatewayError("INVALID_JOB_ID", "job id has an invalid format")
        try:
            return function(self.jobs_root, profile, job_id, *args)
        except FileNotFoundError as exc:
            raise GatewayError("NOT_FOUND", str(exc), HTTPStatus.NOT_FOUND) from exc
        except ValueError as exc:
            raise GatewayError("STAGE_PRECONDITION_FAILED", str(exc), HTTPStatus.CONFLICT) from exc

    def run_pipeline(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._run_pipeline(payload)

    def run_pipeline_request(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        input_sha256 = self._canonical_sha256(payload)
        context = {
            "request_id": request_id,
            "input_sha256": input_sha256,
            "idempotency_key_sha256": (
                hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest() if idempotency_key else None
            ),
        }
        if idempotency_key is None:
            result = self._run_pipeline(payload, request_context=context)
            return {
                "result": result,
                "meta": {
                    "request_id": request_id,
                    "input_sha256": input_sha256,
                    "output_sha256": self._canonical_sha256(result),
                    "idempotency": "NOT_REQUESTED",
                    "replayed": False,
                },
            }
        if SAFE_IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
            raise GatewayError("INVALID_IDEMPOTENCY_KEY", "Idempotency-Key has an invalid format")

        key_sha256 = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        receipt_dir = self.jobs_root / ".idempotency"
        receipt = receipt_dir / f"{key_sha256}.json"
        with self._idempotency_lock:
            existing = self._read_idempotency_receipt(receipt)
            if existing is not None:
                if existing.get("input_sha256") != input_sha256:
                    raise GatewayError(
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency-Key was already used with a different request payload",
                        HTTPStatus.CONFLICT,
                    )
                if existing.get("state") == "COMPLETED":
                    result = existing.get("result")
                    if not isinstance(result, dict) or existing.get("output_sha256") != self._canonical_sha256(result):
                        raise GatewayError(
                            "IDEMPOTENCY_RECEIPT_CORRUPT",
                            "stored idempotency receipt failed integrity validation",
                            HTTPStatus.INTERNAL_SERVER_ERROR,
                        )
                    return {
                        "result": result,
                        "meta": {
                            "request_id": request_id,
                            "original_request_id": existing.get("request_id"),
                            "input_sha256": input_sha256,
                            "output_sha256": existing["output_sha256"],
                            "idempotency": "REPLAY",
                            "replayed": True,
                        },
                    }
                if existing.get("state") == "FAILED":
                    error = existing.get("error") if isinstance(existing.get("error"), dict) else {}
                    try:
                        status = HTTPStatus(int(error.get("status", HTTPStatus.INTERNAL_SERVER_ERROR)))
                    except ValueError:
                        status = HTTPStatus.INTERNAL_SERVER_ERROR
                    raise GatewayError(
                        str(error.get("code", "IDEMPOTENT_REQUEST_FAILED")),
                        str(error.get("message", "the original idempotent request failed")),
                        status,
                    )
                recovered = self._recover_completed_job(existing)
                if recovered is not None:
                    completed = {
                        **existing,
                        "state": "COMPLETED",
                        "result": recovered,
                        "output_sha256": self._canonical_sha256(recovered),
                    }
                    self._write_idempotency_receipt(receipt, completed)
                    return {
                        "result": recovered,
                        "meta": {
                            "request_id": request_id,
                            "original_request_id": existing.get("request_id"),
                            "input_sha256": input_sha256,
                            "output_sha256": completed["output_sha256"],
                            "idempotency": "RECOVERED_REPLAY",
                            "replayed": True,
                        },
                    }
                raise GatewayError(
                    "IDEMPOTENCY_IN_PROGRESS",
                    "a prior request with this Idempotency-Key has not completed",
                    HTTPStatus.CONFLICT,
                )

            receipt_dir.mkdir(parents=True, exist_ok=True)
            pending = {
                "schema_version": "0.1",
                "state": "PENDING",
                "request_id": request_id,
                "input_sha256": input_sha256,
                "job_id": payload.get("job_id"),
            }
            self._write_idempotency_receipt(receipt, pending)
            try:
                result = self._run_pipeline(payload, request_context=context)
            except Exception as exc:
                failed = {
                    **pending,
                    "state": "FAILED",
                    "error": {
                        "code": exc.code if isinstance(exc, GatewayError) else "INTERNAL_ERROR",
                        "message": str(exc),
                        "status": int(exc.status) if isinstance(exc, GatewayError) else 500,
                    },
                }
                self._write_idempotency_receipt(receipt, failed)
                raise
            completed = {
                **pending,
                "state": "COMPLETED",
                "result": result,
                "output_sha256": self._canonical_sha256(result),
            }
            self._write_idempotency_receipt(receipt, completed)
            return {
                "result": result,
                "meta": {
                    "request_id": request_id,
                    "input_sha256": input_sha256,
                    "output_sha256": completed["output_sha256"],
                    "idempotency": "STORED",
                    "replayed": False,
                },
            }

    def _run_pipeline(
        self,
        payload: dict[str, Any],
        *,
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_payload_keys(
            payload,
            {
                "asset",
                "profile",
                "job_id",
                "auto_repair",
                "fault_injection",
                "approval_decision",
                "approval_actor",
            },
        )
        asset = self._resolve_asset(self._required_string(payload, "asset"))
        profile_path = self._resolve_under(self.profile_root, self._required_string(payload, "profile"))
        auto_repair = payload.get("auto_repair", True)
        if not isinstance(auto_repair, bool):
            raise GatewayError("INVALID_REQUEST", "'auto_repair' must be a boolean")
        approval_actor = payload.get("approval_actor", "gateway-user")
        if not isinstance(approval_actor, str) or not approval_actor.strip() or len(approval_actor) > 128:
            raise GatewayError("INVALID_REQUEST", "'approval_actor' must be a non-empty string of at most 128 characters")
        profile = QualityProfile.load(profile_path)
        return run_job(
            asset,
            profile=profile,
            jobs_root=self.jobs_root,
            job_id=self._optional_job_id(payload, None),
            auto_repair=auto_repair,
            fault_injection=payload.get("fault_injection"),
            approval_decision=payload.get("approval_decision"),
            approval_actor=approval_actor,
            request_context=request_context,
        )

    def _read_idempotency_receipt(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GatewayError(
                "IDEMPOTENCY_RECEIPT_CORRUPT",
                f"stored idempotency receipt is invalid: {exc}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            ) from exc
        if not isinstance(payload, dict):
            raise GatewayError(
                "IDEMPOTENCY_RECEIPT_CORRUPT",
                "stored idempotency receipt must be a JSON object",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        return payload

    @staticmethod
    def _write_idempotency_receipt(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _recover_completed_job(self, receipt: dict[str, Any]) -> dict[str, Any] | None:
        job_id = receipt.get("job_id")
        if not isinstance(job_id, str) or SAFE_ID.fullmatch(job_id) is None:
            return None
        decision = self.jobs_root / job_id / "artifacts" / "gate_decision.json"
        if not decision.is_file():
            return None
        try:
            payload = json.loads(decision.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) and payload.get("job_id") == job_id else None

    def list_artifacts(self, job_id: str) -> dict[str, Any]:
        directory = self._artifact_directory(job_id)
        items = []
        for path in sorted(directory.iterdir()):
            if not path.is_file() or SAFE_ARTIFACT.fullmatch(path.name) is None:
                continue
            size = path.stat().st_size
            items.append(
                {
                    "name": path.name,
                    "bytes": size,
                    "sha256": self._sha256(path),
                    "readable": size <= MAX_ARTIFACT_BYTES,
                }
            )
        return {"job_id": job_id, "artifacts": items}

    def read_artifact(self, job_id: str, artifact_name: str) -> dict[str, Any]:
        if SAFE_ARTIFACT.fullmatch(artifact_name) is None:
            raise GatewayError("INVALID_ARTIFACT_ID", "artifact must be a JSON/JSONL file id", HTTPStatus.FORBIDDEN)
        directory = self._artifact_directory(job_id)
        path = (directory / artifact_name).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise GatewayError("NOT_FOUND", "artifact not found", HTTPStatus.NOT_FOUND)
        size = path.stat().st_size
        if size > MAX_ARTIFACT_BYTES:
            raise GatewayError("ARTIFACT_TOO_LARGE", "artifact exceeds the 2 MiB read limit", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        text = path.read_text(encoding="utf-8")
        try:
            content = (
                [json.loads(line) for line in text.splitlines() if line.strip()]
                if path.suffix == ".jsonl"
                else json.loads(text)
            )
        except json.JSONDecodeError as exc:
            raise GatewayError("INVALID_ARTIFACT", f"artifact JSON is invalid: {exc}") from exc
        return {
            "job_id": job_id,
            "artifact": artifact_name,
            "bytes": size,
            "sha256": self._sha256(path),
            "content": content,
        }

    def _artifact_directory(self, job_id: str) -> Path:
        if SAFE_ID.fullmatch(job_id) is None:
            raise GatewayError("INVALID_JOB_ID", "invalid job id", HTTPStatus.FORBIDDEN)
        job_root = (self.jobs_root / job_id).resolve()
        if not job_root.is_relative_to(self.jobs_root):
            raise GatewayError("PATH_OUT_OF_SCOPE", "job path escapes jobs root", HTTPStatus.FORBIDDEN)
        directory = job_root / "artifacts"
        if not directory.is_dir():
            raise GatewayError("NOT_FOUND", "job artifacts not found", HTTPStatus.NOT_FOUND)
        return directory

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _canonical_sha256(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _required_string(payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise GatewayError("INVALID_REQUEST", f"'{field}' must be a non-empty string")
        return value

    @staticmethod
    def _validate_payload_keys(payload: dict[str, Any], allowed: set[str]) -> None:
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise GatewayError("INVALID_REQUEST", "unknown request fields: " + ", ".join(unknown))

    @staticmethod
    def _optional_job_id(payload: dict[str, Any], default: str | None) -> str | None:
        value = payload.get("job_id", default)
        if value is None:
            return None
        if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
            raise GatewayError("INVALID_JOB_ID", "job id has an invalid format")
        return value

    @staticmethod
    def _resolve_under(root: Path, relative: str) -> Path:
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise GatewayError("PATH_OUT_OF_SCOPE", "requested path escapes its configured root", HTTPStatus.FORBIDDEN)
        if not candidate.is_file():
            raise GatewayError("NOT_FOUND", f"file not found: {relative}", HTTPStatus.NOT_FOUND)
        return candidate

    def _resolve_asset(self, asset_ref: str) -> Path:
        if asset_ref.startswith("upload:"):
            upload_id = asset_ref.removeprefix("upload:")
            if not re.fullmatch(r"upload-[a-f0-9]{16}", upload_id):
                raise GatewayError("INVALID_ASSET_REF", "uploaded asset reference has an invalid format")
            upload_root = (self.jobs_root / ".uploads").resolve()
            candidate = (upload_root / f"{upload_id}.glb").resolve()
            if not candidate.is_relative_to(upload_root):
                raise GatewayError("PATH_OUT_OF_SCOPE", "uploaded asset path escapes upload root")
            if not candidate.is_file():
                raise GatewayError("NOT_FOUND", "uploaded asset not found", HTTPStatus.NOT_FOUND)
            return candidate
        return self._resolve_under(self.asset_root, asset_ref)


def make_handler(service: GatewayService, api_token: str | None = None) -> type[BaseHTTPRequestHandler]:
    class SceneGuardHandler(BaseHTTPRequestHandler):
        server_version = "SceneGuardToolGateway/0.1"

        def do_GET(self) -> None:
            request_id = self._request_id()
            parsed = urlparse(self.path)
            route = parsed.path
            if not self._authorized(route):
                return
            if route == "/":
                self._send_html(HTTPStatus.OK, DASHBOARD_HTML)
            elif route == "/health":
                self._send(HTTPStatus.OK, service.health())
            elif route == "/v1/profiles":
                self._send(HTTPStatus.OK, service.profiles())
            elif route == "/v1/assets":
                self._send(HTTPStatus.OK, service.assets())
            elif route == "/v1/assets/content":
                try:
                    asset_ref = parse_qs(parsed.query).get("ref", [""])[0]
                    data, filename, sha256 = service.asset_content(asset_ref)
                    self._send_binary(HTTPStatus.OK, data, filename, sha256)
                except GatewayError as exc:
                    self._send(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
            elif match := re.fullmatch(r"/v1/jobs/([A-Za-z0-9._-]+)/artifacts", route):
                try:
                    self._send(HTTPStatus.OK, service.list_artifacts(match.group(1)))
                except GatewayError as exc:
                    self._send(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
            elif match := re.fullmatch(r"/v1/jobs/([A-Za-z0-9._-]+)/artifacts/([A-Za-z0-9._-]+)", route):
                try:
                    self._send(HTTPStatus.OK, service.read_artifact(match.group(1), match.group(2)))
                except GatewayError as exc:
                    self._send(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
            elif match := re.fullmatch(
                r"/v1/jobs/([A-Za-z0-9._-]+)/assets/(original|working|published)", route
            ):
                try:
                    data, filename, sha256 = service.job_asset_content(match.group(1), match.group(2))
                    self._send_binary(HTTPStatus.OK, data, filename, sha256)
                except GatewayError as exc:
                    self._send(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
            else:
                self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": {"code": "NOT_FOUND", "message": route}})

        def do_POST(self) -> None:
            request_id = self._request_id()
            route = urlparse(self.path).path
            if not self._authorized(route):
                return
            try:
                if route == "/v1/assets/upload":
                    filename = unquote(self.headers.get("X-File-Name", ""))
                    result = service.upload_asset(filename, self._read_binary(MAX_UPLOAD_BYTES))
                    meta = {
                        "request_id": request_id,
                        "input_sha256": result["sha256"],
                        "output_sha256": service._canonical_sha256(result),
                    }
                    self._send(HTTPStatus.CREATED, {"ok": True, "result": result, "meta": meta})
                    return
                payload = self._read_json()
                if route == "/v1/tools/asset.audit":
                    result = service.audit(payload)
                elif route == "/v1/jobs":
                    result = service.create_job(payload)
                elif route == "/v1/tools/repair.plan":
                    result = service.plan_repair(payload)
                elif route == "/v1/tools/repair.execute":
                    result = service.execute_repair(payload)
                elif route == "/v1/tools/regression.verify":
                    result = service.verify_regression(payload)
                elif route == "/v1/pipeline/run":
                    outcome = service.run_pipeline_request(
                        payload,
                        request_id=request_id,
                        idempotency_key=self.headers.get("Idempotency-Key"),
                    )
                    self._send(HTTPStatus.OK, {"ok": True, **outcome})
                    return
                elif route == "/v1/pipeline/decide":
                    result = service.decide_pipeline(payload)
                else:
                    raise GatewayError("NOT_FOUND", f"unknown route: {route}", HTTPStatus.NOT_FOUND)
                meta = {
                    "request_id": request_id,
                    "input_sha256": service._canonical_sha256(payload),
                    "output_sha256": service._canonical_sha256(result),
                }
                self._send(HTTPStatus.OK, {"ok": True, "result": result, "meta": meta})
            except GatewayError as exc:
                self._send(exc.status, {"ok": False, "error": {"code": exc.code, "message": str(exc)}})
            except json.JSONDecodeError as exc:
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": {"code": "INVALID_JSON", "message": str(exc)}},
                )
            except Exception as exc:
                self._send(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": str(exc)}},
                )

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            if length > MAX_REQUEST_BYTES:
                raise GatewayError("REQUEST_TOO_LARGE", "request body exceeds 1 MiB")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise GatewayError("INVALID_REQUEST", "JSON body must be an object")
            return payload

        def _read_binary(self, maximum: int) -> bytes:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise GatewayError("INVALID_REQUEST", "Content-Length must be an integer") from exc
            if length <= 0:
                raise GatewayError("INVALID_UPLOAD", "upload body is empty")
            if length > maximum:
                raise GatewayError("UPLOAD_TOO_LARGE", "uploaded GLB exceeds the configured limit", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return self.rfile.read(length)

        def _authorized(self, route: str) -> bool:
            if not route.startswith("/v1/") or api_token is None:
                return True
            supplied = self.headers.get("Authorization", "")
            if hmac.compare_digest(supplied, f"Bearer {api_token}"):
                return True
            self._send(
                HTTPStatus.UNAUTHORIZED,
                {"ok": False, "error": {"code": "UNAUTHORIZED", "message": "valid Bearer token required"}},
            )
            return False

        def _request_id(self) -> str:
            cached = getattr(self, "_request_id_value", None)
            if cached:
                return cached
            supplied = self.headers.get("X-Request-ID", "")
            self._request_id_value = (
                supplied if SAFE_REQUEST_ID.fullmatch(supplied) is not None else f"req-{uuid4().hex}"
            )
            return self._request_id_value

        def _send(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", self._request_id())
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, status: HTTPStatus, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", self._request_id())
            self.end_headers()
            self.wfile.write(body)

        def _send_binary(self, status: HTTPStatus, body: bytes, filename: str, sha256: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'inline; filename="{filename}"')
            self.send_header("ETag", f'"sha256:{sha256}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Request-ID", self._request_id())
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"{self.address_string()} - {fmt % args}")

    return SceneGuardHandler


def run_gateway(
    host: str,
    port: int,
    asset_root: str | Path,
    profile_root: str | Path,
    jobs_root: str | Path,
    api_token: str | None = None,
) -> None:
    validate_gateway_security(host, api_token)
    service = GatewayService(asset_root=asset_root, profile_root=profile_root, jobs_root=jobs_root)
    server = ThreadingHTTPServer((host, port), make_handler(service, api_token=api_token))
    print(f"SceneGuard Tool Gateway listening on http://{host}:{port}")
    print("Open / for the demo; API: GET /health, GET /v1/profiles, GET /v1/assets, POST /v1/pipeline/run")
    server.serve_forever()


def validate_gateway_security(host: str, api_token: str | None) -> None:
    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    if host not in loopback_hosts and not api_token:
        raise ValueError("non-loopback Gateway binding requires an API token from the environment")
