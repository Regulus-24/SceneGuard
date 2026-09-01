# Repair Planner Worker

## Mission

把 Audit Finding 映射为最小 Patch Plan、风险等级、审批条件、验证规则和回滚条件。规划不等于执行。

## Current v0.2 behavior

`profiles/web-realtime-v0.2.json` 把 `mesh.degenerate_triangles` 映射为 L1 `remove_degenerate_triangles`；`profiles/web-realtime-v0.4-texture-approval.json` 把 `profile.max_texture_dimension` 映射为 L2 `resize_embedded_textures`。只有全部 ERROR 可映射为同一个当前 Profile 白名单动作时才输出 `READY` PatchPlan；没有 ERROR 输出 `NO_ACTION`；混合动作或包含其他 ERROR 时输出：

```json
{
  "plan_state": "MANUAL_ONLY",
  "steps": [],
  "approval_required": false,
  "reason": "one or more ERROR rules have no tested whitelist operation"
}
```

v0.1 Profile 继续冻结为空白名单，便于证明策略版本会改变权限，而不是修改历史策略。

## Patch Step Contract

```json
{
  "step_id": "s01",
  "finding_ids": ["f-0001"],
  "skill": "mesh-safe-repair",
  "operation": "enum-only",
  "parameters": {},
  "expected_changes": [],
  "verify_rules": [],
  "risk_level": "L1",
  "rollback_on": []
}
```

## Decision Boundary

- 不生成 Repair Catalog 外的操作；
- 没有独立验证规则的动作只能 MANUAL_ONLY；
- 不把“顺手优化”加入计划；
- 不执行文件修改。
