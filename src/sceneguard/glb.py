from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GLB_MAGIC = b"glTF"
GLB_VERSION = 2
JSON_CHUNK_TYPE = 0x4E4F534A
BIN_CHUNK_TYPE = 0x004E4942
COMPONENT_FORMATS = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


class GlbFormatError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GlbChunk:
    chunk_type: int
    data: bytes


@dataclass(frozen=True)
class GlbDocument:
    json: dict[str, Any]
    binary: bytes
    file_size: int
    sha256: str
    chunks: tuple[GlbChunk, ...]


def parse_glb(path: str | Path) -> GlbDocument:
    return parse_glb_bytes(Path(path).read_bytes())


def parse_glb_bytes(data: bytes) -> GlbDocument:
    if len(data) < 12:
        raise GlbFormatError("TRUNCATED_HEADER", "GLB header requires 12 bytes")

    magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
    if magic != GLB_MAGIC:
        raise GlbFormatError("INVALID_MAGIC", "file does not start with the glTF magic bytes")
    if version != GLB_VERSION:
        raise GlbFormatError("UNSUPPORTED_VERSION", f"expected GLB version 2, got {version}")
    if declared_length != len(data):
        raise GlbFormatError(
            "LENGTH_MISMATCH",
            f"header declares {declared_length} bytes but file contains {len(data)}",
        )

    offset = 12
    chunks: list[GlbChunk] = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise GlbFormatError("TRUNCATED_CHUNK_HEADER", "incomplete GLB chunk header")
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        end = offset + chunk_length
        if end > len(data):
            raise GlbFormatError("TRUNCATED_CHUNK", "chunk extends beyond the declared GLB length")
        chunks.append(GlbChunk(chunk_type=chunk_type, data=data[offset:end]))
        offset = end

    if not chunks:
        raise GlbFormatError("MISSING_JSON_CHUNK", "GLB contains no chunks")
    if chunks[0].chunk_type != JSON_CHUNK_TYPE:
        raise GlbFormatError("JSON_NOT_FIRST", "the first GLB chunk must be JSON")

    json_chunks = [chunk for chunk in chunks if chunk.chunk_type == JSON_CHUNK_TYPE]
    bin_chunks = [chunk for chunk in chunks if chunk.chunk_type == BIN_CHUNK_TYPE]
    if len(json_chunks) != 1:
        raise GlbFormatError("JSON_CHUNK_COUNT", "GLB must contain exactly one JSON chunk")
    if len(bin_chunks) > 1:
        raise GlbFormatError("BIN_CHUNK_COUNT", "GLB can contain at most one BIN chunk")

    raw_json = json_chunks[0].data.rstrip(b" \t\r\n\x00")
    try:
        payload = json.loads(raw_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GlbFormatError("INVALID_JSON", f"cannot decode GLB JSON chunk: {exc}") from exc
    if not isinstance(payload, dict):
        raise GlbFormatError("JSON_ROOT_TYPE", "GLB JSON root must be an object")

    asset = payload.get("asset")
    if not isinstance(asset, dict) or not str(asset.get("version", "")).startswith("2"):
        raise GlbFormatError("INVALID_ASSET_VERSION", "glTF asset.version must start with '2'")

    return GlbDocument(
        json=payload,
        binary=bin_chunks[0].data if bin_chunks else b"",
        file_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        chunks=tuple(chunks),
    )


def build_glb(payload: dict[str, Any], binary: bytes = b"") -> bytes:
    """Serialize a GLB 2.0 document with deterministic compact JSON."""
    json_data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    json_data += b" " * ((-len(json_data)) % 4)
    chunks = struct.pack("<II", len(json_data), JSON_CHUNK_TYPE) + json_data
    if binary:
        bin_data = binary + b"\x00" * ((-len(binary)) % 4)
        chunks += struct.pack("<II", len(bin_data), BIN_CHUNK_TYPE) + bin_data
    return struct.pack("<4sII", GLB_MAGIC, GLB_VERSION, 12 + len(chunks)) + chunks


def collection(payload: dict[str, Any], name: str) -> list[Any]:
    value = payload.get(name, [])
    return value if isinstance(value, list) else []


def decode_accessor(document: GlbDocument, accessor_index: int) -> list[Any]:
    """Decode a regular, non-sparse accessor from the embedded BIN chunk."""
    accessors = collection(document.json, "accessors")
    views = collection(document.json, "bufferViews")
    if not isinstance(accessor_index, int) or not 0 <= accessor_index < len(accessors):
        raise GlbFormatError("ACCESSOR_INDEX", f"invalid accessor index: {accessor_index}")
    accessor = accessors[accessor_index]
    if not isinstance(accessor, dict):
        raise GlbFormatError("ACCESSOR_TYPE", "accessor must be an object")
    if "sparse" in accessor:
        raise GlbFormatError("SPARSE_ACCESSOR_UNSUPPORTED", "sparse accessor decoding is not implemented in v0.1")
    view_index = accessor.get("bufferView")
    if not isinstance(view_index, int) or not 0 <= view_index < len(views):
        raise GlbFormatError("ACCESSOR_BUFFER_VIEW", "accessor has no valid bufferView")
    view = views[view_index]
    if not isinstance(view, dict) or view.get("buffer", 0) != 0:
        raise GlbFormatError("ACCESSOR_BUFFER", "only the embedded GLB buffer is supported")

    component_type = accessor.get("componentType")
    type_name = accessor.get("type")
    count = accessor.get("count")
    fmt = COMPONENT_FORMATS.get(component_type)
    component_bytes = COMPONENT_BYTES.get(component_type)
    components = TYPE_COMPONENTS.get(type_name)
    if fmt is None or component_bytes is None or components is None or not isinstance(count, int) or count < 0:
        raise GlbFormatError("ACCESSOR_LAYOUT", "accessor layout is invalid")

    element_bytes = component_bytes * components
    stride = view.get("byteStride", element_bytes)
    if not isinstance(stride, int) or stride < element_bytes:
        raise GlbFormatError("ACCESSOR_STRIDE", "bufferView stride is smaller than one element")
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    if not isinstance(start, int) or start < 0:
        raise GlbFormatError("ACCESSOR_OFFSET", "accessor offset is invalid")

    result: list[Any] = []
    unpack_format = "<" + fmt * components
    for item_index in range(count):
        offset = start + item_index * stride
        end = offset + element_bytes
        if end > len(document.binary):
            raise GlbFormatError("ACCESSOR_OUT_OF_BOUNDS", "accessor extends beyond the embedded BIN chunk")
        values = struct.unpack_from(unpack_format, document.binary, offset)
        result.append(values[0] if components == 1 else values)
    return result


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return PNG/JPEG dimensions without decoding image pixels."""
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = struct.unpack_from(">II", data, 16)
        return width, height
    if len(data) >= 4 and data[:2] == b"\xff\xd8":
        return _jpeg_dimensions(data)
    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    offset = 2
    start_of_frame = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset + 3 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            break
        segment_length = struct.unpack_from(">H", data, offset)[0]
        if segment_length < 2 or offset + segment_length > len(data):
            break
        if marker in start_of_frame and segment_length >= 7:
            height, width = struct.unpack_from(">HH", data, offset + 3)
            return width, height
        offset += segment_length
    return None
