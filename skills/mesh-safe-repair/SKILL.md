---
name: mesh-safe-repair
description: Remove eligible degenerate indexed triangles under a bound PatchPlan and checkpoint.
metadata:
  version: "0.1.0"
  maturity: implemented
  type: external-tool-wrapper
  input_schema: schemas/repair-execution-input.schema.json
  output_schema: schemas/execution-report.schema.json
  dependency: sceneguard.repair.remove_degenerate_triangles
  dependency_version: "sceneguard@0.1.0; GLB 2.0; Python>=3.11"
  timeout_seconds: 60
---

# mesh-safe-repair

## Purpose

对符合严格前置条件的 GLB indexed TRIANGLES 删除退化三角形，并保留可验证、可回滚的修改证据。

## Input

- 当前 Job `working/candidate.glb`；
- PatchPlan 中的 `asset_sha256`；
- operation 必须为 `remove_degenerate_triangles`；
- `web-realtime@0.2` 或其他显式允许该动作的版本化 Profile。

## Preconditions

- GLB 使用单个内嵌 Buffer；
- Primitive mode 为 TRIANGLES 且存在 indices；
- indices 是无符号整数 SCALAR、非交错 Accessor；
- 工作副本哈希与 PatchPlan 一致；
- `pre-repair` checkpoint 已创建并校验。

## Output

`execution_report.json` 包含 operation、前后 SHA-256、删除三角形数、受影响 Primitive、修改前后字节数。Executor 的成功输出不等于发布许可，必须交给 Regression Verifier 全量复验。

## Safety boundary

- 永不写 `original/`；
- 不处理非索引 Primitive、压缩扩展、外部 Buffer 或任意路径；
- 没有发现可修复退化面时失败；
- 任一异常停止执行并触发 checkpoint 回滚。
