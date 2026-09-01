# SceneGuard 可交付原型

SceneGuard 是面向游戏/XR、三维电商、数字孪生与仿真的 3D 资产质量门禁与受控修复多 Agent 系统，已从 800+ 个初赛作品中进入 Top30。本仓库为可运行的 GLB 最小闭环，不包含任何公司内部数据、代码、规则、阈值、截图或流程。

## 当前已实现

- 自研 GLB 2.0 解析与确定性审计，图像重采样仅使用锁定版本的 Pillow；
- 文件封装、引用、Accessor 边界、预算、非有限坐标与退化三角形检查；
- 版本化 Quality Profile、Finding、PatchPlan、GateDecision 和 JSONL Trace；
- 13 份 Draft 2020-12 输入/输出 Schema、7 个 Skill 机器契约和零依赖本地 Schema 校验；
- `original/working/checkpoints/published/artifacts` 隔离工作区；
- 两类受控白名单修复：退化三角形最小索引修改，以及内嵌纹理等比缩放；两者都执行哈希前置校验与全量复验；
- PASS、REPAIRED_PASS、NEED_APPROVAL、REJECTED、FAILED_ROLLBACK 状态；
- 失败注入、checkpoint 哈希校验、原子回滚及发布证明；
- HTTP JSON Tool Gateway、32 MiB 上限的用户 GLB 上传，以及零构建双 WebGL 预览页面；
- 12 个团队自建 GLB + 3 个固定 commit/SHA-256 的 Khronos CC0 公开 GLB、Golden 评测和自动测试；
- 原子回执、会话互斥、10–24 小时墙钟预算、逐轮不可变证据、工程恢复快照和回归停机的 Loop Supervisor；
- 已实跑的 1 TeamLeader + 4 Worker AgentTeams/HiClaw 团队，以及四角色 LLM 原生 tool-call + 受校验 Supervisor 的零人工完整链路、Agent Identity、Team Spec、脱敏轨迹与运行手册。

2026-09-01，`sceneguard-auto-v1` 跑通了经验证的五 Agent 零人工 Supervisor 主链：TeamLeader 在自己的 HiClaw/CoPaw 容器内用本地 `qwen3.5:9b` 产生原生工具决策，创建 Project/DAG、委派并验收 4 个 Task；四个业务 Worker 分别在自己的容器内用本地 `qwen3.5:4b` 决策、调用受限 Gateway 并提交产物。修复后连续 5/5 次达到 `COMPLETED → REPAIRED_PASS`，派发后人工动作数为 0，P50 83.344 秒、P90 90.250 秒，13 项证据完整性检查和 5 项跨报告不变量全部通过。正式封套位于 `evidence/agentteams/five-agent-supervisor-20260901.json`，稳定性报告位于 `reports/agentteams-stability-latest.json`。准确口径是“所有五个模型决策与业务动作均在 AgentTeams 容器中运行，主机锁定拓扑并推进有限状态机”；不宣称自由式原生 Matrix 编排。2026-08-11 的 `OPERATOR_ASSISTED` 历史轨迹与 2026-08-31 的 8 次原生 Leader 失败仍保留，不能覆盖或改写。尚未完成的是原生 MCP；Gateway 的最小 Bearer 鉴权也不是企业级 IAM。

## 复赛答辩材料

- 最终 PPT/PDF：`submission/semifinal/SceneGuard_复赛方案_最终版.*`；初赛反馈对应改动以红色标注。
- 3+1 分钟现场节奏与问答口径：`submission/semifinal/DEFENSE_RUNBOOK.zh-CN.md`。
- 平台材料、答辩时间与团队待决策项：`SEMIFINAL_SUBMISSION_CHECKLIST.zh-CN.md`、`TEAM_DECISIONS_REQUIRED.zh-CN.md`。
- 2026-09-04 第 6 组第 26 队；15:42 前候场，15:52–16:00 正式答辩。

## 一键启动与 P0 验证

在新环境中使用 Python 3.11+ 安装唯一锁定依赖，然后启动 Demo：

```powershell
python -m pip install -e .
powershell -ExecutionPolicy Bypass -File scripts/start_initial_demo.ps1
```

