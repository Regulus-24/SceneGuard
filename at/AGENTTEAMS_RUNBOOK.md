# Run SceneGuard with AgentTeams/HiClaw

> Verified status (2026-08-11): `sceneguard-real` is an Active local 1+4 Team. Clean `PASS`, repair `REPAIRED_PASS`, and sanitized Matrix/Hermes traces are retained under `evidence/agentteams/`.

Official references:

- Deployment: https://higress.ai/docs/hiclaw/hiclaw-deployment/
- Architecture: https://github.com/agentscope-ai/HiClaw/blob/main/docs/architecture.md

## 1. Preflight

From the `sceneguard` directory:

```powershell
python scripts/preflight.py --run-tests
```

The deterministic core may be ready while `agentteams.docker_available` is false. AgentTeams requires Docker Desktop on Windows/macOS or Docker Engine on Linux. On this Windows host, Docker Engine 29.6.2 was validated on 2026-08-11. The verified run used a local-only Ollama container and `qwen3:8b`, so no external model-provider key was required. Never place local gateway, Matrix or model credentials in this repository or a Team message.

## 2. Start the SceneGuard Tool Gateway

```powershell
$env:SCENEGUARD_DEMO_TOKEN = '<generate-a-temporary-random-secret>'
python scripts/run_cli.py serve --host 0.0.0.0 --port 18091 --asset-root samples --profile-root profiles --jobs-root jobs --api-token-env SCENEGUARD_DEMO_TOKEN
```

Verify on the host:

```powershell
Invoke-RestMethod http://127.0.0.1:18091/health
```

Binding `0.0.0.0` is only for local Docker Worker access. SceneGuard refuses non-loopback binding without an environment-provided Bearer Token. Configure every Worker to send `Authorization: Bearer <token>`，do not paste the token into Team messages, logs or screenshots, and do not expose port 18091 to an untrusted network.

## 3. Install AgentTeams/HiClaw

