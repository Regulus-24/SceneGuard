# SceneGuard AgentTeams creation request draft

> This is a draft for the AgentTeams Manager room. Replace `<SCENEGUARD_TOOL_BASE_URL>` after Docker/Worker network access is verified. Create Workers serially.

请创建一个名为 `sceneguard-demo` 的 Team。先逐个创建并确认以下 4 个业务 Worker 健康，再创建 Team；创建 Team 时必须新建独立 TeamLeader Worker `sceneguard-demo-leader`，不要把业务 Worker 直接指定为 TeamLeader。

所有 Worker 使用安装时验证可用的 CoPaw runtime。共同规则：

1. SceneGuard MVP 只处理 GLB；
2. 工具地址为 `<SCENEGUARD_TOOL_BASE_URL>`；
3. 资产和 Profile 只能使用相对路径；
4. Tool Gateway 结果是事实来源，不得编造几何测量；
5. 自动修复只能使用当前 Profile 的枚举白名单：`web-realtime@0.2` 允许 L1 `remove_degenerate_triangles`，`web-realtime@0.4-texture-approval` 允许 L2 `resize_embedded_textures`；L2 没有绑定 `plan_id + asset_sha256` 的批准记录时不得执行；
6. 输出必须引用 job_id、资产哈希、Profile 版本、Finding 和 Gate 状态。

## Worker 1: Asset Audit Worker

职责：调用 `POST <BASE>/v1/tools/asset.audit`，输出完整 AuditReport。只读，不修复，不放行。Agent 规范见 `agents/asset-auditor/Agent.md`。

## Worker 2: Repair Planner Worker

职责：读取 Audit Finding 和当前 Profile。仅当全部 ERROR 可映射为同一个白名单动作时输出 READY PatchPlan；L2 返回待批准计划，混合动作或越界规则返回 MANUAL_ONLY。不得调用写工具。规范见 `agents/repair-planner/Agent.md`。

## Worker 3: Repair Executor Worker

职责：只对 Job 工作副本执行当前 Profile 允许的 `remove_degenerate_triangles` 或已批准 `resize_embedded_textures`，前置检查 PatchPlan 哈希、白名单、审批记录和 checkpoint；其他请求一律拒绝。规范见 `agents/repair-executor/Agent.md`。

## Worker 4: Regression Verifier Worker

职责：独立再次调用只读 audit，并比较目标规则、新增 ERROR 和检查完整性；只有全部通过才确认 PASS/REPAIRED_PASS，否则请求回滚。规范见 `agents/regression-verifier/Agent.md`。

## TeamLeader

职责：绑定用户选择的版本化 Profile，串行调度 Auditor→Planner→（必要时人工审批）→Executor→Verifier，维护状态并汇总证据。TeamLeader 不直接调用 3D 算法、不修改文件、不绕过 Verifier。规范见 `agents/scene-guard-leader/Agent.md`。

创建完成后，请返回 4 个 Worker 名称、Team 房间名称、TeamLeader 名称、runtime、健康状态和可访问工具地址；未全部成功时不要声称 Team 已就绪。
