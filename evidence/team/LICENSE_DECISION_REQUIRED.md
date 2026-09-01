# SceneGuard license decision history

Release evidence is intentionally blocked because two retained team statements conflict:

- `Agent比赛/初赛交付_20260816/TEAM_CONFIRMATION.json` records
  `ALL_RIGHTS_RESERVED_NOT_PUBLIC` and `NOT_PUBLIC_WITH_VERIFIABLE_REVIEW_MATERIALS`.
- The submitted V3 deck states Apache-2.0.
- On 2026-08-25 the project owner/final submitter selected MIT and authorized adding the
  repository `LICENSE`; see `MIT_SELECTION_RECORDED.md`.
- On 2026-08-31 the final submitter confirmed the team's decision to follow the semifinal
  judge guidance and replace MIT with Apache-2.0; see `APACHE_2_0_SELECTION_RECORDED.md`.

Apache-2.0 is now frozen as the repository license. The retained machine-readable decision
supersedes both the older all-rights-reserved policy and the interim MIT decision.
The final choice must be reflected identically in the deck, video, README and code package.

Completed close-out:

1. The team selected `Apache-2.0` and the public-distribution scope.
2. Names, roles, public-bio authorization, public-asset review and timestamp are recorded.
3. `evidence/team/release-decisions.json` uses SPDX identifier `Apache-2.0` and all three names.
4. The repository, README, next deck and video must use Apache-2.0.
5. Run `powershell -ExecutionPolicy Bypass -File scripts/verify_p0.ps1` after material updates.
