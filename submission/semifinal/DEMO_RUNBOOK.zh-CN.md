# SceneGuard 可运行 Demo 手册

## 结论

复赛主交付采用可运行 Demo，不制作演示视频。仓库提供两种模式：Quick 用于一分钟现场展示，AgentTeams 用于完整验证真实 1+4 多 Agent 主链。

## 一、现场前 10 分钟：Quick 模式

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_semifinal_demo.ps1 -Mode Quick
```

脚本会自动完成：

1. 在 `127.0.0.1:18096` 启动本地 SceneGuard UI；
2. 运行固定场景 `mixed_valid_degenerate.glb` + `web-realtime-v0.5-visual-demo.json`；
3. 验证 `REPAIRED_PASS`、发布文件、before/after 哈希和证据 Artifact；
4. 把本次冒烟结果写入时间戳文件，并更新 `reports/semifinal-demo-smoke-latest.json`；
5. 打开浏览器页面，并在终端显示服务 PID。

一分钟只展示四件事：输入资产/Profile、修复前后、`REPAIRED_PASS`、Trace/Artifact 哈希。不要在一分钟内等待模型。

## 二、会前完整验证：AgentTeams 模式

前提：Docker Desktop、Ollama、HiClaw `sceneguard-auto-v1` Team 已启动。执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_semifinal_demo.ps1 -Mode AgentTeams
```

脚本会生成唯一 Run ID；创建仅本次运行使用的 256-bit 临时 Token；启动认证网关；校验 Team 拓扑；让 TeamLeader 和四个 Worker 分角色运行；最后删除容器中的临时 Token 并停止认证网关。

成功标准：

- `agent_count=5`、`worker_count=4`；
- `operator_actions_after_dispatch=0`；
- `status=COMPLETED`、`gate_state=REPAIRED_PASS`；
- 6 个 L1 必要 Skill 实际调用；
- Plan、执行、回归、发布哈希不变量全部通过。

证据位置：

- Agent 协作：`jobs/.agentteams-native/<run-id>/run-result.json`
- 控制轨迹：`jobs/.agentteams-native/<run-id>/control-trace.jsonl`
- 业务证据：`jobs/<run-id>/artifacts/`
- 包内已验证证据：`evidence/agentteams/semifinal-wrapper-20260902-001/`

第 7 个 Skill `texture-safe-resize` 属于 L2 审批场景，不在 L1 主链中越权调用；四场景套件覆盖全部 7 个 Skill。

## 三、已验证实跑

2026-09-02 已完成两次真实验证：

- semifinal-live-20260902-001：底层主链 68.5 秒；
- semifinal-wrapper-20260902-001：通过一键启动器完成，322.3 秒；
- 两次均为五 Agent、零派发后人工操作、REPAIRED_PASS，全部哈希不变量通过。

完整链存在本地模型长尾，因此只在会前运行；一分钟现场使用 Quick 模式。

## 四、现场失败切换

- Quick 服务未启动：重新运行 Quick 命令，脚本会在 10 秒内明确成功或失败。
- 端口占用：停止占用 18096 的旧进程后重试。
- 模型或 Docker 异常：不要在一分钟 Demo 中排障，直接打开已验证 Run 的 `run-result.json` 和 Artifact，说明这是同一脚本产生的不可变证据。
- UI 异常：用 `reports/semifinal-demo-smoke-latest.json` 展示八项检查结果。

## 五、交付方式

团队已锁定由评委下载代码包后本地运行 Demo；不部署公开在线地址，不制作演示视频。提交包保留一键启动器、依赖说明、冒烟报告和真实五 Agent 不可变证据。
