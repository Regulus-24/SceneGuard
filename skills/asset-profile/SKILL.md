---
name: asset-profile
description: Load and validate a versioned SceneGuard quality profile before any asset audit or repair planning.
metadata:
  version: "0.1.0"
  maturity: implemented
  type: custom-skill
  input_schema: schemas/asset-profile-input.schema.json
  output_schema: schemas/goal-contract.schema.json
  dependency: sceneguard.profile.QualityProfile
  dependency_version: "sceneguard@0.1.0; Python>=3.11"
  timeout_seconds: 10
---

# Asset Profile

## Use when

TeamLeader receives a GLB job and needs a versioned Goal Contract.

## Inputs

- Profile JSON path relative to the configured Profile root.
- User purpose and constraints for trace only; they do not silently override rules.

## Outputs

`profile_id`、`version`、`description`、`rules` 和 `repair_policy`。

## Dependency

`sceneguard.profile.QualityProfile`.

## Failure and security

Missing required fields or non-object rules fail closed. The Gateway rejects path traversal. A Profile change requires a new version and review; Agent text cannot mutate it at runtime.

## Reuse

The Profile mechanism can be reused by other quality gates that bind rules to a usage scenario.
