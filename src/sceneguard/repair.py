from __future__ import annotations

import copy
import hashlib
import io
import math
import os
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .glb import COMPONENT_BYTES, COMPONENT_FORMATS, build_glb, collection, decode_accessor, parse_glb


class RepairError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepairResult:
    operation: str
    before_sha256: str
    after_sha256: str
    removed_triangle_count: int
    changed_primitives: tuple[dict[str, int], ...]
    bytes_before: int
    bytes_after: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_primitives"] = list(payload["changed_primitives"])
        return payload


@dataclass(frozen=True)
class TextureResizeResult:
    operation: str
    before_sha256: str
    after_sha256: str
    resized_image_count: int
    changed_images: tuple[dict[str, Any], ...]
    max_dimension: int
    bytes_before: int
    bytes_after: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_images"] = list(payload["changed_images"])
        return payload


def remove_degenerate_triangles(path: str | Path, expected_sha256: str) -> RepairResult:
    target = Path(path)
    before = target.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    if before_hash != expected_sha256:
        raise RepairError("working copy hash does not match the approved PatchPlan")

    document = parse_glb(target)
    payload = copy.deepcopy(document.json)
    binary = bytearray(document.binary)
    accessors = collection(payload, "accessors")
    views = collection(payload, "bufferViews")
    removed_total = 0
    changed: list[dict[str, int]] = []

    for mesh_index, mesh in enumerate(collection(payload, "meshes")):
        if not isinstance(mesh, dict) or not isinstance(mesh.get("primitives"), list):
            continue
        for primitive_index, primitive in enumerate(mesh["primitives"]):
            if not isinstance(primitive, dict) or primitive.get("mode", 4) != 4:
                continue
            attributes = primitive.get("attributes")
            position_index = attributes.get("POSITION") if isinstance(attributes, dict) else None
            index_accessor_index = primitive.get("indices")
            if not isinstance(position_index, int) or not isinstance(index_accessor_index, int):
                continue
            if not (0 <= position_index < len(accessors) and 0 <= index_accessor_index < len(accessors)):
                continue

            positions = decode_accessor(document, position_index)
            indices = decode_accessor(document, index_accessor_index)
            if len(indices) % 3:
                raise RepairError("indexed TRIANGLES accessor count must be divisible by 3")
            kept: list[int] = []
            removed_here = 0
            for offset in range(0, len(indices), 3):
                triangle = (indices[offset], indices[offset + 1], indices[offset + 2])
                if any(not isinstance(value, int) or value < 0 or value >= len(positions) for value in triangle):
                    raise RepairError("cannot repair a primitive with out-of-bounds indices")
                if _is_degenerate(positions[triangle[0]], positions[triangle[1]], positions[triangle[2]]):
                    removed_here += 1
                else:
                    kept.extend(triangle)
            if not removed_here:
                continue

            accessor = accessors[index_accessor_index]
            if not isinstance(accessor, dict) or accessor.get("type") != "SCALAR":
                raise RepairError("indices accessor must be SCALAR")
            component_type = accessor.get("componentType")
            if component_type not in {5121, 5123, 5125}:
                raise RepairError("indices accessor must use an unsigned integer component type")
            view_index = accessor.get("bufferView")
            if not isinstance(view_index, int) or not 0 <= view_index < len(views):
                raise RepairError("indices accessor has no valid bufferView")
            view = views[view_index]
            if not isinstance(view, dict) or view.get("buffer", 0) != 0:
                raise RepairError("repair only supports the embedded GLB buffer")
            component_bytes = COMPONENT_BYTES[component_type]
            stride = view.get("byteStride", component_bytes)
            if stride != component_bytes:
                raise RepairError("repair does not support strided index accessors")
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            if not isinstance(start, int) or start < 0:
                raise RepairError("indices accessor offset is invalid")
            fmt = "<" + COMPONENT_FORMATS[component_type]
            old_count = len(indices)
            for value_index, value in enumerate(kept):
                struct.pack_into(fmt, binary, start + value_index * component_bytes, value)
            for value_index in range(len(kept), old_count):
                struct.pack_into(fmt, binary, start + value_index * component_bytes, 0)
            accessor["count"] = len(kept)
            if kept:
                accessor["min"] = [min(kept)]
                accessor["max"] = [max(kept)]
            else:
                accessor.pop("min", None)
                accessor.pop("max", None)
            removed_total += removed_here
            changed.append(
                {
                    "mesh": mesh_index,
                    "primitive": primitive_index,
                    "old_index_count": old_count,
                    "new_index_count": len(kept),
                    "removed_triangles": removed_here,
                }
            )

    if removed_total == 0:
        raise RepairError("no eligible degenerate triangles were found")

    repaired = build_glb(payload, bytes(binary))
    parse_path = target.with_suffix(".repair.tmp")
    parse_path.write_bytes(repaired)
    try:
        parse_glb(parse_path)
        os.replace(parse_path, target)
    except Exception:
        parse_path.unlink(missing_ok=True)
        raise
    after_hash = hashlib.sha256(repaired).hexdigest()
    return RepairResult(
        operation="remove_degenerate_triangles",
        before_sha256=before_hash,
        after_sha256=after_hash,
        removed_triangle_count=removed_total,
        changed_primitives=tuple(changed),
        bytes_before=len(before),
        bytes_after=len(repaired),
    )


