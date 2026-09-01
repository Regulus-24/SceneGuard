# SceneGuard Demo AgentTeam

## AgentTeams mapping

| AgentTeams concept | SceneGuard v0.2 |
|---|---|
| Manager room | Receives a self-contained request to create 4 business Workers and 1 Team |
| Team room | User submits an asset-relative path, Profile and goal to the dedicated TeamLeader |
| TeamLeader Worker | `sceneguard-real-leader`, created independently during Team creation |
| Business Workers | Asset Auditor, Repair Planner, Repair Executor, Regression Verifier |
| Shared state | Job manifest, Audit Report, Trace JSONL and artifact references |
| Tool access | HTTP JSON Tool Gateway on port 18091; no Worker reads arbitrary host paths |
| Human oversight | Team room shows task routing；L1 tested whitelist can auto-run, L2 requires approval |

Official AgentTeams/HiClaw uses a Manager-Workers architecture over Matrix rooms and can create a Team with a dedicated Team Leader. SceneGuard follows that structure rather than implementing an unrelated in-process “multi-agent” loop.

## Verified runtime boundary

The deterministic Tool Gateway and a real Team were run locally on 2026-08-11 with HiClaw 1.1.2, Hermes 0.10.0 and Ollama `qwen3:8b`. The Team is `sceneguard-real`, with one Leader and these four business Workers:

- `Asset Audit Worker`: implemented Tool contract;
- `Repair Planner Worker`: creates READY/NO_ACTION/MANUAL_ONLY PatchPlan from the active Profile;
- `Repair Executor Worker`: enabled for `remove_degenerate_triangles` and, only after bound L2 approval, `resize_embedded_textures` on a Job working copy;
- `Regression Verifier Worker`: independently re-audits and compares target/new ERROR findings;
- Team state: Active, Leader ready, 4/4 Workers ready; retained evidence is in `evidence/agentteams/`.

The local 8B Leader successfully called `projectflow` to create the Project, but also produced invalid `plan_dag`, `taskflow` and `message` payloads. The framework rejected those calls. The run then used an audited operator-assisted recovery: assignments retained the Leader/Matrix control-plane context, every business result came from a real Worker session, and only structured tool results were accepted. This is a real but not fully autonomous 1+4 run; the failed calls are disclosed in `trace-control-plane.jsonl`.

## Task flow

1. User sends `asset`, `profile` and intended usage to TeamLeader.
2. TeamLeader asks Asset Auditor to call `POST /v1/tools/asset.audit`.
3. If the report is PASS, Verifier re-runs the audit and TeamLeader returns PASS with evidence refs.
4. If all ERROR findings map to the selected Profile whitelist, Planner returns a single-operation PatchPlan and a checkpoint is created. L2 plans stop at NEED_APPROVAL until a decision is bound to plan and asset hashes.
5. Executor repairs only the working copy; Verifier re-audits and returns REPAIRED_PASS or requests rollback.
6. Unsupported ERROR rules remain MANUAL_ONLY/REJECTED without file mutation.

The Matrix/Worker run proves this flow for a clean `PASS` case and a `REPAIRED_PASS` degenerate-triangle case. A stricter `web-realtime@0.2` attempt was correctly kept `REJECTED` because `profile.max_triangles` was outside the automatic repair contract. Native MCP and official cloud Skill evidence remain outside this verified boundary.
