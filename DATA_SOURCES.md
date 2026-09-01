# Data Sources

The current dataset contains twelve minimal GLB files generated from scratch by `scripts/generate_samples.py`, plus three license-cleared public Khronos test assets sourced from GitHub. No company, customer or employer production asset is used. These 15 samples are regression fixtures and compatibility cases, not an industry-generalization benchmark.

| Asset | Source | Purpose |
|---|---|---|
| `clean_triangle.glb` | Self-created | Clean baseline |
| `over_triangle_budget.glb` | Self-created | Profile budget failure |
| `broken_reference.glb` | Self-created | Invalid accessor reference |
| `accessor_out_of_bounds.glb` | Self-created | BufferView/accessor bounds failure |
| `degenerate_triangle.glb` | Self-created | Repairable repeated-index triangle |
| `degenerate_collinear.glb` | Self-created | Repairable zero-area collinear triangle |
| `degenerate_duplicate_positions.glb` | Self-created | Repairable equal-position triangle |
| `degenerate_repeated_u8.glb` | Self-created | Repeated index encoded as UNSIGNED_BYTE |
| `degenerate_repeated_u32.glb` | Self-created | Repeated index encoded as UNSIGNED_INT |
| `mixed_valid_degenerate.glb` | Self-created | Preserve a valid triangle while removing one degenerate triangle |
| `external_buffer.glb` | Self-created | GLB single-file policy failure |
| `oversized_texture.glb` | Self-created | Approval-bound embedded texture resize |
| `public/BoxVertexColors.glb` | KhronosGroup/glTF-Sample-Assets; Marco Hutter; CC0-1.0 | Real public GLB compatibility and Profile behavior |
| `public/Avocado.glb` | KhronosGroup/glTF-Sample-Assets; Microsoft; CC0-1.0 | Real textured asset compatibility |
| `public/BoomBox.glb` | KhronosGroup/glTF-Sample-Assets; Microsoft; CC0-1.0 | Real textured asset compatibility |

The machine-readable registry is `samples/source_manifest.json`; the Golden expectations are `evaluation/golden_findings.json`. Regenerating the self-created samples is preferred to redistributing opaque binaries. Every public asset is pinned by upstream commit, source/license URL, byte size and SHA-256 in its adjacent `.source.json`; the dedicated read-only Profile is `profiles/public-gltf-validation-v0.1.json`.

`python scripts/sync_public_assets.py` performs a network-free verification of all retained
public bytes. `--download` reproducibly fetches only full-commit-pinned
`raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets` URLs and writes an asset only
after its license metadata, byte size and SHA-256 pass. The receipt is
`reports/public-asset-sync-latest.json`. This is an open-source GitHub asset-platform
intake, not a claim of private studio, customer or production DAM integration.

The team code and self-created assets use Apache-2.0. Public assets retain CC0-1.0; their source records are `TEAM_REVIEWED`. The 2026-08-31 three-asset runtime receipt is `evidence/public-assets/runtime-20260831.json`.
