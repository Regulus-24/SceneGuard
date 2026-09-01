---
name: texture-safe-resize
description: Resize oversized PNG or JPEG textures embedded in a GLB under a hash-bound PatchPlan. Use for profile.max_texture_dimension findings when the active Profile permits resize_embedded_textures and any required L2 approval is present.
---

# Texture safe resize

Operate only on the current Job's `working/candidate.glb`.

1. Require a PatchPlan bound to the working-copy SHA-256.
2. Require operation `resize_embedded_textures` and a positive `max_dimension` copied from the active Profile.
3. Require a verified `pre-repair` checkpoint. For L2 Profiles, require a human approval bound to both `plan_id` and `asset_sha256`.
4. Decode only embedded PNG or JPEG images referenced by `bufferView`; reject external URIs, unsupported image formats, invalid ranges, or undecodable images.
5. Preserve aspect ratio and resize with Lanczos. Append the encoded replacement to the embedded BIN chunk and update only the image's `bufferView` reference and the buffer length.
6. Emit `execution_report.json` with before/after hashes, dimensions, byte counts, and affected image indices.
7. Require an independent full regression. Publish only when `profile.max_texture_dimension`, package bounds, references, and all other required checks pass; otherwise roll back.

Never modify `original/`, accept an arbitrary output path, upscale textures, change geometry, or treat successful encoding as release approval.
