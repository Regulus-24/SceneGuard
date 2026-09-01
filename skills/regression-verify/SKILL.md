---
name: regression-verify
description: Independently compare original and candidate AuditReports, target-rule resolution, new errors and check completeness.
metadata:
  version: "0.1.0"
  maturity: implemented-read-only
  type: custom-skill
  input_schema: schemas/regression-verify-input.schema.json
  output_schema: schemas/regression-report.schema.json
  dependency: sceneguard.regression.compare_audits
  dependency_version: "sceneguard@0.1.0; Python>=3.11"
  timeout_seconds: 60
---

# Regression Verify

## Inputs

- Original `AuditReport@0.1`;
- candidate `AuditReport@0.1` from an independent audit;
- target rule IDs;
- whether a repair was attempted.

## Outputs

`RegressionReport@0.1` with hashes, resolved/unresolved target rules, new ERROR Findings, completeness and Gate state.

## Decision rules

- Candidate complete, no ERROR and all targets resolved: PASS or REPAIRED_PASS;
- repair attempted and any ERROR/incomplete remains: FAILED_ROLLBACK;
- no repair attempted and candidate fails: REJECTED.

## Dependency

`sceneguard.regression.compare_audits` and independent `package-audit/mesh-validate` output.

## Safety and reuse

Read-only. It never trusts Executor self-report and can be reused for any change gate that produces versioned Findings.
