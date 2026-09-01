# SceneGuard P0 autonomous repair acceptance task

Run this task entirely inside the existing `sceneguard-real` AgentTeams team. No human or
operator may repair a payload, invoke a missing tool, edit an artifact, join a room, restart a
Worker, or substitute a Worker after dispatch. If any such action becomes necessary, return
`FAILED_OPERATOR_REQUIRED`; do not relabel the run as autonomous.

## Fixed input

- asset: `mixed_valid_degenerate.glb`
- profile: `web-realtime-v0.5-visual-demo.json`
- job id: supplied in the dispatch message; every role must use the same id
- expected finding: `mesh.degenerate_triangles`
- only permitted repair: `remove_degenerate_triangles`
- expected terminal gate: `REPAIRED_PASS`

## Required role sequence

1. TeamLeader records `DISPATCHED`, assigns the fixed job id and delegates to all four named
   business Workers. It must not execute SceneGuard business tools itself.
2. Asset Auditor calls `/host-share/sceneguard_client.py audit` and returns the actual JSON
   response. Model prose is not evidence.
3. Repair Planner checks the audit response, the fixed Profile and repair whitelist. It returns
   a machine-readable plan decision. It has read-only access and must not run the repair.
4. Repair Executor calls `/host-share/sceneguard_client.py pipeline` exactly once for the fixed
   input and job id. Transport/schema failures may be retried twice with the identical payload;
   a business failure must not be retried under a new job id.
5. Regression Verifier independently retrieves `audit_report.json`, `patch_plan.json`,
   `execution_report.json`, `regression_report.json`, `gate_decision.json`,
   `release_attestation.json` and `trace.jsonl`. It verifies hashes, profile binding, terminal
   gate and artifact existence. It must not trust the Executor's prose.
6. TeamLeader aggregates the four Worker results and writes the final result to the parent task.

## Final result contract

The final result must contain one JSON object with these fields:

```json
{
  "status": "PASS or FAIL",
  "autonomous": true,
  "operator_actions_after_dispatch": 0,
  "team": "sceneguard-real",
  "job_id": "the fixed dispatch job id",
  "asset": "mixed_valid_degenerate.glb",
  "profile": "web-realtime-v0.5-visual-demo.json",
  "gate_state": "REPAIRED_PASS",
  "roles_completed": [
    "sceneguard-real-asset-auditor",
    "sceneguard-real-repair-planner",
    "sceneguard-real-repair-executor",
    "sceneguard-real-regression-verifier"
  ],
  "request_ids": [],
  "input_sha256": "64 lowercase hex characters",
  "output_sha256": "64 lowercase hex characters",
  "artifact_refs": [],
  "invariants": {
    "single_job_id": true,
    "profile_bound": true,
    "plan_bound_to_input": true,
    "execution_bound_to_regression": true,
    "gate_matches_result": true,
    "release_hash_matches_published": true
  },
  "failure_code": null
}
```

Set `autonomous` to `false` whenever any operator action occurred. A truthful failed result is
acceptable evidence for improving the automation; fabricated success is not.
