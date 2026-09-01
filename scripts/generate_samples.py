from __future__ import annotations

import hashlib
import io
import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"
JSON_CHUNK_TYPE = 0x4E4F534A
BIN_CHUNK_TYPE = 0x004E4942


def pad(data: bytes, fill: bytes) -> bytes:
    return data + fill * ((-len(data)) % 4)


def glb_bytes(payload: dict, binary: bytes = b"") -> bytes:
    json_data = pad(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), b" ")
    chunks = struct.pack("<II", len(json_data), JSON_CHUNK_TYPE) + json_data
    if binary:
        bin_data = pad(binary, b"\x00")
        chunks += struct.pack("<II", len(bin_data), BIN_CHUNK_TYPE) + bin_data
    total = 12 + len(chunks)
    return struct.pack("<4sII", b"glTF", 2, total) + chunks


def mesh_payload(
    two_triangles: bool = False,
    mixed_triangles: bool = False,
    broken_position_ref: bool = False,
    accessor_overflow: bool = False,
    degenerate: bool = False,
    degenerate_kind: str | None = None,
    index_component_type: int = 5123,
    with_uvs: bool = False,
) -> tuple[dict, bytes]:
    if two_triangles or mixed_triangles:
        positions = [
            (-1.0, -1.0, 0.0),
            (1.0, -1.0, 0.0),
            (1.0, 1.0, 0.0),
            (-1.0, 1.0, 0.0),
        ]
        indices = [0, 1, 2, 0, 0, 3] if mixed_triangles else [0, 1, 2, 0, 2, 3]
    else:
        if degenerate_kind == "collinear":
            positions = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
            indices = [0, 1, 2]
        elif degenerate_kind == "duplicate_positions":
            positions = [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
            indices = [0, 1, 2]
        else:
            positions = [(0.0, 1.0, 0.0), (-1.0, -1.0, 0.0), (1.0, -1.0, 0.0)]
            indices = [0, 0, 2] if degenerate or degenerate_kind == "repeated_index" else [0, 1, 2]

    position_bytes = b"".join(struct.pack("<fff", *item) for item in positions)
    index_formats = {5121: "<B", 5123: "<H", 5125: "<I"}
    if index_component_type not in index_formats:
        raise ValueError("unsupported generated index component type")
    index_bytes = b"".join(struct.pack(index_formats[index_component_type], item) for item in indices)
    uv_bytes = b""
    if with_uvs:
        min_x = min(item[0] for item in positions)
        max_x = max(item[0] for item in positions)
        min_y = min(item[1] for item in positions)
        max_y = max(item[1] for item in positions)
        span_x = max_x - min_x or 1.0
        span_y = max_y - min_y or 1.0
        uvs = [((item[0] - min_x) / span_x, (item[1] - min_y) / span_y) for item in positions]
        uv_bytes = b"".join(struct.pack("<ff", *item) for item in uvs)
    binary = position_bytes + index_bytes + uv_bytes
    position_accessor = 99 if broken_position_ref else 0
    payload = {
        "asset": {"version": "2.0", "generator": "SceneGuard self-created sample generator"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": position_accessor}, "indices": 1, "mode": 4}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(position_bytes), "byteLength": len(index_bytes), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 99 if accessor_overflow else len(positions),
                "type": "VEC3",
                "min": [min(item[i] for item in positions) for i in range(3)],
                "max": [max(item[i] for item in positions) for i in range(3)],
            },
            {
                "bufferView": 1,
                "componentType": index_component_type,
                "count": len(indices),
                "type": "SCALAR",
                "min": [min(indices)],
                "max": [max(indices)],
            },
        ],
    }
    if with_uvs:
        uv_offset = len(position_bytes) + len(index_bytes)
        payload["bufferViews"].append(
            {"buffer": 0, "byteOffset": uv_offset, "byteLength": len(uv_bytes), "target": 34962}
        )
        payload["accessors"].append(
            {"bufferView": 2, "componentType": 5126, "count": len(positions), "type": "VEC2"}
        )
        payload["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"] = 2
    return payload, binary


