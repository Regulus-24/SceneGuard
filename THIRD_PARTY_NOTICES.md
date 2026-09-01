# Third-Party Notices

## Pillow

- Version: 11.3.0
- Purpose: deterministic decoding and resizing of embedded PNG/JPEG textures for the `texture-safe-resize` Skill.
- License: HPND License.
- Project: https://python-pillow.github.io/

## Public evaluation assets

The following KhronosGroup/glTF-Sample-Assets files are Public / CC0 1.0 Universal and are used for read-only compatibility evaluation:

- `BoxVertexColors.glb` by Marco Hutter;
- `Avocado.glb` and `BoomBox.glb` by Microsoft.

Each adjacent `.source.json` records the exact upstream commit, download and license-evidence URLs, SHA-256, byte size, creator and `TEAM_REVIEWED` status.

## Deterministic runtime

SceneGuard package `0.1.0` requires Python 3.11+ and declares `Pillow==11.3.0` in `pyproject.toml`. Pillow is the only imported third-party dependency of the deterministic SceneGuard package.

## External AgentTeams runtime used for retained evidence

- AgentTeams/HiClaw `1.1.2`: multi-Agent Controller, Manager, Matrix coordination and Worker containers; Apache-2.0; not vendored in the submission repository. Official source: https://github.com/agentscope-ai/HiClaw
- CoPaw runtime bundled with the retained HiClaw environment: runtime for the current TeamLeader and four business Workers; not vendored in the submission repository.
- Hermes Agent v0.10.0: runtime for the four Workers in the historical 2026-08-11 operator-assisted run; project declares MIT; not vendored. Official source: https://github.com/NousResearch/hermes-agent
- Ollama `0.32.5`: local model server; MIT; not vendored. Official source: https://github.com/ollama/ollama
- `qwen3:8b`: local model used by the historical operator-assisted run; the locally stored model metadata reports Apache-2.0.
- `qwen3.5:9b` and `qwen3.5:4b`: local models used by the current validated five-Agent run. Model weights are not included in the submission package.
- `alibabacloud-resourcecenter-search`: official Alibaba Cloud Skill pinned from official repository commit `93b63c6c208c390839793b22298956f2f2d4b646`; the Skill spec is installed project-locally, while cloud runtime evidence remains blocked until the team supplies an explicit default Region and a valid least-privilege CLI profile.

Development machines may contain unrelated software; it is not a SceneGuard dependency unless declared in `pyproject.toml`, a container manifest, or the final runtime evidence.

Last reviewed: 2026-08-31.
