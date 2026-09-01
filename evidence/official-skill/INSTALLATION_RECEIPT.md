# Official Skill installation receipt

Status: `PRECONDITIONS_READY; NOT CLOUD RUNTIME EVIDENCE`

Observed on 2026-08-10:

- Node.js `v24.19.0` and npm `11.17.0` are installed.
- The Node.js x64 MSI SHA-256 is `f0f66c2a80c08a30a5ab5179ee9ea9e45f9b46289436a8cc87ff833b852db351`; it matches the official `SHASUMS256.txt`, and its Authenticode signer is the OpenJS Foundation.
- Alibaba Cloud CLI `3.3.18` is installed for the current user.
- The Alibaba Cloud CLI release ZIP SHA-256 is `b09db59c9cbdbe43c52a4d9bfa4cb5145c18c181120c13f6c78e483a3dcfcbd5`; it matches the digest returned by the official GitHub Release API.
- `alibabacloud-resourcecenter-search` was pinned from official repository commit `93b63c6c208c390839793b22298956f2f2d4b646` and installed project-locally under `.codex/skills/`.
- The installed `SKILL.md` SHA-256 is `6f6290be0a9f0c6ad93a3a1e3a8be5bee5eee07ce3f13c89a89f2a7b6258eddd`.

No Alibaba Cloud credential was read, printed or stored in the SceneGuard repository. No Resource Center API call has been made yet. The Skill preflight stopped because the required default Region and credential profile still need user-owned configuration. AI Mode was disabled before stopping.

This receipt proves installation provenance only. It must not be promoted to `integration.json`; real success and isolated failure traces are still required.

Official sources:

- https://help.aliyun.com/zh/skillsportal/quickly-use-alibaba-cloud-skills
- https://github.com/aliyun/alibabacloud-aiops-skills
- https://help.aliyun.com/en/cli/install-update-alibaba-cloud-cli
- https://nodejs.org/download/release/v24.19.0/