另一终端执行统一 P0 门禁。该脚本依次运行测试、代码/数据/文档/证据一致性检查和 Release Benchmark；存在真实外部阻塞时返回退出码 2，并把具体原因写入报告，不会伪造 PASS：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_p0.ps1
```

五 Agent 主链在 Docker、Ollama、Gateway 和 `sceneguard-auto-v1` Team 就绪后，用一个命令运行；每个 ID 只允许使用一次：

```powershell
python scripts/run_agentteams_native_supervisor.py --run-id semifinal-demo-001 --job-id semifinal-demo-001 --project-id semifinal-demo-001
```

L1 主链只调用 6 个必要 Skill；第 7 个 `texture-safe-resize` 在 L2 审批场景使用。四场景套件 `at/semifinal-scenario-suite.v0.2.json` 合计覆盖全部 7 个 Skill。

`release-facts.v0.1.json` 是 PPT、视频、README 与机器报告应共同引用的唯一事实源；一致性结果写入 `reports/release-consistency.json`，Release 结果写入 `reports/benchmark-latest.json`。

## 初赛彩排（保留兼容入口）

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_initial_demo.ps1
python scripts/run_demo_smoke.py --base-url http://127.0.0.1:18096 --output reports/initial-demo-smoke.json
python scripts/initial_submission_check.py --allow-pending-signoff
```

第一个命令在后台启动 Demo；第二个命令自动验证固定修复链、修复前后 GLB 和证据包；第三个命令检查 500 字简介、PPT/PDF、敏感信息与团队签字。技术材料就绪但三人尚未签字时，最后一个命令会明确返回 `WAITING_TEAM_CONFIRMATION`。移除 `--allow-pending-signoff` 可作为提交前的严格门禁。

三人确认后可以一次生成正式 PPT/PDF 和自校验材料包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/finalize_initial_submission.ps1
python scripts/build_initial_materials_package.py --verify "..\..\初赛交付_20260816\SceneGuard_初赛正式提交包.zip"
```

脚本先验证三人确认与已经审阅的姓名、角色、职责完全一致，再移除成员页待确认状态，通过 PowerPoint 导出 PDF，最后执行严格门禁和打包。如果成员要求修改信息，脚本会拒绝沿用旧稿，必须先更新并重审 V3。打包器只会在严格门禁为 `PASS` 时运行；ZIP 内把官方必交的简介、PPT、PDF 单独放在 `01_官方必交/`，同时写入 SHA-256 清单和完整检查回执，并拒绝“待团队确认”或模板文件。

## 3 分钟启动

要求 Python 3.11+。在项目根目录安装锁定依赖并执行：

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/run_cli.py serve --host 127.0.0.1 --port 18091 --asset-root samples --profile-root profiles --jobs-root jobs
```

浏览器打开 `http://127.0.0.1:18091/`。推荐演示：

1. 默认 `mixed_valid_degenerate.glb` + `web-realtime@0.5-visual-demo`：修复后仍保留可见几何，可直接对比前后模型；
2. 上传自己的 `.glb`：文件先经大小、扩展名和 GLB 2.0 结构校验，再进入同一 Job 流程；
3. `oversized_texture.glb` + `web-realtime@0.4-texture-approval`：先得到 `NEED_APPROVAL`，勾选批准后执行 L2 内嵌纹理等比缩放；
4. 退化样本勾选“注入验证故障”：`FAILED_ROLLBACK`，不发布且工作副本恢复。

命令行复现：

```powershell
python scripts/run_cli.py run-job samples/clean_triangle.glb --profile profiles/web-realtime-v0.2.json --jobs-root jobs --job-id demo-clean
python scripts/run_cli.py run-job samples/degenerate_triangle.glb --profile profiles/web-realtime-v0.2.json --jobs-root jobs --job-id demo-repair
python scripts/run_cli.py run-job samples/degenerate_triangle.glb --profile profiles/web-realtime-v0.2.json --jobs-root jobs --job-id demo-rollback --fault-injection corrupt_after_execute
```

最后一个命令以退出码 2 表示门禁阻断，这是预期结果，不是程序崩溃。

## Loop Engineering 验收

运行一轮“基线—评测—差距—回归—判定”闭环：

```powershell
python scripts/run_loop_iteration.py --target release
```

运行有界长时监督会话：

```powershell
# 当前核心已通过时，只监测真实外部证据变化；不会重复刷完整测试
python scripts/run_loop_supervisor.py --target release --hours 20 --watch-external

# 存在本地 Core 差距时，显式接入一个外部工程 Agent；参数不经过 shell
python scripts/run_loop_supervisor.py --target release --hours 10 --worker-command YOUR_AGENT_EXECUTABLE ARG1 ARG2
```

