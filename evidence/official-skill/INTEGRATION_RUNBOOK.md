# Alibaba Cloud official Skill integration runbook

## Selected first integration

Use `alibabacloud-resourcecenter-search` for the first real cloud evidence path. It is
the official quick-start example, supports Codex, and can run under the read-only
`AliyunResourceCenterReadOnlyAccess` RAM policy. SceneGuard uses it to discover and
confirm candidate OSS evidence destinations before any upload capability is allowed.

Official references:

- Portal entry: https://skills.aliyun.com/skills/alibabacloud-resourcecenter-search
- Quick start: https://help.aliyun.com/zh/skillsportal/quickly-use-alibaba-cloud-skills
- Portal overview: https://help.aliyun.com/zh/skillsportal/learn-about-the-alibaba-cloud-agent-skills-portal

## Preconditions owned by the team

1. A real-name verified Alibaba Cloud test account and an isolated RAM identity.
2. Alibaba Cloud CLI 3.3.3 or later and Node.js 18 or later.
3. Resource Center enabled and only `AliyunResourceCenterReadOnlyAccess` granted.
4. Credentials configured outside the repository. Never paste or capture AccessKey
   values, session tokens, CLI profile files, environment dumps, or full account ids.

The local installation provenance and versions are recorded in `INSTALLATION_RECEIPT.md`. This is not runtime evidence. Before configuring Alibaba Cloud CLI, the team must explicitly select a default Region; the official Skill forbids the Agent from assuming it.

## Install

Run from the SceneGuard project on the designated integration machine:

```powershell
npx skills add aliyun/alibabacloud-aiops-skills --skill alibabacloud-resourcecenter-search --agent codex -y --full-depth
npx skills ls
aliyun version
aliyun configure list
```

The last command is only a readiness check. Screenshots and logs must redact identity
fields and must never include credential values.

## Success case

Ask the Agent to query Resource Center for OSS resources available to the test identity
and return only a sanitized count, regions and masked resource ids. Capture:

- installed Skill name/version and official portal URL;
- timestamp, request/trace id and sanitized operation summary;
- proof that the Skill, rather than an invented direct call, was loaded and used;
- no-secret scan result for all retained logs/screenshots.

An empty resource list is a valid API result only if the Trace proves authentication and
the real official Skill call succeeded. It is not evidence of Artifact upload.

## Failure case

In a separate clean CLI profile with no credential, invoke the same read-only request and
capture the real authentication failure code. Do not revoke a working identity or weaken
the success identity. The pipeline fallback is the local hash-verified ZIP; it must not
blindly retry, switch credentials, create resources, or claim cloud archival.

## Promote evidence

Copy `integration.template.json` to `integration.json` only after replacing every TODO
with real, sanitized values. Set `status` to `PASS`, `failure_tested` and
`secret_scan_passed` to `true`, and ensure every `trace_refs` target exists. Then run:

```powershell
python scripts/run_benchmark.py --target release --output reports/benchmark-latest.json
```

The validator rejects non-Aliyun source domains, placeholders, missing failure tests,
missing replacement strategy and empty Trace references.
