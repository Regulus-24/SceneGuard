# SceneGuard Loop Engineering Benchmark

本目录把正式材料中的验收要求编译为可执行门禁。它不是让 Agent 无限制重试，而是让每一轮遵循同一个证据闭环：

```text
Baseline → Evaluate → Diagnose → Minimal Change → Regression → Receipt → Decide
```

## 运行一轮

```powershell
python scripts/run_loop_iteration.py --target release
```

## 运行 10–20 小时有界监督会话

```powershell
python scripts/run_loop_supervisor.py --target release --hours 20 --watch-external
```

若 Core 存在可由工程修改解决的差距，可在命令末尾用 `--worker-command EXECUTABLE ARG...` 显式适配外部 Agent。Supervisor 使用无 shell argv、单会话文件锁、24 小时硬上限、原子 heartbeat、逐轮不可变 Benchmark 回执和每次 Worker 前的可复验恢复 ZIP。没有 Worker 时会生成 `work-item.json` 后返回 `AGENT_ACTION_REQUIRED`；Worker 失败、超时或导致 Core 分数下降时停止，不自动覆盖当前工作区。当前 Core 已通过而 Release 只缺外部证据时，默认立即返回 `AWAIT_EXTERNAL_EVIDENCE`；只有显式 `--watch-external` 才会等待，并且证据哈希或 Docker 状态未变化时不会重复运行测试。Supervisor 不隔离 Worker 的文件系统或网络权限，也不内置 Codex Adapter；这些限制与已实现控制固定在 `loop-supervisor-contract.v0.1.json`。

`submission.manifest` also requires a current, verified file inventory. Regenerate it
after source or material changes with `python scripts/build_submission_manifest.py`.

每轮会覆盖写入两个有界文件：

- `reports/benchmark-latest.json`：本轮完整证据；
- `reports/loop-state.json`：最多保留最近 20 个紧凑回执。

判定语义：

- `COMPLETE`：目标的全部硬门通过；
- `CONTINUE`：存在可由代码、测试或材料修改解决的差距；
- `REPLAN_REQUIRED`：连续三轮没有提升或失败指纹不变，必须改变策略；
- `AWAIT_EXTERNAL_EVIDENCE`：本地核心通过，但 Docker、真实 AgentTeams 或官方 Skill 证据缺失；
- `STOP_ITERATION_LIMIT`：达到 50 轮安全上限，需要人工复核后才能继续。
- `STOP_TIME_BUDGET`：达到本次 10–24 小时墙钟预算；
- `AGENT_ACTION_REQUIRED`：已生成工作包，但没有配置真实工程 Agent；
- `WORKER_FAILED` / `REGRESSION_DETECTED`：Worker 异常、超时或使核心分下降，保留恢复包后停机。

## 当前硬门

1. Python 编译和不少于 79 项回归测试；
2. 13 个 Golden（12 自建 + 1 个固定来源的 CC0 公开 GLB）的 Gate、14 个预期 ERROR 的规则召回和证据完整率全部为 100%；
3. PASS、REPAIRED_PASS、NEED_APPROVAL、FAILED_ROLLBACK、REJECTED 五条路径；
4. 原件哈希不变、发布隔离、完整 Artifact，以及至少 3 种语义不同失败注入的 100% 回滚；
5. `remove_degenerate_triangles` 至少 5 个独立资产真实尝试，成功率与独立 Regression 通过率均不低于 90%；`resize_embedded_textures` 另有 L2 待审批、拒绝和批准后修复三条门禁用例；
6. 每个 Job 的 Trace 使用同一 `trace_id`，并生成结构化 Metrics；
7. 5 个 Agent Identity、核心 Skill 和 Team Spec 存在；
8. 13 份 Draft 2020-12 Schema、7 个 Skill 的输入/输出/依赖/版本/超时元数据与真实运行产物一致；
9. 11 条 HTTP 路由的鉴权、输入 Schema、限额、幂等和 MCP 映射与实现注册表一致；
10. Profile、Team Spec 和 README 与已实现白名单保持一致；
11. 正式条款注册表和 SHA-256 提交清单均保持当前；
12. Loop Supervisor 的原子状态、会话互斥、墙钟预算、显式 Worker 边界、恢复快照、回归停机和外部证据无空转监测契约完整。

外部运行证据单独作为 release gate，不能用占位 JSON 或模拟日志冒充。校验器递归拒绝 `TODO/TBD/PLACEHOLDER/REPLACE_ME`，要求带时区时间并把每个成功/失败用例的 Trace 引用交叉绑定到真实非空文件。AgentTeams 证据还必须证明唯一的至少 4 个 Worker、TeamLeader、Docker 主机与健康 Gateway；官方 Skill 证据必须包含阿里云官方来源、鉴权方式、成功与失败双链、替代策略和脱敏确认。Benchmark 分数只描述当前自建样本与契约测试，不代表真实行业泛化能力。

正式条款追踪位于 `requirements.v0.1.json`。回执的 `requirements` 字段分别报告 Core 与 Release 覆盖率；Release 还要求 `evidence/team/release-decisions.json` 和实际 `LICENSE`，防止代码通过但报名/开源决策未冻结时被误判为可提交。
