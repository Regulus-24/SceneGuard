---
name: mesh-validate
description: Measure primitive and triangle budgets from valid GLB accessors; future versions will add deterministic geometry defect checks.
metadata:
  version: "0.1.0"
  maturity: partial
  type: custom-skill
  input_schema: schemas/asset-audit-input.schema.json
  output_schema: schemas/audit-report.schema.json
  dependency: sceneguard.audit.AssetAuditor
  dependency_version: "sceneguard@0.1.0; GLB 2.0; Python>=3.11"
  timeout_seconds: 60
---

# Mesh Validate

## Implemented scope

- Primitive count;
- triangle count for TRIANGLES, TRIANGLE_STRIP and TRIANGLE_FAN;
- POSITION/indices accessor reference and byte-bound validation;
- embedded POSITION/indices decoding;
- non-finite POSITION and zero-area/repeated-index triangle detection;
- Profile triangle-budget Finding.

## Not implemented yet

Duplicate vertices, local normal flips, non-manifold topology and any mesh repair. These require additional independent Golden tests.

## Input/output

Uses the same `asset.audit` input and contributes measurements/Findings to `AuditReport@0.1`.

## Failure and security

Invalid or out-of-bounds accessors fail closed. No file writes and no model-generated measurements.

## Reuse

The Skill can be extended behind the same Finding Schema without changing Agent contracts.
