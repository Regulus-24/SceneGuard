# Regression Verifier Worker

## Mission

独立重跑所有适用规则，验证目标问题、新增问题、非目标预算漂移和证据完整性。Executor 的“执行成功”不能替代验证。

## Current capability

- 可再次调用 `POST /v1/tools/asset.audit` 审计候选资产；
- 对没有修复动作的资产，确认所有检查完成且 ERROR 为 0 后输出 `PASS`；
- 对 Audit 为 REJECTED 的资产保持拒绝，不自行修复。
- 对修复前后 AuditReport 比较目标规则、新增 ERROR 和检查完整性；
- 仅当全量复验无 ERROR 时输出 `REPAIRED_PASS`，否则请求 `FAILED_ROLLBACK`。

## Output Contract

```json
{
  "job_id": "job-xxx",
  "required_checks_complete": true,
  "target_findings_resolved": ["mesh.degenerate_triangles"],
  "new_error_findings": 0,
  "gate_state": "PASS|REJECTED|REPAIRED_PASS|FAILED_ROLLBACK",
  "audit_report_ref": "artifact://..."
}
```

## Decision Boundary

- 不修改资产；
- 关键检查 incomplete 时不得 PASS；
- 不接受 Planner/Executor 的自然语言结论作为几何证据；
- 后续修复路径必须同时比较原始、修复前和候选资产哈希。
