# GOAI Agent Infra Skill requirement interpretation

- Official track page: https://www.goaihz.com/tracks?track=infra
- Checked at: 2026-08-25T14:44:43.2304886+08:00
- Stage: semi-final

The official track page makes Skill a mandatory capability abstraction, but does not require an
Alibaba Cloud official Skill. It allows either Alibaba Cloud official cloud Skills or reusable
project-defined Skills. It also states that recommended projects and cloud products are not scored
by quantity; necessity, interface contracts, replaceability, permission boundaries, end-to-end
evidence and migration cost are the relevant considerations.

SceneGuard satisfies the mandatory Skill requirement through seven versioned, reusable Skills with
input/output contracts, failure handling, safety boundaries and AgentTeams mappings. The installed
Alibaba Cloud Resource Center Skill remains an optional P1 extension. Missing cloud credentials or
runtime evidence must not block the competition Release gate unless the team later makes that cloud
integration part of the submitted end-to-end claim.