def write(name: str, payload: dict, binary: bytes = b"") -> None:
    (SAMPLES / name).write_bytes(glb_bytes(payload, binary))


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)

    payload, binary = mesh_payload()
    write("clean_triangle.glb", payload, binary)

    payload, binary = mesh_payload(two_triangles=True)
    write("over_triangle_budget.glb", payload, binary)

    payload, binary = mesh_payload(broken_position_ref=True)
    write("broken_reference.glb", payload, binary)

    payload, binary = mesh_payload(accessor_overflow=True)
    write("accessor_out_of_bounds.glb", payload, binary)

    payload, binary = mesh_payload(degenerate=True)
    write("degenerate_triangle.glb", payload, binary)

    payload, binary = mesh_payload(degenerate_kind="collinear")
    write("degenerate_collinear.glb", payload, binary)

    payload, binary = mesh_payload(degenerate_kind="duplicate_positions")
    write("degenerate_duplicate_positions.glb", payload, binary)

    payload, binary = mesh_payload(degenerate_kind="repeated_index", index_component_type=5121)
    write("degenerate_repeated_u8.glb", payload, binary)

    payload, binary = mesh_payload(degenerate_kind="repeated_index", index_component_type=5125)
    write("degenerate_repeated_u32.glb", payload, binary)

    payload, binary = mesh_payload(mixed_triangles=True)
    write("mixed_valid_degenerate.glb", payload, binary)

    payload, binary = mesh_payload(with_uvs=True)
    texture = Image.new("RGB", (2048, 512), "#246bfd")
    drawing = ImageDraw.Draw(texture)
    drawing.rectangle((1024, 0, 2047, 511), fill="#0a8f63")
    encoded = io.BytesIO()
    texture.save(encoded, format="PNG", compress_level=9, optimize=False)
    texture_bytes = encoded.getvalue()
    texture_offset = len(binary) + ((-len(binary)) % 4)
    binary = binary + b"\x00" * (texture_offset - len(binary)) + texture_bytes
    payload["bufferViews"].append(
        {"buffer": 0, "byteOffset": texture_offset, "byteLength": len(texture_bytes)}
    )
    payload["buffers"][0]["byteLength"] = len(binary)
    payload["images"] = [{"bufferView": len(payload["bufferViews"]) - 1, "mimeType": "image/png"}]
    payload["textures"] = [{"source": 0}]
    payload["materials"] = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]
    payload["meshes"][0]["primitives"][0]["material"] = 0
    write("oversized_texture.glb", payload, binary)

    external = {
        "asset": {"version": "2.0", "generator": "SceneGuard self-created sample generator"},
        "buffers": [{"byteLength": 12, "uri": "external.bin"}],
        "scenes": [{}],
        "scene": 0,
    }
    write("external_buffer.glb", external)

    manifest = {
        "schema_version": "0.1",
        "source_type": "SELF_CREATED",
        "generator": "scripts/generate_samples.py",
        "license_status": "team-created samples are distributed under Apache-2.0; each public sample retains its recorded upstream license",
        "samples": {
            "clean_triangle.glb": {"expected_gate": "PASS", "purpose": "one valid triangle"},
            "over_triangle_budget.glb": {"expected_gate": "REJECTED", "purpose": "two triangles exceed demo profile max=1"},
            "broken_reference.glb": {"expected_gate": "REJECTED", "purpose": "POSITION points to missing accessor"},
            "accessor_out_of_bounds.glb": {"expected_gate": "REJECTED", "purpose": "accessor count exceeds bufferView"},
            "degenerate_triangle.glb": {"expected_gate": "REJECTED", "purpose": "triangle repeats one vertex index"},
            "degenerate_collinear.glb": {"expected_gate": "REJECTED", "purpose": "three distinct vertices are collinear"},
            "degenerate_duplicate_positions.glb": {"expected_gate": "REJECTED", "purpose": "two indices reference equal positions"},
            "degenerate_repeated_u8.glb": {"expected_gate": "REJECTED", "purpose": "repeated index with UNSIGNED_BYTE indices"},
            "degenerate_repeated_u32.glb": {"expected_gate": "REJECTED", "purpose": "repeated index with UNSIGNED_INT indices"},
            "mixed_valid_degenerate.glb": {"expected_gate": "REJECTED", "purpose": "one valid and one degenerate triangle in the same primitive"},
            "oversized_texture.glb": {"expected_gate": "REJECTED", "purpose": "one embedded 2048x512 PNG exceeds the demo texture budget"},
            "external_buffer.glb": {"expected_gate": "REJECTED", "purpose": "GLB points to external buffer URI"}
        }
    }
    for public_source in sorted((SAMPLES / "public").glob("*.source.json")):
        source_record = json.loads(public_source.read_text(encoding="utf-8"))
        public_asset = SAMPLES / source_record["local_path"]
        if not public_asset.is_file():
            raise ValueError(f"public asset missing for source record: {public_source.name}")
        digest = hashlib.sha256(public_asset.read_bytes()).hexdigest()
        if digest != source_record.get("sha256") or public_asset.stat().st_size != source_record.get("bytes"):
            raise ValueError(f"public asset does not match pinned source record: {public_asset.name}")
        if source_record.get("review_status") != "TEAM_REVIEWED":
            raise ValueError(f"public asset is not team-reviewed: {public_asset.name}")
        relative_asset = public_asset.relative_to(SAMPLES).as_posix()
        relative_source = public_source.relative_to(SAMPLES).as_posix()
        manifest["source_type"] = "MIXED_SELF_CREATED_AND_LICENSED_PUBLIC"
        manifest["samples"][relative_asset] = {
            "expected_gate": "REJECTED",
            "purpose": "license-cleared real public GLB; evaluated by the dedicated read-only public Profile",
            "source_type": source_record["source_type"],
            "source_record": relative_source,
            "license_spdx": source_record["license_spdx"],
            "redistribution_allowed": source_record["redistribution_allowed"],
            "sha256": source_record["sha256"]
        }
    (SAMPLES / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Registered {len(manifest['samples'])} GLB samples in {SAMPLES}")


if __name__ == "__main__":
    main()
