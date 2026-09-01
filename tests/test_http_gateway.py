from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sceneguard.gateway import GatewayService, make_handler, validate_gateway_security  # noqa: E402


class HttpGatewayTests(unittest.TestCase):
    @staticmethod
    def post_json(base: str, route: str, payload: dict) -> dict:
        request = Request(
            f"{base}{route}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.load(response)["result"]

    def test_remote_binding_requires_environment_token(self) -> None:
        validate_gateway_security("127.0.0.1", None)
        with self.assertRaisesRegex(ValueError, "requires an API token"):
            validate_gateway_security("0.0.0.0", None)
        validate_gateway_security("0.0.0.0", "test-token")

    def test_api_token_protects_v1_routes(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = GatewayService(ROOT / "samples", ROOT / "profiles", jobs_root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, api_token="test-token"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(f"{base}/", timeout=2) as response:
                    dashboard = response.read().decode("utf-8")
                self.assertIn("可核验证据", dashboard)
                self.assertIn("trace.jsonl", dashboard)
                with urlopen(f"{base}/health", timeout=2) as response:
                    self.assertTrue(json.load(response)["ok"])
                with self.assertRaises(HTTPError) as context:
                    urlopen(f"{base}/v1/assets", timeout=2)
                self.assertEqual(context.exception.code, 401)
                request = Request(f"{base}/v1/assets", headers={"Authorization": "Bearer test-token"})
                with urlopen(request, timeout=2) as response:
                    assets = json.load(response)["assets"]
                self.assertIn("public/BoxVertexColors.glb", {item["file"] for item in assets})
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_health_and_audit_over_real_http(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = GatewayService(ROOT / "samples", ROOT / "profiles", jobs_root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(f"{base}/health", timeout=2) as response:
                    health = json.load(response)
                self.assertTrue(health["ok"])

                body = json.dumps(
                    {"asset": "clean_triangle.glb", "profile": "web-realtime-v0.1.json", "job_id": "http-test"}
                ).encode("utf-8")
                request = Request(
                    f"{base}/v1/tools/asset.audit",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request, timeout=2) as response:
                    result = json.load(response)
                self.assertTrue(result["ok"])
                self.assertEqual(result["result"]["summary"]["gate_state"], "PASS")

                service.run_pipeline(
                    {
                        "asset": "clean_triangle.glb",
                        "profile": "web-realtime-v0.2.json",
                        "job_id": "http-artifact",
                    }
                )
                with urlopen(f"{base}/v1/jobs/http-artifact/artifacts/gate_decision.json", timeout=2) as response:
                    artifact = json.load(response)
                self.assertEqual(artifact["content"]["gate_state"], "PASS")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_upload_and_preview_assets_over_real_http(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = GatewayService(ROOT / "samples", ROOT / "profiles", jobs_root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                source = (ROOT / "samples" / "degenerate_triangle.glb").read_bytes()
                request = Request(
                    f"{base}/v1/assets/upload",
                    data=source,
                    headers={
                        "Content-Type": "model/gltf-binary",
                        "X-File-Name": "%E7%94%A8%E6%88%B7%E6%A8%A1%E5%9E%8B.glb",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=2) as response:
                    self.assertEqual(response.status, 201)
                    upload = json.load(response)["result"]

                payload = {
                    "asset": upload["asset_ref"],
                    "profile": "web-realtime-v0.2.json",
                    "job_id": "http-uploaded-repair",
                }
                pipeline_request = Request(
                    f"{base}/v1/pipeline/run",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(pipeline_request, timeout=2) as response:
                    result = json.load(response)["result"]
                self.assertEqual(result["gate_state"], "REPAIRED_PASS")

                with urlopen(f"{base}/v1/jobs/http-uploaded-repair/assets/original", timeout=2) as response:
                    self.assertEqual(response.headers["Content-Type"], "model/gltf-binary")
                    self.assertEqual(response.read(), source)
                with urlopen(f"{base}/v1/jobs/http-uploaded-repair/assets/published", timeout=2) as response:
                    self.assertNotEqual(response.read(), source)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_four_role_staged_chain_over_real_http(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = GatewayService(ROOT / "samples", ROOT / "profiles", jobs_root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                created = self.post_json(
                    base,
                    "/v1/jobs",
                    {
                        "asset": "degenerate_triangle.glb",
                        "profile": "web-realtime-v0.2.json",
                        "job_id": "http-agent-chain",
                    },
                )
                self.assertEqual(created["gate_state"], "REJECTED")
                planned = self.post_json(
                    base,
                    "/v1/tools/repair.plan",
                    {"job_id": "http-agent-chain", "profile": "web-realtime-v0.2.json"},
                )
                plan_id = planned["patch_plan"]["plan_id"]
                executed = self.post_json(
                    base,
                    "/v1/tools/repair.execute",
                    {"job_id": "http-agent-chain", "profile": "web-realtime-v0.2.json", "plan_id": plan_id},
                )
                self.assertEqual(executed["execution"]["state"], "SUCCEEDED")
                self.assertFalse((Path(jobs_root) / "http-agent-chain" / "published" / "asset.glb").exists())
                verified = self.post_json(
                    base,
                    "/v1/tools/regression.verify",
                    {"job_id": "http-agent-chain", "profile": "web-realtime-v0.2.json", "plan_id": plan_id},
                )
                self.assertEqual(verified["decision"]["gate_state"], "REPAIRED_PASS")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_http_request_id_and_idempotency_contract(self) -> None:
        with tempfile.TemporaryDirectory() as jobs_root:
            service = GatewayService(ROOT / "samples", ROOT / "profiles", jobs_root)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}/v1/pipeline/run"
                payload = {
                    "asset": "clean_triangle.glb",
                    "profile": "web-realtime-v0.2.json",
                    "job_id": "http-idempotent",
                }
                body = json.dumps(payload).encode("utf-8")
                headers = {
                    "Content-Type": "application/json",
                    "X-Request-ID": "http-request-001",
                    "Idempotency-Key": "http-stable-key",
                }
                first_request = Request(url, data=body, headers=headers, method="POST")
                with urlopen(first_request, timeout=2) as response:
                    first = json.load(response)
                    self.assertEqual(response.headers["X-Request-ID"], "http-request-001")
                self.assertFalse(first["meta"]["replayed"])

                retry_headers = {**headers, "X-Request-ID": "http-request-002"}
                retry_request = Request(url, data=body, headers=retry_headers, method="POST")
                with urlopen(retry_request, timeout=2) as response:
                    replay = json.load(response)
                    self.assertEqual(response.headers["X-Request-ID"], "http-request-002")
                self.assertTrue(replay["meta"]["replayed"])
                self.assertEqual(first["result"], replay["result"])

                conflict = {**payload, "asset": "degenerate_triangle.glb"}
                conflict_request = Request(
                    url,
                    data=json.dumps(conflict).encode("utf-8"),
                    headers=retry_headers,
                    method="POST",
                )
                with self.assertRaises(HTTPError) as context:
                    urlopen(conflict_request, timeout=2)
                self.assertEqual(context.exception.code, 409)
                error = json.load(context.exception)
                self.assertEqual(error["error"]["code"], "IDEMPOTENCY_CONFLICT")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