def resize_embedded_textures(
    path: str | Path,
    expected_sha256: str,
    max_dimension: int,
) -> TextureResizeResult:
    if not isinstance(max_dimension, int) or max_dimension <= 0:
        raise RepairError("max_dimension must be a positive integer")
    target = Path(path)
    before = target.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    if before_hash != expected_sha256:
        raise RepairError("working copy hash does not match the approved PatchPlan")

    document = parse_glb(target)
    payload = copy.deepcopy(document.json)
    binary = bytearray(document.binary)
    views = collection(payload, "bufferViews")
    images = collection(payload, "images")
    changed: list[dict[str, Any]] = []

    for image_index, image in enumerate(images):
        if not isinstance(image, dict) or not isinstance(image.get("bufferView"), int):
            continue
        view_index = image["bufferView"]
        if not 0 <= view_index < len(views):
            raise RepairError("embedded image references an invalid bufferView")
        view = views[view_index]
        if not isinstance(view, dict) or view.get("buffer", 0) != 0:
            raise RepairError("texture repair only supports the embedded GLB buffer")
        offset = view.get("byteOffset", 0)
        length = view.get("byteLength")
        if not isinstance(offset, int) or not isinstance(length, int) or offset < 0 or length <= 0:
            raise RepairError("embedded image bufferView has an invalid range")
        source = bytes(document.binary[offset : offset + length])
        try:
            with Image.open(io.BytesIO(source)) as opened:
                opened.load()
                old_width, old_height = opened.size
                if max(old_width, old_height) <= max_dimension:
                    continue
                scale = max_dimension / max(old_width, old_height)
                new_size = (max(1, round(old_width * scale)), max(1, round(old_height * scale)))
                resized = opened.resize(new_size, Image.Resampling.LANCZOS)
                mime_type = image.get("mimeType")
                if mime_type == "image/jpeg":
                    if resized.mode not in {"L", "RGB"}:
                        resized = resized.convert("RGB")
                    output_format = "JPEG"
                    save_options = {"quality": 90, "optimize": False, "progressive": False}
                elif mime_type == "image/png":
                    output_format = "PNG"
                    save_options = {"compress_level": 9, "optimize": False}
                else:
                    raise RepairError("texture repair only supports embedded PNG and JPEG images")
                output = io.BytesIO()
                resized.save(output, format=output_format, **save_options)
                encoded = output.getvalue()
        except RepairError:
            raise
        except Exception as exc:
            raise RepairError(f"cannot decode embedded image {image_index}: {exc}") from exc

        padding = (-len(binary)) % 4
        if padding:
            binary.extend(b"\x00" * padding)
        new_offset = len(binary)
        binary.extend(encoded)
        new_view_index = len(views)
        views.append({"buffer": 0, "byteOffset": new_offset, "byteLength": len(encoded)})
        image["bufferView"] = new_view_index
        changed.append(
            {
                "image": image_index,
                "mime_type": image.get("mimeType"),
                "old_width": old_width,
                "old_height": old_height,
                "new_width": new_size[0],
                "new_height": new_size[1],
                "old_bytes": len(source),
                "new_bytes": len(encoded),
            }
        )

    if not changed:
        raise RepairError("no eligible embedded texture exceeded the configured dimension")
    buffers = collection(payload, "buffers")
    if not buffers or not isinstance(buffers[0], dict) or buffers[0].get("uri"):
        raise RepairError("texture repair requires one embedded GLB buffer")
    buffers[0]["byteLength"] = len(binary)

    repaired = build_glb(payload, bytes(binary))
    parse_path = target.with_suffix(".repair.tmp")
    parse_path.write_bytes(repaired)
    try:
        parse_glb(parse_path)
        os.replace(parse_path, target)
    except Exception:
        parse_path.unlink(missing_ok=True)
        raise
    after_hash = hashlib.sha256(repaired).hexdigest()
    return TextureResizeResult(
        operation="resize_embedded_textures",
        before_sha256=before_hash,
        after_sha256=after_hash,
        resized_image_count=len(changed),
        changed_images=tuple(changed),
        max_dimension=max_dimension,
        bytes_before=len(before),
        bytes_after=len(repaired),
    )


def _is_degenerate(a: Any, b: Any, c: Any) -> bool:
    if a == b or b == c or a == c:
        return True
    if not all(math.isfinite(float(value)) for point in (a, b, c) for value in point):
        return False
    ab = (float(b[0]) - float(a[0]), float(b[1]) - float(a[1]), float(b[2]) - float(a[2]))
    ac = (float(c[0]) - float(a[0]), float(c[1]) - float(a[1]), float(c[2]) - float(a[2]))
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return sum(value * value for value in cross) <= 1e-24
