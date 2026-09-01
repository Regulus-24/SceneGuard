---
name: package-audit
description: Deterministically validate GLB 2.0 structure, single-file policy, byte bounds, references, hashes and profile budgets.
metadata:
  version: "0.1.0"
  maturity: implemented
  type: external-tool-wrapper
  input_schema: schemas/asset-audit-input.schema.json
  output_schema: schemas/audit-report.schema.json
  dependency: sceneguard.audit.AssetAuditor
  dependency_version: "sceneguard@0.1.0; GLB 2.0; Python>=3.11"
  timeout_seconds: 60
---

# Package Audit

## Call condition

Asset Auditor or Regression Verifier has a `.glb` path inside the configured Asset root and a valid Profile.

## Input

```json
{"asset":"clean_triangle.glb","profile":"web-realtime-v0.2.json","job_id":"job-xxx"}
```

## Output

`AuditReport@0.1`，包含哈希、测量值、Finding、完整/未完整检查和 Gate 摘要。

## Tool

`POST /v1/tools/asset.audit` → `sceneguard.audit.AssetAuditor` → Python standard library GLB parser.

## Failure and security

Invalid GLB becomes an ERROR Finding with remaining checks incomplete. Asset/Profile paths are resolved under configured roots and path escape is denied. The operation is read-only.

## Reuse

Can be used in local CLI, CI asset gate, AgentTeams Worker or a future MCP adapter with the same JSON contract.
