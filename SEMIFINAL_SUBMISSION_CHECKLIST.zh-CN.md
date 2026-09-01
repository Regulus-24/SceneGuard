# SceneGuard 复赛提交与答辩清单

> 依据《GOAI 2026 赛道一 Agent Infra 复赛参赛指南》整理。内部封版：2026-09-02 晚；线上答辩：2026-09-04。

## 一、不可错过的时间

- 队伍：第 6 组、第 26 队 SceneGuard。
- 候场：最晚 15:42 进入等候室。
- 正式答辩：15:52–16:00。
- 节奏：3 分钟项目陈述 + 1 分钟 Demo + 3 分钟问答 + 1 分钟评分/切换。

## 二、指南硬性材料

- [x] 更新后的 PPT 与 PDF；初赛反馈对应改动使用红色标记。
- [x] 场景闭环：目标用户、痛点、价值、输入与输出。
- [x] 1 TeamLeader + 4 Worker 的身份、边界与协作链。
- [x] 7 个核心 Skill 的版本化合同、调用边界、失败处理与安全约束。
- [x] 高风险操作 L2 人工确认、故障回滚与完整审计。
- [x] 完整端到端证据链与可复现代码包。
- [x] 跨行业迁移路径及当前真实开源资产来源。
- [ ] 公开在线 Demo 环境，或不超过 8 分钟的备用演示视频。
- [ ] 最终上传后的平台可访问性与匿名下载复核。

## 三、团队必须一次确认的事项

1. 主讲人、现场 Demo 操作人、最终上传人、视频录制/剪辑人及各自备份。
2. L2 审批演示是否继续使用公开角色 `asset-quality-reviewer`，以及现场由谁点击批准。
3. 是否能完成 3 人 × 3 次人工业务基线；不能完成则只报告 Agent 自动侧指标，不声明 ROI 或节省比例。

## 四、已锁定口径

- 公开仓库：`Regulus-24/SceneGuard`，默认分支 `main`。
- 项目许可证：Apache-2.0；第三方 Khronos 资产保留 CC0-1.0 和原作者/来源信息。
- 主 Demo：`mixed_valid_degenerate.glb` + `web-realtime-v0.5-visual-demo.json`。
- AgentTeams：经验证的五 Agent 零人工 Supervisor 模式；不冒充自由式 Matrix 原生编排。
- Skill：L1 只调用 6 个必要 Skill，四场景套件覆盖全部 7 个 Skill。
- Sketchfab：仅为下一阶段 OAuth Connector 设计路线，当前不声明已接入。
- 业务价值：当前报告 5/5、P50/P90、派发后人工救场 0 次和证据完整率 100%；人工基线完成前不声明 ROI。

## 五、上传前门禁

```powershell
python -m unittest discover -s tests -v
powershell -ExecutionPolicy Bypass -File scripts/verify_p0.ps1
python scripts/build_submission_manifest.py
python scripts/build_submission_manifest.py --verify
python scripts/build_submission_manifest.py --archive reports/sceneguard-submission.zip
python scripts/build_submission_manifest.py --verify-archive reports/sceneguard-submission.zip
```

只有全部通过且 PPT、PDF、代码包与视频/在线环境都能由未登录或评委身份访问时，才允许上传。