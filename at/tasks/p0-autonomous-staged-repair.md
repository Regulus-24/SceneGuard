# P0 staged autonomous repair

Run one zero-operator SceneGuard AgentTeams workflow.

- Asset: `mixed_valid_degenerate.glb`
- Profile: `web-realtime-v0.5-visual-demo.json`
- Job ID: use the exact ID supplied by the dispatch metadata and message
- Required terminal gate: `REPAIRED_PASS`

The TeamLeader must load `asset-profile`, bind the Goal Contract, create one Project and
the serial audit -> plan -> execute -> verify DAG. Assign each node to its named specialist.
Do not call the legacy `/v1/pipeline/run` route.

Required Skill coverage for this run:

- TeamLeader: `asset-profile`;
- Asset Auditor: `package-audit` and `mesh-validate`;
- Repair Planner: `repair-plan`;
- Repair Executor: `mesh-safe-repair`;
- Regression Verifier: independent `package-audit`, `mesh-validate` and `regression-verify`.

At every handoff, accept only the complete SceneGuard HTTP JSON stored in the Worker task
deliverable. Keep the Job ID and profile unchanged and propagate the exact frozen Plan ID.
Return the Project ID, four Task IDs, original Matrix event IDs, five Agent identities,
Skill IDs/versions, PatchPlan operation/risk, execution before/after hashes, regression
state, GateDecision, release hash, artifact hashes and evidence paths. No operator input
