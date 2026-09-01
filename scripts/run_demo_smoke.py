from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def _json_request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
) -> tuple[dict, dict[str, str]]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(base_url.rstrip("/") + path, data=data, headers=request_headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        body = json.load(response)
        response_headers = {key.lower(): value for key, value in response.headers.items()}
    return body, response_headers


def _bytes_request(base_url: str, path: str, *, timeout: float = 10) -> tuple[bytes, dict[str, str]]:
    request = Request(base_url.rstrip("/") + path, headers={"Accept": "model/gltf-binary"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
        response_headers = {key.lower(): value for key, value in response.headers.items()}
    return data, response_headers


def run_smoke(base_url: str, *, timeout: float = 10) -> dict:
    started = time.monotonic()
    suffix = f"{int(time.time())}-{time.perf_counter_ns() % 1_000_000:06d}"
    job_id = f"initial-smoke-{suffix}"
    request_id = f"initial-smoke-request-{suffix}"
    idempotency_key = f"initial-smoke-key-{suffix}"
    checks: list[dict] = []

    def record(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "passed": bool(passed), "detail": detail})

    health, _ = _json_request(base_url, "/health", timeout=timeout)
    record("gateway.health", health.get("ok") is True, f"version={health.get('version', 'unknown')}")

    assets, _ = _json_request(base_url, "/v1/assets", timeout=timeout)
    asset_names = {item.get("file") for item in assets.get("assets", []) if isinstance(item, dict)}
    record(
        "demo.asset",
        "mixed_valid_degenerate.glb" in asset_names,
        "mixed_valid_degenerate.glb is listed",
    )

    profiles, _ = _json_request(base_url, "/v1/profiles", timeout=timeout)
    profile_names = {item.get("file") for item in profiles.get("profiles", []) if isinstance(item, dict)}
    profile = "web-realtime-v0.5-visual-demo.json"
    record("demo.profile", profile in profile_names, f"{profile} is listed")

    payload = {
        "asset": "mixed_valid_degenerate.glb",
        "profile": profile,
        "job_id": job_id,
        "auto_repair": True,
    }
    pipeline, response_headers = _json_request(
        base_url,
        "/v1/pipeline/run",
        method="POST",
        payload=payload,
        headers={"X-Request-ID": request_id, "Idempotency-Key": idempotency_key},
        timeout=max(timeout, 30),
    )
    result = pipeline.get("result", {})
    meta = pipeline.get("meta", {})
    record(
        "pipeline.repaired_pass",
        pipeline.get("ok") is True
        and result.get("gate_state") == "REPAIRED_PASS"
        and result.get("published") is True,
        f"gate_state={result.get('gate_state')}; published={result.get('published')}",
    )
    record(
        "pipeline.request_contract",
        response_headers.get("x-request-id") == request_id
        and meta.get("request_id") == request_id
        and isinstance(meta.get("input_sha256"), str)
        and isinstance(meta.get("output_sha256"), str),
        "request id and input/output hashes are present",
    )

    original, original_headers = _bytes_request(
        base_url,
        f"/v1/jobs/{quote(job_id)}/assets/original",
        timeout=timeout,
    )
    published, published_headers = _bytes_request(
        base_url,
        f"/v1/jobs/{quote(job_id)}/assets/published",
        timeout=timeout,
    )
    record(
        "preview.before_after",
        original_headers.get("content-type", "").startswith("model/gltf-binary")
        and published_headers.get("content-type", "").startswith("model/gltf-binary")
        and hashlib.sha256(original).hexdigest() != hashlib.sha256(published).hexdigest(),
        f"original={len(original)} bytes; published={len(published)} bytes; hashes differ",
    )

    artifacts, _ = _json_request(base_url, f"/v1/jobs/{quote(job_id)}/artifacts", timeout=timeout)
    artifact_names = {
        item.get("name") or item.get("file")
        for item in artifacts.get("artifacts", [])
        if isinstance(item, dict)
    }
    expected = {"gate_decision.json", "trace.jsonl", "execution_report.json", "regression_report.json"}
    record("evidence.artifacts", expected.issubset(artifact_names), f"expected={sorted(expected)}")

    gate, _ = _json_request(
        base_url,
        f"/v1/jobs/{quote(job_id)}/artifacts/gate_decision.json",
        timeout=timeout,
    )
    gate_content = gate.get("content", {})
    record(
        "evidence.gate",
        gate_content.get("gate_state") == "REPAIRED_PASS" and gate_content.get("published") is True,
        f"gate_state={gate_content.get('gate_state')}; published={gate_content.get('published')}",
    )

    passed = all(item["passed"] for item in checks)
    return {
        "schema_version": "0.1",
        "status": "PASS" if passed else "FAIL",
        "base_url": base_url,
        "job_id": job_id,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "checks": checks,
        "next_action": "Open the demo UI and record the fixed workflow." if passed else "Fix failed checks before recording.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed SceneGuard initial-round demo smoke test")
    parser.add_argument("--base-url", default="http://127.0.0.1:18096")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run_smoke(args.base_url, timeout=args.timeout)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": "0.1",
            "status": "FAIL",
            "base_url": args.base_url,
            "error": f"{type(exc).__name__}: {exc}",
            "next_action": "Start the demo with scripts/start_initial_demo.ps1, then retry.",
        }
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