Follow the official installer rather than copying an old version number. On Windows PowerShell 5+ the official documentation currently provides:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
$wc=New-Object Net.WebClient
$wc.Encoding=[Text.Encoding]::UTF8
iex $wc.DownloadString('https://higress.ai/hiclaw/install.ps1')
```

The verified stack was HiClaw 1.1.2, Hermes 0.10.0, local Ollama `qwen3:8b`, local-only Matrix/control-plane ports, and SceneGuard Gateway port 18091. Record any changed stack in a new evidence run. Never commit API keys or generated local tokens.

## 4. Find a Worker-reachable Gateway URL

Inside Docker, `127.0.0.1` points to the Worker container. On Docker Desktop, first try:

```text
http://host.docker.internal:18091
```

Verify from the actual Manager/Worker container with `curl <URL>/health`. If that host is unavailable, inspect the Docker network gateway and use the host gateway address. Do not proceed until the container receives an HTTP 200 health response.

## 5. Create the Team

The four business Workers below are system roles, not the three human team members. Human responsibilities are drafted in `evidence/team/release-decisions.template.json` from slide 14 of the submitted v2 deck and still require each member's confirmation before release evidence can be marked complete.

1. Open the AgentTeams Manager room in Element Web.
2. Supply the Worker-reachable SceneGuard URL from runtime configuration; do not write credentials into `at/create_agents_message.md`.
3. Paste the complete request to Manager.
4. Require serial creation of 4 business Workers.
5. During Team creation, require a new independent Worker such as `sceneguard-real-leader` as TeamLeader.
6. Save the Manager completion message, Team room name, Worker list and health evidence.

## 6. Run three end-to-end tasks

In the Team room, mention the TeamLeader and run one task at a time.

Clean task:

```text
@<team_leader_name>
Create a SceneGuard job for asset clean_triangle.glb with profile web-realtime-v0.2.json. Run the complete workflow and return the asset hash, checks, findings, final gate state and artifact references. A clean asset must not be modified.
```

Repair task:

```text
@<team_leader_name>
Create a SceneGuard job for asset mixed_valid_degenerate.glb with profile web-realtime-v0.5-visual-demo.json. Run the complete workflow. Planner may only select remove_degenerate_triangles, Executor may only write the Job working copy, and Verifier must independently inspect the gate decision before release. Return the PatchPlan, execution, regression and release evidence.
```

Wait for the first result before sending the second task to avoid mixing Job context.

L2 approval task:

```text
@<team_leader_name>
Create a SceneGuard job for asset oversized_texture.glb with profile web-realtime-v0.4-texture-approval.json. Stop at NEED_APPROVAL and return the bound approval request. After an authorized human supplies the matching decision, continue with resize_embedded_textures, independently verify texture dimensions and geometry, and return the final gate and evidence references.
```

Wait for each result before sending the next task to avoid mixing Job context.

## 7. Acceptance evidence

- Team room contains TeamLeader and all 4 business Workers;
- Auditor calls the HTTP Gateway rather than inventing results;
- clean sample ends PASS after independent re-audit;
- mixed-valid-degenerate sample cites `mesh.degenerate_triangles` and ends REPAIRED_PASS under `web-realtime@0.5-visual-demo`;
- oversized texture first ends NEED_APPROVAL, then ends REPAIRED_PASS only after the decision matches both plan and asset hashes;
- Executor only invokes the Profile whitelist operation on the Job working copy;
- report includes asset hash, Profile version, Finding, checks and Trace/artifact refs;
- screenshots/logs contain no API key, local personal path or company information.

## 8. Observed runtime recovery notes

- Team creation invited the four Hermes Workers to the Team room but did not make them join automatically. Join membership and restart/sync must show two joined rooms before dispatch.
- Team synchronization may reset Hermes' default model to the Manager default. Before a retained run, verify the actual session model and configure `model.provider=custom`, `model.default=qwen3:8b`, the local AI Gateway base URL, and `chat_completions` through Hermes configuration.
- Treat plain model text as untrusted. Accept a Worker result only when the Hermes session database contains the expected structured tool call and the matching tool-result payload.
- If the Leader emits an invalid framework payload, retain the rejected call and use a disclosed operator-assisted recovery. Do not relabel it as autonomous success.

## 9. P0 autonomous acceptance contract

`at/automation-contract.v0.1.json` and `at/tasks/p0-autonomous-staged-repair.md` define the fixed
zero-operator acceptance case. Use `scripts/dispatch_agentteams_p0.ps1` to perform all storage,
team-readiness and Matrix validation before the dispatch boundary. Manager inputs must be pulled by
the Leader from `global-shared/...`; `shared/...` is team-private and must not be guessed.

Three 2026-08-25 attempts were retained as negative regression evidence:

1. attempt 001: global input was incorrectly referenced as team-private `shared/...`;
2. attempt 002: `qwen3:8b` emitted invalid `projectflow.create` and `filesync.write` actions;
3. attempt 003: after a successful contract-correct pull, the Leader terminated before reading the
   runbook or creating a Project.

Two additional isolated native-Leader attempts on 2026-08-25 loaded the corrected Team context and
`qwen3.5:9b` SOUL, but still emitted prose/pseudo tool syntax and stopped before Project creation.
They are also failures and must not be relabelled.

The validated fallback is `scripts/run_agentteams_supervisor.py`. It asks four role-separated local
LLM Agents for native Ollama tool calls, validates the exact role/action/identifier contract, and
executes each accepted call inside the matching HiClaw Worker container. It permits at most two
schema retries and no business retry. The retained run `sceneguard-supervised-p0-20260825-004`
produced each LLM decision inside the corresponding Worker container and completed
`REPAIRED_PASS` without operator action after dispatch; see
`evidence/agentteams/supervised-run-20260825.json`. Always call this “validated Supervisor mode”,
not “native HiClaw TeamLeader DAG mode”.

## 10. Semifinal 1+4 complete-chain command

The machine-readable identity list is `at/agent-identities.v0.2.json`; the four-scenario Skill
coverage suite is `at/semifinal-scenario-suite.v0.2.json`. Start the authenticated Gateway,
Docker, Ollama and the Active `sceneguard-auto-v1` Team, then run one unique ID:

```powershell
python scripts/preflight.py --run-tests
docker exec hiclaw-manager hiclaw get teams -o json
python scripts/run_agentteams_native_supervisor.py --run-id semifinal-demo-001 --job-id semifinal-demo-001 --project-id semifinal-demo-001
```

The runner fails before dispatch unless the authoritative Team object is Active with exactly one
named TeamLeader, four expected Workers and the frozen Team room. After dispatch, the host only
validates exact identities and advances the finite state machine; it does not invent findings,
plans, repair results or Gate decisions. Each run ID is immutable and a failed ID is never reused.

The L1 chain uses all five Agents and the six Skills that are actually necessary:

1. TeamLeader invokes `asset-profile`, makes a native tool decision, creates one Project and four
   dependent Tasks, delegates and accepts each result;
2. Asset Auditor invokes `package-audit` and `mesh-validate`;
3. Repair Planner invokes `repair-plan`;
4. Repair Executor invokes `mesh-safe-repair`;
5. Regression Verifier invokes `regression-verify` and exclusively publishes or rolls back.

`texture-safe-resize` is intentionally absent from the L1 run. It is exercised by the L2 scenario
with a plan/hash-bound human approval. Across public-clean, L1, L2 and rollback scenarios all seven
Skills are covered without granting an Agent unnecessary capability.

The retained post-fix runs `semifinal-five-20260901-005` through `-009` passed 5/5 with zero
operator actions after dispatch. See `evidence/agentteams/five-agent-supervisor-20260901.json`
and `reports/agentteams-stability-latest.json`. Call this "validated five-Agent zero-operator
Supervisor mode". Do not call it free-form native Matrix orchestration, and do not delete the
earlier failed attempts.