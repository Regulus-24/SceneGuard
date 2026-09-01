# Model and API Disclosure

## Deterministic SceneGuard core

The SceneGuard audit, whitelist planning, repair, regression and benchmark code does not call an
LLM. It does not upload GLB bytes, images, prompts or Findings to a model provider. The only
runtime Python dependency is `Pillow==11.3.0`, used for embedded texture decoding and resizing.

## Retained AgentTeams runtime

The retained 2026-08-11 multi-Agent run used:

- AgentTeams/HiClaw `1.1.2`;
- one CoPaw TeamLeader and four Hermes Agent v0.10.0 business Workers;
- local Ollama through the HiClaw AI Gateway;
- model `qwen3:8b`, stored and inferred locally;
- HTTP JSON calls to the locally hosted SceneGuard Gateway;
- no external model-provider API key and no cloud model upload.

The retained trace is explicitly operator-assisted: the local model produced invalid DAG/message
parameters, the framework rejected them, and an operator assisted recovery. It must not be
described as fully autonomous. `at/automation-contract.v0.1.json` defines the stricter acceptance
rule for a new autonomous run.

## 2026-08-25 validated Supervisor run

The retained `sceneguard-supervised-p0-20260825-004` run used four local `qwen3.5:4b`
role decisions through Ollama native tool calling, with each decision produced inside its dedicated
HiClaw Worker container. A deterministic Supervisor accepted only one
role-specific tool name with exact fixed identifiers, allowed at most two schema retries, and then
executed the accepted call inside that role's HiClaw Worker container. All four decisions passed on
their first attempt; no GLB bytes left the host and no external API key was used. The run completed
`REPAIRED_PASS` in 10.7 seconds with zero operator actions after dispatch.

This is an autonomous validated-Supervisor claim. It is not a native HiClaw TeamLeader-DAG claim:
two isolated `qwen3.5:9b` Leader attempts emitted prose or pseudo tool syntax and terminated before
Project creation. Those failures are retained as evidence that prompt-only orchestration is not yet
stable with the current local small-model stack.

## 2026-09-01 validated five-Agent Supervisor run

The retained `semifinal-five-20260901-009` run and the four immediately preceding
runs used one local `qwen3.5:9b` TeamLeader and four local `qwen3.5:4b` business
Workers. All five native Ollama tool decisions were produced inside their dedicated
HiClaw/CoPaw containers. The TeamLeader created a real HiClaw Project/DAG, delegated
four taskflow Tasks, checked each Worker result and completed the Project. Each Worker
acknowledged its Task, called the authenticated local SceneGuard Gateway, wrote
Worker-owned deliverables and submitted a taskflow result.

After the runtime adapter fixes, five consecutive runs completed `REPAIRED_PASS`
with zero operator actions after dispatch. Median P50 was 83.344 seconds and
nearest-rank P90 was 90.250 seconds; all 13 per-run evidence checks and five
cross-report invariants passed. The retained envelope is
`evidence/agentteams/five-agent-supervisor-20260901.json`.

This is a validated five-Agent zero-operator Supervisor claim. The host locks the
authoritative 1+4 topology, corrects a HiClaw 0.1 duplicate-worker storage-scope
lookup, validates exact identifiers and advances a finite state machine. It is not
claimed as free-form native Matrix orchestration. The earlier native-Leader failures
remain valid negative evidence and are not overwritten by this result.

## Authority boundary

Model output may decompose work, route tasks and explain evidence. It may not create geometric
facts, change Profile thresholds, expand the repair whitelist, approve an L2 action, edit retained
evidence or override Regression Verifier results. Only structured SceneGuard tool responses and
hash-verified artifacts are accepted as technical evidence.

## Disclosure required for every new model run

Record provider, model identifier, interface/runtime version, local or remote data path,
authentication scope, timeout/retry policy, token and latency metrics, structured-output adherence,
fallback behavior and migration cost. A model change invalidates the prior runtime claim until a
new retained run passes the same contract.