Supervisor 不会假装能启动未安装的 Agent。没有显式 `--worker-command` 时，它生成受限 `work-item.json` 后以 `AGENT_ACTION_REQUIRED` 停机；提供 Worker 时，每次调用前生成可复验恢复 ZIP，并通过环境变量 `SCENEGUARD_LOOP_WORK_ITEM`、`SCENEGUARD_LOOP_SESSION_ID`、`SCENEGUARD_LOOP_CHECKPOINT` 交付上下文。Worker 输出不写入证据文件，避免意外记录密钥；Core 分数下降会 `REGRESSION_DETECTED` 停机并保留快照，但不会覆盖用户工作区。外部证据监测只比较文件哈希和 Docker 可用性，变化后才重跑验收。Supervisor 不是 Worker 的文件系统/网络沙箱，也不含内置 Codex Adapter；完整的真/假能力表由 `benchmark/loop-supervisor-contract.v0.1.json` 机器校验。

Before a delivery benchmark, build and verify the deterministic submission manifest:

```powershell
python scripts/build_submission_manifest.py
python scripts/build_submission_manifest.py --verify
python scripts/build_submission_manifest.py --archive reports/sceneguard-submission.zip
python scripts/build_submission_manifest.py --verify-archive reports/sceneguard-submission.zip
```

The manifest hashes every declared deliverable with SHA-256, rejects path escapes and
sensitive-looking files, includes the three immutable `jobs/delivery-*` evidence directories and
two frozen verification reports, and excludes all other runtime `jobs/` and `reports/` output.
The final ZIP was also extracted into a fresh temporary virtual environment, installed with the
README command, and passed all 103 tests, manifest verification and the L1 `REPAIRED_PASS` demo.

机器可读标准位于 `benchmark/acceptance.v0.1.json`，最新回执写入 `reports/benchmark-latest.json`，循环状态写入 `reports/loop-state.json`。真实 AgentTeams 证据已写入 `evidence/agentteams/runtime.json`，三名成员的 Apache-2.0 决策写入 `evidence/team/release-decisions.json`。GOAI 官网要求 Skill 必选，但允许官方用云 Skill或自研可复用 Skill；SceneGuard 以 7 个版本化自研 Skill 满足硬要求，官方云 Skill 不再被误设为 Release 硬门禁。

`benchmark/requirements.v0.1.json` 进一步把正式材料条款映射到 benchmark check、仓库文件和外部证据。2026-08-31 团队根据复赛评委建议将仓库协议统一切换为 Apache-2.0；未来 PPT、视频、README 和代码包均使用 SPDX 标识 `Apache-2.0`。

自动修复指标不复用同一个资产凑分母：`repair_benchmark` 对 5 个独立生成的退化三角形 GLB（重复索引、共线坐标、重复位置以及 U8/U16/U32 索引变体）逐一执行修复、独立 Regression 和原件哈希检查；少于 5 次真实尝试或成功率低于 90% 会使 Core 失败。

回滚指标同样有真实分母：`rollback_benchmark` 分别注入执行前哈希篡改、执行后工具错误和验证前候选损坏。三种模式都必须进入 `FAILED_ROLLBACK`、恢复原始工作副本哈希、留下注入/回滚 Trace 且不产生发布文件；少于 3 种或成功率不是 100% 会使 Core 失败。

真实公开兼容性样本为 Khronos `BoxVertexColors.glb`、`Avocado.glb` 与 `BoomBox.glb`。每个 `.source.json` 均固定官方 commit、下载 URL、CC0-1.0、作者、字节数和 SHA-256，且在专用只读 Profile 下必须 `PASS`；团队许可复核状态为 `TEAM_REVIEWED`。

`schemas/registry.v0.1.json` 是公开契约入口：它把 13 份 Draft 2020-12 Schema 绑定到 7 个核心 Skill 及 Pipeline API 的输入、输出、实现依赖、依赖版本和超时。`contracts.schemas` 会用当前 Profile 和临时真实修复链验证这些契约，并拒绝远程或越界 `$ref`；这验证的是结构契约，不等于已经实现硬执行超时。`at/http_api.v0.1.json` 则逐条登记 15 个真实 HTTP API，其中三个阶段接口强制规划、执行、独立验证的 Agent 分工，防止设计路由被误称为已经实现。

