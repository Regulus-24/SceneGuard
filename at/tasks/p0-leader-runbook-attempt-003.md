# Leader execution runbook for SG-P0-AUTO-20260825-003

This file compiles the current HiClaw Project/Task Skills into fixed actions. Do not invent action
names, fields or paths. The source requester is Manager in the current Leader Room.

## Fixed identifiers

- projectId: `sceneguard-p0-auto-20260825-003`
- parentTaskId: `SG-P0-AUTO-20260825-003`
- Team Room: `!9XvFcALqzJGB9VEPS8:matrix-local.hiclaw.io:18080`
- requester: `@manager:matrix-local.hiclaw.io:18080`

## Project creation and full DAG

Use `projectflow` action `create_project` with `projectId`, `title`, `source`, `requester` and
`parentTaskId`. Then use `projectflow` action `plan_dag` with this exact graph:

1. `sceneguard-p0-auto-20260825-003-01`, assignedTo
   `sceneguard-real-asset-auditor`, no dependencies.
2. `sceneguard-p0-auto-20260825-003-02`, assignedTo
   `sceneguard-real-repair-planner`, depends on task 01.
3. `sceneguard-p0-auto-20260825-003-03`, assignedTo
   `sceneguard-real-repair-executor`, depends on task 02.
4. `sceneguard-p0-auto-20260825-003-04`, assignedTo
   `sceneguard-real-regression-verifier`, depends on task 03.

Use only `taskId`, `title`, `assignedTo` and `dependsOn` in each DAG node. Push the project
directory with `filesync` action `push`, then call `projectflow` action `ready_nodes`.

## Delegation

For each node returned by `ready_nodes`, use `taskflow` action `delegate_task` with only
`projectId`, `taskId`, `roomId` and `spec`. `roomId` is the Team Room above. After delegation,
push the Project directory, then send the assigned Worker a Team Room message using the
`message` tool action `send` and target
`room:!9XvFcALqzJGB9VEPS8:matrix-local.hiclaw.io:18080`.

Task specs must enforce:

- 01 Auditor: run
  `python3 /host-share/sceneguard_client.py audit mixed_valid_degenerate.glb web-realtime-v0.5-visual-demo.json agentteams-auto-20260825-003`;
  retain actual JSON and publish a valid result.md.
- 02 Planner: inspect the accepted Auditor result; confirm only
  `remove_degenerate_triangles`; do not mutate assets; publish a machine-readable plan decision.
- 03 Executor: run
  `python3 /host-share/sceneguard_client.py pipeline mixed_valid_degenerate.glb web-realtime-v0.5-visual-demo.json agentteams-auto-20260825-003`
  exactly once except for identical transport/schema retries; retain actual JSON.
- 04 Verifier: independently call the client `artifacts` and `artifact` commands for the fixed job;
  verify the six hash/profile/gate invariants in the parent spec and publish actual evidence.

## Result handling

When a Worker reports completion, call `taskflow` action `check_task`. A Worker SUCCESS is only a
candidate. If accepted, update the corresponding Project plan marker to `[x]`, push the Project,
call `ready_nodes`, and delegate the next returned node. Never use `filesync.write`; Project result
content must be written through the runtime file tool, and synchronization only uses
`filesync pull`, `push`, `stat` or `list`.

After task 04 is accepted, write the parent JSON result required by
`p0-autonomous-repair.md`, complete the Project using `projectflow` action `complete_project`, push
the Project and parent task result, then report once to Manager. On any schema rejection or tool
failure, stop with a truthful blocker; no operator correction is allowed.
