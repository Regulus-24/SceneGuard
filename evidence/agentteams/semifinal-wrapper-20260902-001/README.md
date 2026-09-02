# Semifinal runnable Demo evidence

Run ID: `semifinal-wrapper-20260902-001`

This run was produced on 2026-09-02 by `scripts/start_semifinal_demo.ps1 -Mode AgentTeams`. It completed with one TeamLeader, four Workers, zero operator actions after dispatch, `REPAIRED_PASS`, and all hash invariants passing. End-to-end AgentTeams duration was 322312 ms.

- `agent-control/run-result.json`: final machine-readable summary and claim boundary.
- `agent-control/control-trace.jsonl`: ordered coordination events.
- `agent-control/00-*.json` through `05-*.json`: model decisions and Leader acceptances.
- `business-artifacts/`: audit, PatchPlan, execution, regression, release and trace evidence.

Claim boundary: validated five-Agent zero-operator Supervisor mode. The host enforces the finite-state machine; this is not represented as free-form native Matrix orchestration.
