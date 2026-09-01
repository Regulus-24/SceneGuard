# SceneGuard 复赛返修验收矩阵

> 冻结时间：2026-09-01。团队内部封版：2026-09-02 晚。本文区分“已由机器证据证明”“仍需团队输入”和“只作为路线图”，禁止把计划写成已实现。

## 一、统一结论

- 主 Demo 固定为 `mixed_valid_degenerate.glb` + `web-realtime-v0.5-visual-demo.json`。
- 主运行固定为 1 个 TeamLeader + 4 个业务 Worker，共 5 个 Agent。
- L1 主链按最小权限调用 6 个必要 Skill；`texture-safe-resize` 只在 L2 审批场景调用。四场景套件合计覆盖全部 7 个 Skill，不为凑数在单次任务中调用无关能力。
- 对外口径固定为“经验证的五 Agent、零人工 Supervisor 模式”：五个模型决策和业务动作都在各自 AgentTeams 容器中执行，主机仅锁定 1+4 拓扑、校验标识并推进有限状态机。
- 不宣称自由对话式 Matrix 原生编排，不把 HTTP JSON 等价工具契约说成原生 MCP。
- 许可证固定为 Apache-2.0；公开资产保留各自 CC0-1.0，不由项目许可证重新许可。

## 二、评委返修建议

| 编号 | 评委方向 | 复赛实现 | 当前证据 | 封版验收 |
|---|---|---|---|---|
| J1 | 接入真实工作室或资产平台 | 采用 KhronosGroup 官方 GitHub 资产库的 3 个真实 CC0 GLB；固定上游 commit、URL、作者、许可证、字节数和 SHA-256；只读 Profile 运行后原始与发布哈希一致 | `DATA_SOURCES.md`、`samples/public/*.source.json`、`evidence/public-assets/runtime-20260831.json` | 3/3 来源与哈希通过；明确表述为“开源资产平台接入”，不冒充企业客户接入 |
| J2 | 量化业务价值 | 自动侧报告五 Agent 成功率、P50/P90、零人工动作、发布 Gate、证据完整率；人工侧采用 3 人×每场景 3 次的同输入基线协议 | `benchmark/business-value.v0.1.json`、`reports/agentteams-stability-latest.json` | 自动指标可直接引用；未完成真实人工基线前不得声称节省比例或 ROI |
| J3 | 无人值守、多 Agent 主链 | TeamLeader 在自身容器生成原生工具决策，创建 HiClaw Project/DAG；四个 Worker 在各自容器接单、决策、调用 Gateway、提交；Leader 逐项验收并完成 Project | `scripts/run_agentteams_native_supervisor.py`、`evidence/agentteams/five-agent-supervisor-20260901/` | 修复后连续 5/5 `COMPLETED → REPAIRED_PASS`；派发后人工动作数为 0 |
| J4 | 每次运行对应证据链 | 每次保留 Project、4 个 Task、5 个决策哈希、Skill、Plan、输入/候选/发布哈希、Worker 产物、Leader 验收、Trace、Gate 和 ReleaseAttestation | 同上；业务产物位于对应 `jobs/<job-id>/artifacts/` | 13 项稳定性检查每次完整率 100%；5 项跨报告不变量全真 |
| J5 | Skill 工程治理 | Registry 管理版本、Owner、调用者、状态、评测门、25%/100% 灰度、回滚触发；`mesh-validate` 对缺失能力保持 candidate 和非核心口径 | `skills/registry.v0.2.json`、`skills-lock.json`、`tests/test_semifinal_contracts.py` | 四场景覆盖 7 个 Skill；每个 Skill 有 Owner、版本、准入测试与失败边界 |
| J6 | 生产级工程验证 | 单元/集成/Golden/修复/回滚/API 安全/幂等/契约/敏感信息/提交包一致性；失败运行不覆盖并保留原因 | `benchmark/acceptance.v0.1.json`、`reports/benchmark-latest.json`、`tests/` | 103/103 测试、Core 100/100、正式规则 10/10 + 2/2、63/63 一致性检查全部通过 |
| J7 | 可独立复现的开源交付 | Apache-2.0、README、固定依赖、公开资产来源记录、一键运行脚本、证据、机器清单和 SHA-256 提交包 | `LICENSE`、`NOTICE`、`README.md`、`THIRD_PARTY_NOTICES.md`、`scripts/build_submission_manifest.py` | 最终 ZIP 已在全新临时虚拟环境完成安装、103 项测试、清单校验和 L1 `REPAIRED_PASS`，并安全清理临时副本 |

## 三、复赛规则约束映射

机器规则源为 `benchmark/requirements.v0.1.json`，验收源为 `benchmark/acceptance.v0.1.json`。

| 规则域 | SceneGuard 对应实现 | 状态 |
|---|---|---|
| 至少三类 Agent 功能与明确身份 | 1 Leader + 4 Worker、机器身份清单、权限分离 | 已实现 |
| 以 AgentTeams 为协作基础并提供真实运行证据 | HiClaw Team/Project/DAG/taskflow + 五容器成功链 | 已实现并纳入最终 Release Gate |
| Skill 为核心交付 | 7 个版本化 Skill、Schema、Registry、场景覆盖 | 已实现 |
| 工具接口可审计、鉴权、幂等 | 15 条 HTTP JSON 接口；Bearer 最小鉴权、请求哈希与持久幂等 | 已实现；原生 MCP 未实现 |
| 状态与可观测 | Job、Trace、Metrics、Artifact API、控制面时间线 | 已实现 |
| Profile/Plan/审批 fail-closed | Profile 与资产哈希绑定；L2 绑定审批；错参拒绝 | 已实现 |
| 回滚与发布安全 | checkpoint、独立回归、失败回滚、仅验证后发布 | 已实现 |
| 可评测 | 15 样本、Golden、5 次修复、3 类故障回滚、公开资产只读验证 | 已实现 |
| 合规披露 | 依赖、资产、模型、API、安全边界、许可证 | 已实现；最终一致性检查 63/63 通过 |
| 交付完整性 | manifest、archive、路径逃逸防护、敏感信息扫描 | 已实现；241 文件清单与可复现 ZIP 已验证（含复赛 PPT/PDF 与答辩手册） |
| 长运行治理 | 有界次数/时间、锁、恢复包、回归即停、真实阻塞不伪造 | 已实现 |
| 团队决策证据 | Apache-2.0、项目名、成员与职责 | License 已锁；其余见集中决策清单 |

## 四、五 Agent 与七 Skill 的正确用法

| 场景 | Agent | Skill | 目的 |
|---|---|---|---|
| S1 公开干净资产 | Leader、Auditor、Verifier | asset-profile、package-audit、mesh-validate、regression-verify | 证明真实开源资产不被强行修改 |
| S2 L1 自动修复 | 全部 5 Agent | 除 texture-safe-resize 外的 6 个 | 复赛主 Demo，证明零人工受控修复 |
| S3 L2 审批 | 全部 5 Agent | 除 mesh-safe-repair 外的 6 个 | 证明高风险动作先停、审批后自动续跑 |
| S4 故障回滚 | 全部 5 Agent | 与 S2 相同 | 证明损坏候选不会发布且原件可恢复 |

原则：Agent 负责目标绑定、风险路由和跨工具编排；Skill 负责版本化能力边界；确定性工具负责真正修改文件；Verifier 独立决定发布或回滚。
