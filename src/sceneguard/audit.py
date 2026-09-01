from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .glb import GlbDocument, GlbFormatError, collection, decode_accessor, image_dimensions, parse_glb_bytes
from .models import AuditReport, Finding, Severity
from .profile import QualityProfile


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


class AssetAuditor:
    def __init__(self, profile: QualityProfile) -> None:
        self.profile = profile
        self._findings: list[Finding] = []
        self._counter = 0
        self._completed: list[str] = []
        self._incomplete: list[str] = []

    def audit(self, path: str | Path, job_id: str = "standalone") -> AuditReport:
        source = Path(path)
        data = source.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        measurements: dict[str, Any] = {"file_bytes": len(data)}

        try:
            document = parse_glb_bytes(data)
        except GlbFormatError as exc:
            self._add(
                rule_id="package.valid_glb",
                severity=Severity.ERROR,
                message=str(exc),
                observed=exc.code,
                expected="valid GLB 2.0",
            )
            self._incomplete.extend(
                ["package.single_file", "package.bounds", "package.references", "profile.budgets"]
            )
            return self._report(source, sha256, job_id, measurements)

        self._completed.append("package.valid_glb")
        measurements.update(self._base_measurements(document))
        self._check_single_file(document)
        self._check_bounds(document)
        self._check_references(document)
        self._check_mesh_geometry(document, measurements)
        self._check_budgets(document, measurements)
        return self._report(source, sha256, job_id, measurements)

    def _report(
        self,
        source: Path,
        sha256: str,
        job_id: str,
        measurements: dict[str, Any],
    ) -> AuditReport:
        return AuditReport(
            schema_version="0.1",
            job_id=job_id,
            asset_path=str(source),
            asset_sha256=sha256,
            profile_id=self.profile.profile_id,
            profile_version=self.profile.version,
            measurements=measurements,
            findings=self._findings,
            checks_completed=self._completed,
            checks_incomplete=self._incomplete,
            created_at=datetime.now(UTC).isoformat(),
        )

    def _base_measurements(self, document: GlbDocument) -> dict[str, Any]:
        payload = document.json
        return {
            "file_bytes": document.file_size,
            "bin_bytes": len(document.binary),
            "scene_count": len(collection(payload, "scenes")),
            "node_count": len(collection(payload, "nodes")),
            "mesh_count": len(collection(payload, "meshes")),
            "primitive_count": sum(
                len(mesh.get("primitives", []))
                for mesh in collection(payload, "meshes")
                if isinstance(mesh, dict) and isinstance(mesh.get("primitives", []), list)
            ),
            "material_count": len(collection(payload, "materials")),
            "texture_count": len(collection(payload, "textures")),
            "image_count": len(collection(payload, "images")),
        }

    def _check_single_file(self, document: GlbDocument) -> None:
        rules = self.profile.rules
        allow_external = bool(rules.get("allow_external_uris", False))
        require_embedded = bool(rules.get("require_embedded_buffers", True))
        payload = document.json

        for index, buffer in enumerate(collection(payload, "buffers")):
            if not isinstance(buffer, dict):
                self._invalid_object("buffers", index)
                continue
            uri = buffer.get("uri")
            if uri and require_embedded:
                self._add(
                    "package.single_file",
                    Severity.ERROR,
                    "GLB buffer uses a URI instead of the embedded BIN chunk",
                    {"buffer": index},
                    uri,
                    "no buffer URI",
                )

        for index, image in enumerate(collection(payload, "images")):
            if not isinstance(image, dict):
                self._invalid_object("images", index)
                continue
            uri = image.get("uri")
            is_external = isinstance(uri, str) and not uri.startswith("data:")
            if is_external and not allow_external:
                self._add(
                    "package.single_file",
                    Severity.ERROR,
                    "image references an external URI",
                    {"image": index},
                    uri,
                    "embedded bufferView or data URI",
                )
        self._completed.append("package.single_file")

    def _check_bounds(self, document: GlbDocument) -> None:
        payload = document.json
        buffers = collection(payload, "buffers")
        views = collection(payload, "bufferViews")
        accessors = collection(payload, "accessors")

        for index, buffer in enumerate(buffers):
            if not isinstance(buffer, dict):
                continue
            declared = buffer.get("byteLength")
            if not isinstance(declared, int) or declared < 0:
                self._add(
                    "package.buffer_bounds",
                    Severity.ERROR,
                    "buffer.byteLength must be a non-negative integer",
                    {"buffer": index},
                    declared,
                    ">= 0",
                )
                continue
            if index == 0 and not buffer.get("uri"):
                actual = len(document.binary)
                if declared > actual or actual > declared + 3:
                    self._add(
                        "package.buffer_bounds",
                        Severity.ERROR,
                        "embedded BIN size does not match buffer.byteLength (up to 3 padding bytes allowed)",
                        {"buffer": index},
                        {"declared": declared, "actual": actual},
                        "declared <= actual <= declared + 3",
                    )

        for index, view in enumerate(views):
            if not isinstance(view, dict):
                self._invalid_object("bufferViews", index)
                continue
            buffer_index = view.get("buffer")
            offset = view.get("byteOffset", 0)
            length = view.get("byteLength")
            if not self._valid_index(buffer_index, buffers):
                self._ref_error("bufferViews", index, "buffer", buffer_index, len(buffers))
                continue
            if not isinstance(offset, int) or offset < 0 or not isinstance(length, int) or length < 0:
                self._add(
                    "package.buffer_bounds",
                    Severity.ERROR,
                    "bufferView offset and length must be non-negative integers",
                    {"bufferView": index},
                    {"byteOffset": offset, "byteLength": length},
                    ">= 0",
                )
                continue
            buffer = buffers[buffer_index]
            declared = buffer.get("byteLength") if isinstance(buffer, dict) else None
            if isinstance(declared, int) and offset + length > declared:
                self._add(
                    "package.buffer_bounds",
                    Severity.ERROR,
                    "bufferView extends beyond its buffer",
                    {"bufferView": index},
                    offset + length,
                    f"<= {declared}",
                )

        for index, accessor in enumerate(accessors):
            if not isinstance(accessor, dict):
                self._invalid_object("accessors", index)
                continue
            if "bufferView" not in accessor:
                continue
            view_index = accessor.get("bufferView")
            if not self._valid_index(view_index, views):
                self._ref_error("accessors", index, "bufferView", view_index, len(views))
                continue
            view = views[view_index]
            if not isinstance(view, dict):
                continue
            component_bytes = COMPONENT_BYTES.get(accessor.get("componentType"))
            component_count = TYPE_COMPONENTS.get(accessor.get("type"))
            count = accessor.get("count")
            byte_offset = accessor.get("byteOffset", 0)
            if component_bytes is None or component_count is None or not isinstance(count, int) or count < 0:
                self._add(
                    "package.accessor_layout",
                    Severity.ERROR,
                    "accessor componentType, type or count is invalid",
                    {"accessor": index},
                    {
                        "componentType": accessor.get("componentType"),
                        "type": accessor.get("type"),
                        "count": count,
                    },
                    "valid glTF accessor layout",
                )
                continue
            if not isinstance(byte_offset, int) or byte_offset < 0:
                self._add(
                    "package.accessor_layout",
                    Severity.ERROR,
                    "accessor.byteOffset must be a non-negative integer",
                    {"accessor": index},
                    byte_offset,
                    ">= 0",
                )
                continue
            element_bytes = component_bytes * component_count
            stride = view.get("byteStride", element_bytes)
            if not isinstance(stride, int) or stride < element_bytes:
                self._add(
                    "package.accessor_layout",
                    Severity.ERROR,
                    "bufferView.byteStride is smaller than one accessor element",
                    {"accessor": index, "bufferView": view_index},
                    stride,
                    f">= {element_bytes}",
                )
                continue
            required = byte_offset if count == 0 else byte_offset + (count - 1) * stride + element_bytes
            view_length = view.get("byteLength")
            if isinstance(view_length, int) and required > view_length:
                self._add(
                    "package.accessor_bounds",
                    Severity.ERROR,
                    "accessor data extends beyond its bufferView",
                    {"accessor": index, "bufferView": view_index},
                    required,
                    f"<= {view_length}",
                )
        self._completed.append("package.bounds")

    def _check_references(self, document: GlbDocument) -> None:
        payload = document.json
        scenes = collection(payload, "scenes")
        nodes = collection(payload, "nodes")
        meshes = collection(payload, "meshes")
        accessors = collection(payload, "accessors")
        materials = collection(payload, "materials")
        textures = collection(payload, "textures")
        images = collection(payload, "images")
        samplers = collection(payload, "samplers")
        views = collection(payload, "bufferViews")

        if "scene" in payload and not self._valid_index(payload.get("scene"), scenes):
            self._ref_error("root", 0, "scene", payload.get("scene"), len(scenes))
        for scene_index, scene in enumerate(scenes):
            if isinstance(scene, dict):
                self._check_index_list("scenes", scene_index, "nodes", scene.get("nodes", []), nodes)
        for node_index, node in enumerate(nodes):
            if not isinstance(node, dict):
                self._invalid_object("nodes", node_index)
                continue
            if "mesh" in node and not self._valid_index(node.get("mesh"), meshes):
                self._ref_error("nodes", node_index, "mesh", node.get("mesh"), len(meshes))
            self._check_index_list("nodes", node_index, "children", node.get("children", []), nodes)

        for mesh_index, mesh in enumerate(meshes):
            if not isinstance(mesh, dict):
                self._invalid_object("meshes", mesh_index)
                continue
            primitives = mesh.get("primitives", [])
            if not isinstance(primitives, list) or not primitives:
                self._add(
                    "package.reference_integrity",
                    Severity.ERROR,
                    "mesh must contain at least one primitive",
                    {"mesh": mesh_index},
                    primitives,
                    "non-empty primitives array",
                )
                continue
            for primitive_index, primitive in enumerate(primitives):
                if not isinstance(primitive, dict):
                    self._invalid_object(f"meshes[{mesh_index}].primitives", primitive_index)
                    continue
                attributes = primitive.get("attributes")
                if not isinstance(attributes, dict) or "POSITION" not in attributes:
                    self._add(
                        "package.reference_integrity",
                        Severity.ERROR,
                        "mesh primitive requires a POSITION accessor",
                        {"mesh": mesh_index, "primitive": primitive_index},
                        attributes,
                        "attributes.POSITION",
                    )
                elif not self._valid_index(attributes.get("POSITION"), accessors):
                    self._ref_error(
                        f"meshes[{mesh_index}].primitives",
                        primitive_index,
                        "attributes.POSITION",
                        attributes.get("POSITION"),
                        len(accessors),
                    )
                if isinstance(attributes, dict):
                    for semantic, accessor_index in attributes.items():
                        if not self._valid_index(accessor_index, accessors):
                            self._ref_error(
                                f"meshes[{mesh_index}].primitives",
                                primitive_index,
                                f"attributes.{semantic}",
                                accessor_index,
                                len(accessors),
                            )
                if "indices" in primitive and not self._valid_index(primitive.get("indices"), accessors):
                    self._ref_error(
                        f"meshes[{mesh_index}].primitives",
                        primitive_index,
                        "indices",
                        primitive.get("indices"),
                        len(accessors),
                    )
                if "material" in primitive and not self._valid_index(primitive.get("material"), materials):
                    self._ref_error(
                        f"meshes[{mesh_index}].primitives",
                        primitive_index,
                        "material",
                        primitive.get("material"),
                        len(materials),
                    )

        for texture_index, texture in enumerate(textures):
            if not isinstance(texture, dict):
                self._invalid_object("textures", texture_index)
                continue
            if "source" in texture and not self._valid_index(texture.get("source"), images):
                self._ref_error("textures", texture_index, "source", texture.get("source"), len(images))
            if "sampler" in texture and not self._valid_index(texture.get("sampler"), samplers):
                self._ref_error("textures", texture_index, "sampler", texture.get("sampler"), len(samplers))
        for image_index, image in enumerate(images):
            if isinstance(image, dict) and "bufferView" in image and not self._valid_index(image.get("bufferView"), views):
                self._ref_error("images", image_index, "bufferView", image.get("bufferView"), len(views))

        for material_index, material in enumerate(materials):
            if isinstance(material, dict):
                for field_path, texture_index in self._material_texture_refs(material):
                    if not self._valid_index(texture_index, textures):
                        self._ref_error("materials", material_index, field_path, texture_index, len(textures))
        self._completed.append("package.references")

    def _check_budgets(self, document: GlbDocument, measurements: dict[str, Any]) -> None:
        rules = self.profile.rules
        max_file = rules.get("max_file_bytes")
        if isinstance(max_file, int) and document.file_size > max_file:
            self._add(
                "profile.max_file_bytes",
                Severity.ERROR,
                "GLB exceeds the profile file-size budget",
                observed=document.file_size,
                expected=f"<= {max_file}",
            )

        triangle_count = self._triangle_count(document.json)
        measurements["triangle_count"] = triangle_count
        max_triangles = rules.get("max_triangles")
        if isinstance(max_triangles, int) and triangle_count > max_triangles:
            self._add(
                "profile.max_triangles",
                Severity.ERROR,
                "mesh triangle count exceeds the profile budget",
                observed=triangle_count,
                expected=f"<= {max_triangles}",
            )

        dimensions = self._embedded_image_dimensions(document)
        measurements["embedded_image_dimensions"] = dimensions
        largest = max((max(item["width"], item["height"]) for item in dimensions), default=0)
        measurements["max_texture_dimension"] = largest
        max_dimension = rules.get("max_texture_dimension")
        if isinstance(max_dimension, int):
            for item in dimensions:
                observed = max(item["width"], item["height"])
                if observed > max_dimension:
                    self._add(
                        "profile.max_texture_dimension",
                        Severity.ERROR,
                        "embedded texture exceeds the profile dimension budget",
                        {"image": item["image"]},
                        observed,
                        f"<= {max_dimension}",
                        {"width": item["width"], "height": item["height"]},
                    )
        self._completed.append("profile.budgets")

    def _check_mesh_geometry(self, document: GlbDocument, measurements: dict[str, Any]) -> None:
        payload = document.json
        accessors = collection(payload, "accessors")
        degenerate_locations: list[dict[str, int]] = []
        non_finite_locations: list[dict[str, int]] = []
        geometry_complete = True

        for mesh_index, mesh in enumerate(collection(payload, "meshes")):
            if not isinstance(mesh, dict):
                geometry_complete = False
                continue
            primitives = mesh.get("primitives", [])
            if not isinstance(primitives, list):
                geometry_complete = False
                continue
            for primitive_index, primitive in enumerate(primitives):
                if not isinstance(primitive, dict):
                    geometry_complete = False
                    continue
                attributes = primitive.get("attributes")
                position_index = attributes.get("POSITION") if isinstance(attributes, dict) else None
                if not self._valid_index(position_index, accessors):
                    geometry_complete = False
                    continue
                position_accessor = accessors[position_index]
                if not isinstance(position_accessor, dict) or position_accessor.get("type") != "VEC3":
                    self._add(
                        "mesh.position_layout",
                        Severity.ERROR,
                        "POSITION accessor must use VEC3",
                        {"mesh": mesh_index, "primitive": primitive_index},
                        position_accessor.get("type") if isinstance(position_accessor, dict) else None,
                        "VEC3",
                    )
                    geometry_complete = False
                    continue
                try:
                    positions = decode_accessor(document, position_index)
                    index_accessor = primitive.get("indices")
                    if index_accessor is None:
                        indices = list(range(len(positions)))
                    else:
                        if not self._valid_index(index_accessor, accessors):
                            geometry_complete = False
                            continue
                        index_meta = accessors[index_accessor]
                        if (
                            not isinstance(index_meta, dict)
                            or index_meta.get("type") != "SCALAR"
                            or index_meta.get("componentType") not in {5121, 5123, 5125}
                        ):
                            self._add(
                                "mesh.index_layout",
                                Severity.ERROR,
                                "indices accessor must be unsigned SCALAR",
                                {"mesh": mesh_index, "primitive": primitive_index},
                                {
                                    "type": index_meta.get("type") if isinstance(index_meta, dict) else None,
                                    "componentType": index_meta.get("componentType") if isinstance(index_meta, dict) else None,
                                },
                                "SCALAR with UNSIGNED_BYTE/SHORT/INT",
                            )
                            geometry_complete = False
                            continue
                        indices = decode_accessor(document, index_accessor)
                except GlbFormatError as exc:
                    self._add(
                        "mesh.geometry_decode",
                        Severity.ERROR,
                        str(exc),
                        {"mesh": mesh_index, "primitive": primitive_index},
                        exc.code,
                        "decodable embedded geometry",
                    )
                    geometry_complete = False
                    continue

                for vertex_index, position in enumerate(positions):
                    if not all(math.isfinite(float(value)) for value in position):
                        non_finite_locations.append(
                            {"mesh": mesh_index, "primitive": primitive_index, "vertex": vertex_index}
                        )

                for triangle_index, triangle in enumerate(self._triangles(indices, primitive.get("mode", 4))):
                    if any(not isinstance(value, int) or value < 0 or value >= len(positions) for value in triangle):
                        self._add(
                            "mesh.index_bounds",
                            Severity.ERROR,
                            "triangle index references a missing POSITION element",
                            {"mesh": mesh_index, "primitive": primitive_index, "triangle": triangle_index},
                            list(triangle),
                            f"each index in [0, {max(-1, len(positions) - 1)}]",
                        )
                        continue
                    if self._is_degenerate(positions[triangle[0]], positions[triangle[1]], positions[triangle[2]]):
                        degenerate_locations.append(
                            {"mesh": mesh_index, "primitive": primitive_index, "triangle": triangle_index}
                        )

        measurements["degenerate_triangle_count"] = len(degenerate_locations)
        measurements["non_finite_position_count"] = len(non_finite_locations)
        if degenerate_locations:
            self._add(
                "mesh.degenerate_triangles",
                Severity.ERROR,
                "mesh contains zero-area or repeated-index triangles",
                observed=len(degenerate_locations),
                expected=0,
                evidence={"locations": degenerate_locations[:20]},
                repairability="AUTO_CANDIDATE",
            )
        if non_finite_locations:
            self._add(
                "mesh.non_finite_positions",
                Severity.ERROR,
                "POSITION accessor contains NaN or infinity",
                observed=len(non_finite_locations),
                expected=0,
                evidence={"locations": non_finite_locations[:20]},
            )
        if geometry_complete:
            self._completed.append("mesh.geometry")
        else:
            self._incomplete.append("mesh.geometry")

    @staticmethod
    def _triangles(indices: list[Any], mode: Any) -> Iterable[tuple[int, int, int]]:
        if mode == 4:
            for offset in range(0, len(indices) - 2, 3):
                yield indices[offset], indices[offset + 1], indices[offset + 2]
        elif mode == 5:
            for offset in range(len(indices) - 2):
                yield indices[offset], indices[offset + 1], indices[offset + 2]
        elif mode == 6 and indices:
            for offset in range(1, len(indices) - 1):
                yield indices[0], indices[offset], indices[offset + 1]

    @staticmethod
    def _is_degenerate(a: Any, b: Any, c: Any) -> bool:
        if a == b or b == c or a == c:
            return True
        ab = (float(b[0]) - float(a[0]), float(b[1]) - float(a[1]), float(b[2]) - float(a[2]))
        ac = (float(c[0]) - float(a[0]), float(c[1]) - float(a[1]), float(c[2]) - float(a[2]))
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        area_squared_times_four = sum(value * value for value in cross)
        return area_squared_times_four <= 1e-24

    def _triangle_count(self, payload: dict[str, Any]) -> int:
        accessors = collection(payload, "accessors")
        total = 0
        for mesh in collection(payload, "meshes"):
            if not isinstance(mesh, dict):
                continue
            for primitive in mesh.get("primitives", []):
                if not isinstance(primitive, dict):
                    continue
                mode = primitive.get("mode", 4)
                count = 0
                indices = primitive.get("indices")
                if self._valid_index(indices, accessors):
                    accessor = accessors[indices]
                    count = accessor.get("count", 0) if isinstance(accessor, dict) else 0
                else:
                    position = (primitive.get("attributes") or {}).get("POSITION")
                    if self._valid_index(position, accessors):
                        accessor = accessors[position]
                        count = accessor.get("count", 0) if isinstance(accessor, dict) else 0
                if not isinstance(count, int) or count < 0:
                    continue
                if mode == 4:
                    total += count // 3
                elif mode in {5, 6}:
                    total += max(0, count - 2)
        return total

    def _embedded_image_dimensions(self, document: GlbDocument) -> list[dict[str, int]]:
        payload = document.json
        views = collection(payload, "bufferViews")
        dimensions: list[dict[str, int]] = []
        for image_index, image in enumerate(collection(payload, "images")):
            if not isinstance(image, dict):
                continue
            view_index = image.get("bufferView")
            if not self._valid_index(view_index, views):
                continue
            view = views[view_index]
            if not isinstance(view, dict) or view.get("buffer", 0) != 0:
                continue
            offset = view.get("byteOffset", 0)
            length = view.get("byteLength", 0)
            if not isinstance(offset, int) or not isinstance(length, int):
                continue
            result = image_dimensions(document.binary[offset : offset + length])
            if result is None:
                self._add(
                    "texture.dimensions_readable",
                    Severity.WARNING,
                    "embedded image dimensions could not be read as PNG or JPEG",
                    {"image": image_index},
                    image.get("mimeType"),
                    "image/png or image/jpeg",
                )
                continue
            width, height = result
            dimensions.append({"image": image_index, "width": width, "height": height})
        return dimensions

    def _material_texture_refs(self, material: dict[str, Any]) -> Iterable[tuple[str, Any]]:
        pbr = material.get("pbrMetallicRoughness")
        if isinstance(pbr, dict):
            for name in ("baseColorTexture", "metallicRoughnessTexture"):
                info = pbr.get(name)
                if isinstance(info, dict) and "index" in info:
                    yield f"pbrMetallicRoughness.{name}.index", info.get("index")
        for name in ("normalTexture", "occlusionTexture", "emissiveTexture"):
            info = material.get(name)
            if isinstance(info, dict) and "index" in info:
                yield f"{name}.index", info.get("index")

    def _check_index_list(
        self,
        collection_name: str,
        index: int,
        field: str,
        values: Any,
        targets: list[Any],
    ) -> None:
        if not isinstance(values, list):
            self._add(
                "package.reference_integrity",
                Severity.ERROR,
                f"{collection_name}.{field} must be an array",
                {collection_name.rstrip("s"): index},
                values,
                "array of valid indices",
            )
            return
        for value in values:
            if not self._valid_index(value, targets):
                self._ref_error(collection_name, index, field, value, len(targets))

    @staticmethod
    def _valid_index(value: Any, targets: list[Any]) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(targets)

    def _ref_error(self, owner: str, index: int, field: str, value: Any, target_count: int) -> None:
        self._add(
            "package.reference_integrity",
            Severity.ERROR,
            f"{owner}[{index}].{field} references a missing object",
            {"owner": owner, "index": index, "field": field},
            value,
            f"integer in [0, {max(-1, target_count - 1)}]",
        )

    def _invalid_object(self, collection_name: str, index: int) -> None:
        self._add(
            "package.object_type",
            Severity.ERROR,
            f"{collection_name}[{index}] must be an object",
            {"collection": collection_name, "index": index},
            "non-object",
            "object",
        )

    def _add(
        self,
        rule_id: str,
        severity: Severity,
        message: str,
        location: dict[str, Any] | None = None,
        observed: Any = None,
        expected: Any = None,
        evidence: dict[str, Any] | None = None,
        repairability: str = "MANUAL_ONLY",
    ) -> None:
        self._counter += 1
        self._findings.append(
            Finding(
                finding_id=f"f-{self._counter:04d}",
                rule_id=rule_id,
                severity=severity,
                message=message,
                location=location or {},
                observed=observed,
                expected=expected,
                evidence=evidence or {},
                repairability=repairability,
            )
        )


def audit_asset(path: str | Path, profile: QualityProfile, job_id: str = "standalone") -> AuditReport:
    return AssetAuditor(profile).audit(path, job_id=job_id)
