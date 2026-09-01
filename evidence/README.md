# SceneGuard 外部运行证据

本目录只保存真实运行证据，禁止为了让 Benchmark 变绿而复制模板或编造结果。

## 当前状态

1. `agentteams/runtime.json`：已于 2026-08-11 由本机真实 HiClaw/AgentTeams 1+4 运行生成，并引用三份脱敏 JSONL 轨迹；该轨迹明确包含操作员辅助恢复。
2. `agentteams/autonomous-attempt-001.json` 至 `003.json`：2026-08-25 三次零人工验收均真实失败，分别覆盖存储路径、工具 Schema 和 Leader 提前终止；不得用于自主成功声明。
3. `official-skill/integration.json`：仍未生成。GOAI 官网要求 Skill 必选，但官方用云 Skill 是可选方案；SceneGuard 已由 7 个自研 Skill 满足硬要求，因此该集成保留为 P1 增强，不再阻断 Release。解释见 `competition/GOAI_SKILL_REQUIREMENT_20260825.md`。
4. `team/release-decisions.json`：团队于 2026-08-31 根据复赛评委建议将协议从 MIT 切换为 Apache-2.0；详见 `team/APACHE_2_0_SELECTION_RECORDED.md`。旧 MIT 文件仅保留为历史审计记录。

对应模板分别是 `runtime.template.json` 和 `integration.template.json`。模板只用于说明结构；正式文件必须来自真实运行、引用的日志必须存在并完成脱敏。

仅把顶层 `status` 改成 `PASS` 无效：Release 校验会递归拒绝所有占位符，校验 ISO 8601 时区、唯一 Worker/成员集合，并要求用例内的成功/失败 `trace_ref` 同时出现在顶层清单且指向仓库 `evidence/` 内真实非空文件。

填完后执行：

```powershell
python scripts/run_benchmark.py --output reports/benchmark-latest.json
```

预期从 `core.status=PASS, release.status=BLOCKED_EXTERNAL` 变为 `release.status=PASS`。
