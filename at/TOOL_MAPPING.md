# SceneGuard HTTP/MCP Tool Mapping

The v0.2.5 Tool Gateway is HTTP JSON. The machine-readable source is
`at/http_api.v0.1.json`; this page explains how its fifteen implemented routes map to a
future MCP adapter. No route below should be described as native MCP today.

| Implemented HTTP route | Current function | Future MCP tool/resource |
|---|---|---|
| `GET /health` | Gateway health/version | `sceneguard.health` |
| `GET /v1/assets` | List configured GLB samples | `sceneguard.asset.list` |
| `GET /v1/assets/content` | Stream a validated built-in or uploaded GLB for preview | `sceneguard.asset.read` |
| `GET /v1/profiles` | List validated Profile versions | `sceneguard.profile.list` |
| `POST /v1/assets/upload` | Validate and store one bounded user GLB | `sceneguard.asset.upload` |
| `POST /v1/tools/asset.audit` | Read-only deterministic GLB audit | `sceneguard.asset.audit` |
| `POST /v1/jobs` | Create isolated Job and first audit | `sceneguard.job.create` |
| `POST /v1/tools/repair.plan` | Freeze one profile/hash-bound PatchPlan | `sceneguard.repair.plan` |
| `POST /v1/tools/repair.execute` | Execute only the exact frozen PatchPlan; cannot publish | `sceneguard.repair.execute` |
| `POST /v1/tools/regression.verify` | Independently re-audit and exclusively publish or roll back | `sceneguard.regression.verify` |
| `POST /v1/pipeline/run` | Approval/repair/verify/release-or-rollback pipeline | `sceneguard.pipeline.run` |
| `POST /v1/pipeline/decide` | Decide the exact pending PatchPlan and continue the same Job | `sceneguard.pipeline.decide` |
| `GET /v1/jobs/{job_id}/artifacts` | List safe Job evidence | `sceneguard.job.artifacts.list` |
| `GET /v1/jobs/{job_id}/artifacts/{artifact_id}` | Read one bounded JSON/JSONL artifact | `sceneguard.job.artifact.read` |
| `GET /v1/jobs/{job_id}/assets/{asset_kind}` | Stream original, working or published GLB for comparison | `sceneguard.job.asset.read` |

## Current request contract

The audit and Job-create routes accept `schemas/asset-audit-input.schema.json`. Pipeline
execution accepts `schemas/pipeline-run-input.schema.json`; a pending L2 plan continues
through `schemas/pipeline-decision-input.schema.json`. Pipeline-run requires `asset`
and `profile`; `job_id` is optional. Unknown fields and wrong primitive types fail with
`INVALID_REQUEST` instead of being silently ignored or coerced.

```json
{
  "asset": "clean_triangle.glb",
  "profile": "web-realtime-v0.2.json",
  "job_id": "optional-id"
}
```

Paths are relative to configured roots. Path escape, missing files and non-GLB input
fail closed. Every response carries `X-Request-ID`. POST responses include canonical
input/output SHA-256. `POST /v1/pipeline/run` additionally accepts `Idempotency-Key` and
persists replay receipts without storing the raw key.

The decision route requires the pending `job_id`, its original `profile`, and an
`APPROVE` or `REJECT` decision. The gateway verifies the stored Plan ID, asset hash and
working copy before it records the decision or allows Executor to continue.

All `/v1/` routes require Bearer authentication when a token is configured, and a
non-loopback bind is rejected unless such a token is supplied. `/` and `/health` remain
public for local UI and liveness. This is Demo-level service authentication, not a
short-lived per-Worker identity or enterprise authorization system.

The three staged routes are the AgentTeams control surface: Planner output binds the
Executor to one Plan ID and asset hash; Executor output cannot publish; Verifier must
consume both evidence records and alone may publish or roll back. The legacy
`pipeline.run` route remains for the single-process demo and compatibility tests.

## MCP migration cost

1. Map each route to the declared MCP `name`, `description` and `inputSchema`;
2. keep the versioned Audit/Patch/Regression/Gate schemas as structured content;
3. replace Demo Bearer authentication with gateway-managed Worker credentials;
4. forward Trace ID, caller and scope to the existing evidence log;
5. add MCP transport tests while retaining the same Golden GLB and pipeline tests.
