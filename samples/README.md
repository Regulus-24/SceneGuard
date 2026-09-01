# Self-created samples

本目录的 `.glb` 文件由 `scripts/generate_samples.py` 从零生成，不来自公司或第三方资产。删除二进制后可随时用脚本重新生成。

默认 `web-realtime@0.1` Profile 将三角面上限故意设置为 1，仅用于快速证明预算规则和测试分支，不代表行业生产阈值。

| 样本 | 预期 | 目的 |
|---|---|---|
| `clean_triangle.glb` | PASS | 正常资产不应被误报 |
| `over_triangle_budget.glb` | REJECTED | 预算超限 |
| `broken_reference.glb` | REJECTED | 跨对象引用错误 |
| `accessor_out_of_bounds.glb` | REJECTED | Accessor 越界 |
| `degenerate_triangle.glb` | REJECTED | 重复顶点索引形成零面积三角形 |
| `external_buffer.glb` | REJECTED | GLB-only 单文件策略 |