`skills/registry.v0.2.json` 定义 7 个 Skill 的 owner、版本状态、评测门槛、兼容维度、灰度和回滚触发器；`at/semifinal-scenario-suite.v0.2.json` 用公开干净资产、L1 自主修复、L2 人工审批和故障回滚四个场景覆盖全部 Skill。单个 Job 只调用必要 Skill，不为凑数量破坏最小权限与安全边界。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/` | 本地 Demo 页面 |
| GET | `/health` | 健康检查 |
| GET | `/v1/assets` | 列出 Demo 样本 |
| GET | `/v1/assets/content?ref=...` | 读取经校验的内置/上传 GLB 用于预览 |
| GET | `/v1/profiles` | 列出质量策略 |
| POST | `/v1/assets/upload` | 上传并校验一个不超过 32 MiB 的用户 GLB |
| POST | `/v1/tools/asset.audit` | 只读审计 |
| POST | `/v1/jobs` | 初始化隔离工作区 |
| POST | `/v1/tools/repair.plan` | 冻结绑定 Profile、资产哈希的 PatchPlan |
| POST | `/v1/tools/repair.execute` | 只执行指定 Plan ID，不能验证或发布 |
| POST | `/v1/tools/regression.verify` | 独立复验，并独占发布/回滚权限 |
| POST | `/v1/pipeline/run` | 运行完整发布/回滚闭环 |
| GET | `/v1/jobs/{job_id}/artifacts` | 列出当前 Job 的安全证据文件 |
| GET | `/v1/jobs/{job_id}/artifacts/{artifact}.json[l]` | 读取受限 JSON/JSONL 证据与哈希 |
| GET | `/v1/jobs/{job_id}/assets/{original\|working\|published}` | 读取修复前后 GLB 用于双视窗对比 |

每次 UI 运行结束后，证据面板会通过上述受限接口展示按顺序排列的 JSONL Trace 时间线，以及可读 Artifact 的 SHA-256 和字节数。

所有 HTTP 响应返回 `X-Request-ID`；客户端可传同名请求头进行关联。`POST /v1/pipeline/run` 支持 `Idempotency-Key`：同键同输入返回持久化结果且不重复执行，同键异参返回 `409 IDEMPOTENCY_CONFLICT`。响应 `meta` 包含规范化输入/输出 SHA-256；Job Trace 记录 Request ID 与幂等键哈希，不落盘原始幂等键。

Gateway 默认只绑定 `127.0.0.1`。若为 Docker Worker 绑定 `0.0.0.0`，必须先把 Token 写入自定义环境变量，并用 `--api-token-env <变量名>` 读取；Token 不得出现在命令参数、仓库或截图中。该最小 Bearer 鉴权仍不适合直接暴露公网。

## Gate 语义

- `PASS`：无需修复，所有必检项完成且无 ERROR，已发布；
- `REPAIRED_PASS`：白名单动作执行后全量复验通过，已发布；
- `NEED_APPROVAL`：存在候选动作，但本次未授权执行；
- `REJECTED`：存在不可自动修复的 ERROR 或检查不完整，不发布；
- `FAILED_ROLLBACK`：修复/验证失败，已回滚且不发布。

## 证据在哪里

每个 Job 都产生：

```text
jobs/<job-id>/
├─ original/asset.glb                # 只读原件副本
├─ working/candidate.glb             # 受控工作副本
├─ checkpoints/pre-repair.glb        # 修复前检查点（需要修复时）
├─ published/asset.glb               # 仅 PASS/REPAIRED_PASS 存在
└─ artifacts/
   ├─ audit_report.json
   ├─ patch_plan.json
   ├─ execution_report.json          # 执行修复时
   ├─ regression_audit.json          # 修复后复验时
   ├─ regression_report.json
   ├─ release_attestation.json       # 发布时
   ├─ rollback-pre-repair.json       # 回滚时
   ├─ approval_request.json          # L2 待审批/已决策时
   ├─ approval_record.json           # L2 已批准或拒绝时
   ├─ gate_decision.json
   ├─ metrics.json
   └─ trace.jsonl
```

仓库内的 `jobs/delivery-clean`、`jobs/delivery-repair`、`jobs/delivery-rollback` 是 2026-08-06 生成的三条固定运行证据。

## Clean-room 与能力边界

所有 Demo Profile 和资产均由团队为公开比赛从零设计/生成，只代表演示契约，不代表企业生产标准。修复白名单目前包含 `remove_degenerate_triangles` 和 `resize_embedded_textures`：前者仅支持 GLB 内嵌 Buffer、规则 Accessor、indexed TRIANGLES；后者仅处理 bufferView 内嵌的 PNG/JPEG，并保持宽高比，默认按 L2 要求人工批准。其他错误坚持检测、阻断和人工处理，不做未经验证的自动改写。

依赖、数据、模型/API 与安全披露分别见 `THIRD_PARTY_NOTICES.md`、`DATA_SOURCES.md`、`MODEL_DISCLOSURE.md` 和 `SECURITY.md`。SceneGuard 仓库采用 Apache License 2.0；第三方资产与依赖仍遵循各自来源记录和许可证，不能被项目协议重新许可。
