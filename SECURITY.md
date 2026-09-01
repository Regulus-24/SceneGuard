# Security Boundary

SceneGuard is a competition prototype, not an internet-facing production service.

## Enforced controls

- MVP accepts configured-root `.glb` files or a raw user upload capped at 32 MiB. Uploads must have a plain `.glb` name, pass GLB 2.0 parsing, and are stored under an isolated server-generated ID.
- Original assets are copied read-only; all writes stay inside a per-Job workspace.
- PatchPlan hashes bind a repair to the audited working copy.
- Repair operations are enumerated; arbitrary scripts, shell commands and paths are rejected.
- Embedded texture repair accepts only PNG/JPEG bytes referenced by a GLB bufferView, preserves aspect ratio, and requires a plan-and-asset-bound L2 approval under the demo texture Profile.
- Checkpoints and published artifacts use temporary copies, SHA-256 verification and atomic replacement.
- Only `PASS` and `REPAIRED_PASS` may create a published asset.
- All Job events share one correlation `trace_id`; Metrics and Gate evidence are written without secrets or binary payloads.
- HTTP responses carry a bounded `X-Request-ID`. Pipeline requests can use a bounded `Idempotency-Key`; only its SHA-256 is retained, completed responses are integrity-checked, and key reuse with different input is rejected.
- The Gateway may run without a token only on `127.0.0.1`, `localhost` or `::1`. Non-loopback binding requires a Bearer token loaded from the `SCENEGUARD_API_TOKEN` environment variable.
- The Loop Supervisor accepts an engineering Worker only as explicit argv and always uses `shell=False`; it applies a wall-clock timeout, stores no Worker stdout/stderr, takes a reproducible recovery archive first and stops on a lower Core score.
- Release evidence is accepted only from bounded UTF-8 text files under `evidence/`. The benchmark scans the evidence declaration and every referenced trace for common API-key, Bearer-token, private-key, credential-assignment and personal home-path patterns; a self-asserted `secret_scan_passed` flag cannot bypass findings.

## Known limitations

- There is no user/role database, token rotation service, rate limiter or production sandbox.
- The HTTP demo should not be exposed directly to the public internet.
- GLB CPU/memory isolation still depends on the future container runtime.
- Idempotency serialization is process-local plus persistent receipts; multiple Gateway processes must not share one `jobs_root`. There is no hard execution deadline until the container Worker boundary is available.
- Real AgentTeams and official cloud Skill permissions have not yet been validated.
- The dependency surface now includes the pinned Pillow 11.3.0 package for image resampling; its upstream license and purpose are disclosed in `THIRD_PARTY_NOTICES.md`.
- The Loop Supervisor is not a filesystem or network sandbox for the configured Worker. A Worker inherits the launching user's permissions and environment. The supervisor does not include a built-in Codex adapter and does not automatically restore source files; it preserves a recovery ZIP and stops so a human or isolated worktree process can review the regression safely.

Do not report a vulnerability with confidential employer/customer content. Reproduce it using a minimal self-created GLB and describe the affected rule, expected boundary and observed behavior.
