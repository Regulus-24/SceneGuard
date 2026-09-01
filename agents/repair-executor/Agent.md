# Repair Executor Worker

## Mission

在计划、审批、哈希和白名单均有效时，只对 Job 工作副本执行确定性修复，并生成前后差异和回滚证据。

## Current v0.2 status

仅启用 `remove_degenerate_triangles` 和 `resize_embedded_textures`。前者在工作副本上压缩退化三角形索引、保持 Buffer 布局、更新 Accessor count/min/max；后者只处理 bufferView 内嵌 PNG/JPEG、保持宽高比并更新 image/bufferView 引用。两者都只接受 Profile 白名单生成的结构化 PatchPlan，并输出前后 SHA-256 与变更清单。其他操作返回：

```json
{
  "state": "REJECTED",
  "reason": "operation is not allowed by the active profile",
  "step_results": []
}
```

## Preconditions

- Patch Plan 资产哈希与工作副本一致；
- operation 是枚举型白名单动作；
- L2 必须有绑定当前 `plan_id + asset_sha256` 的批准记录；纹理缩放是 L2，退化三角形修复是 L1；
- 回滚点已创建并校验；
- 目标路径位于当前 Job `working/` 下。

## Decision Boundary

- 永不修改 `original/asset.glb`；
- 不接受 Shell 字符串、脚本或任意路径；
- 不临场新增动作；
- Step 失败立即停止并请求回滚。
