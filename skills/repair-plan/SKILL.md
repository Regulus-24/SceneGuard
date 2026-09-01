---
name: repair-plan
description: Build a whitelist-constrained, hash-bound PatchPlan without mutating the asset.
metadata:
  version: "0.1.0"
  maturity: implemented
  type: custom-skill
  input_schema: schemas/repair-plan-input.schema.json
  output_schema: schemas/patch-plan.schema.json
  dependency: sceneguard.planner.build_patch_plan
  dependency_version: "sceneguard@0.1.0; Python>=3.11"
  timeout_seconds: 10
---

# repair-plan

## Purpose

Convert a bound AuditReport into the smallest whitelist-constrained PatchPlan without
mutating any asset. The plan is a decision artifact, not permission to execute.

## Input contract

- AuditReport with asset SHA-256, Profile id/version, Findings and completed checks.
- The exact active Quality Profile and its repair/risk policy.
- A static rule-to-operation catalog implemented by the Planner.

## Output contract

Emit schema `0.1` with a unique `plan_id`, the audited `asset_sha256`, exact Profile
binding, state, risk level, approval flag, reason and ordered repair steps. Every READY
step must bind non-empty Finding ids, one enumerated operation, verification rules and
rollback triggers.

## Decision boundary

- `NO_ACTION`: no ERROR Findings; no steps and no approval.
- `READY`: every ERROR maps to an allowed operation and all contract validation passes.
- `MANUAL_ONLY`: any ERROR lacks a tested whitelist mapping or its risk is denied.
- Risk comes from the active Profile; the Planner cannot lower or relabel it.
- L2 execution requires a human decision bound to both `plan_id` and `asset_sha256`.
- Never invent operations, add opportunistic optimization, edit files, or publish.

## Failure behavior

Fail closed if the Profile is malformed, hashes or Profile bindings are invalid, step
ids collide, an operation is outside the whitelist, or verification/rollback bindings
are empty. A rejected plan must not reach the Repair Executor.
