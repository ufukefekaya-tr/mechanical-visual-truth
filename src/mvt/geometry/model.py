"""Contract-owned native geometry and deterministic parametric solids.

Copyright 2026 Ufuk Efe Kaya
SPDX-License-Identifier: MIT OR Apache-2.0
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import cadquery as cq

from mvt.contracts import Contract
from mvt.contracts.loader import source_path
from mvt.errors import BuildError, ContractError
from mvt.util import sha256_data, sha256_file


@dataclass
class EntitySolid:
    id: str
    entity_class: str
    station: str | None
    material: str
    color: tuple[float, float, float]
    shape: cq.Shape
    metadata: dict[str, Any]

    @property
    def bbox(self) -> dict[str, list[float]]:
        return optimal_bbox(self.shape)


def optimal_bbox(shape: cq.Shape) -> dict[str, list[float]]:
    """Analytic OCC bounds, independent of whether the shape was tessellated."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    values = list(box.Get())
    return {"min": values[:3], "max": values[3:]}


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BuildError(f"{field} must be a finite number")
    if positive and value <= 0:
        raise BuildError(f"{field} must be positive")
    return float(value)


def _vector(value: Any, field: str, *, positive: bool = False) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise BuildError(f"{field} must contain exactly three numbers")
    return tuple(_number(item, field, positive=positive) for item in value)


def _pose(solid: cq.Shape, spec: dict[str, Any]) -> cq.Shape:
    """Rotate around local origin in X/Y/Z order (degrees), then translate."""
    for axis, angle in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), _vector(spec.get("rotation", [0, 0, 0]), "rotation")):
        if angle:
            solid = solid.rotate((0, 0, 0), axis, angle)
    return solid.translate(_vector(spec["position"], "position"))


def _primitive(spec: dict[str, Any]) -> cq.Shape:
    primitive = spec["primitive"]
    if primitive == "box":
        return cq.Workplane("XY").box(*_vector(spec["size"], "size", positive=True), centered=True).val()
    if primitive not in {"cylinder", "hex_prism"}:
        raise BuildError(f"Unsupported primitive: {primitive}")
    height = _number(spec["height"], "height", positive=True)
    axis = spec.get("axis", "z")
    # Define positive local cylinder axes explicitly; XZ's normal points -Y.
    planes = {"z": cq.Plane.XY(), "x": cq.Plane.YZ(), "y": cq.Plane(origin=(0, 0, 0), xDir=(1, 0, 0), normal=(0, 1, 0))}
    if axis not in planes:
        raise BuildError(f"Unsupported primitive axis: {axis}")
    work = cq.Workplane(planes[axis])
    if primitive == "cylinder":
        return work.circle(_number(spec["radius"], "radius", positive=True)).extrude(height / 2, both=True).val()
    across = _number(spec["across_flats"], "across_flats", positive=True)
    solid = work.polygon(6, 2 * across / math.sqrt(3)).extrude(height / 2, both=True).val()
    if "bore_radius" in spec:
        radius = _number(spec["bore_radius"], "bore_radius", positive=True)
        if radius >= across / 2:
            raise BuildError("hex_prism bore_radius must be smaller than half across_flats")
        solid = solid.cut(work.circle(radius).extrude(height / 2, both=True).val())
    return solid


def _valid_solid(solid: cq.Shape, label: str) -> None:
    if not solid.isValid() or len(solid.Solids()) != 1 or not math.isfinite(solid.Volume()) or solid.Volume() <= 1e-9:
        raise BuildError(f"Invalid, empty or disconnected solid for {label}")


def _verified_source_path(contract: Contract, source: dict[str, Any], path_key: str, hash_key: str) -> Path:
    try:
        path = source_path(contract.project_dir, source[path_key])
    except ContractError as exc:
        raise BuildError(f"Source {source['id']}: {exc}") from exc
    if sha256_file(path) != source[hash_key]:
        raise BuildError(f"Source hash mismatch: {source['id']} ({path_key})")
    return path


def _source_prototypes(contract: Contract, source: dict[str, Any]) -> dict[str, cq.Shape]:
    """Import pinned native solids. Assemblies require a pinned index/name sidecar."""
    path = _verified_source_path(contract, source, "path", "sha256")
    if source["format"] == "BREP":
        shapes = cq.Shape.importBrep(str(path)).Solids()
    else:
        shapes = cq.importers.importStep(str(path)).solids().vals()
    if not shapes:
        raise BuildError(f"Source contains no solids: {source['id']}")
    for index, shape in enumerate(shapes):
        _valid_solid(shape, f"{source['id']}/{index}")
    if "sidecar_path" not in source:
        if len(shapes) != 1:
            raise BuildError(f"Multi-solid source requires a hash-locked sidecar: {source['id']}")
        return {"__single__": shapes[0]}
    sidecar_path = _verified_source_path(contract, source, "sidecar_path", "sidecar_sha256")
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if not isinstance(sidecar, dict) or sidecar.get("source_sha256") != source["sha256"]:
        raise BuildError(f"Sidecar source hash mismatch: {source['id']}")
    actors = sidecar.get("actors")
    if not isinstance(actors, list) or len(actors) != len(shapes):
        raise BuildError(f"Source and sidecar solid counts differ: {source['id']}")
    tolerance = {"bbox_mm": 1e-5, "volume_absolute_mm3": 1e-5, "volume_fraction": 1e-8, **source.get("signature_tolerance", {})}
    for key, value in tolerance.items():
        if _number(value, key) < 0:
            raise BuildError("Signature tolerances cannot be negative")
    output: dict[str, cq.Shape] = {}
    for index, (actor, shape) in enumerate(zip(actors, shapes)):
        if not isinstance(actor, dict) or actor.get("solid_index") != index:
            raise BuildError(f"Sidecar solid index mismatch: {source['id']}/{index}")
        actor_id = actor.get("id")
        if not isinstance(actor_id, str) or not actor_id or actor_id in output:
            raise BuildError(f"Missing or duplicate source actor ID: {source['id']}/{index}")
        signature = actor.get("signature", {})
        try:
            expected_bbox = {key: _vector(signature["bbox"][key], "source bbox") for key in ("min", "max")}
            expected_volume = _number(signature["volume_mm3"], "source volume", positive=True)
        except (KeyError, TypeError) as exc:
            raise BuildError(f"Incomplete source signature: {source['id']}/{actor_id}") from exc
        actual_bbox = optimal_bbox(shape)
        bbox_bad = any(abs(a-b) > tolerance["bbox_mm"] for key in ("min", "max") for a, b in zip(actual_bbox[key], expected_bbox[key]))
        volume_bad = abs(shape.Volume()-expected_volume) > max(tolerance["volume_absolute_mm3"], expected_volume*tolerance["volume_fraction"])
        if bbox_bad or volume_bad:
            raise BuildError(f"Source signature mismatch: {source['id']}/{actor_id}")
        output[actor_id] = shape
    return output


def build_model(contract: Contract) -> list[EntitySolid]:
    solids: list[EntitySolid] = []
    sources = {source["id"]: source for source in contract.data.get("sources", [])}
    cache: dict[str, dict[str, cq.Shape]] = {}
    seen: set[str] = set()
    for entity in contract.entities:
        label = entity["id"]
        if label in seen:
            raise BuildError(f"Duplicate entity ID: {label}")
        seen.add(label)
        if entity.get("visible", True) is False:
            continue
        try:
            metadata = {**entity.get("metadata", {}), "actor": entity.get("actor", label), "validation_tier": contract.data["project"].get("validation_tier", "geometry"), "commercial_status": entity.get("metadata", {}).get("commercial_status", contract.data.get("commercial_status", "not_applicable"))}
            if "source_id" in entity:
                source = sources[entity["source_id"]]
                if source["id"] not in cache:
                    cache[source["id"]] = _source_prototypes(contract, source)
                actor_id = entity.get("source_actor_id", "__single__")
                if actor_id not in cache[source["id"]]:
                    raise BuildError(f"Unknown source actor: {source['id']}/{actor_id}")
                shape = cache[source["id"]][actor_id]
                metadata["source"] = {"id": source["id"], "path": source["path"], "sha256": source["sha256"], "actor_id": actor_id}
            else:
                shape = _primitive(entity)
            _valid_solid(shape, label)
            for index, cutter in enumerate(entity.get("cuts", [])):
                tool = _pose(_primitive(cutter), cutter)
                _valid_solid(tool, f"{label}/cuts/{index}")
                before = shape.Volume()
                shape = shape.cut(tool)
                _valid_solid(shape, label)
                if before-shape.Volume() <= 1e-9:
                    raise BuildError(f"Non-intersecting or ineffective cut: {label}/cuts/{index}")
            shape = _pose(shape, entity)
            _valid_solid(shape, label)
        except BuildError:
            raise
        except Exception as exc:
            raise BuildError(f"Geometry construction failed for {label}: {exc}") from exc
        solids.append(EntitySolid(label, entity["class"], entity.get("station"), entity["material"], tuple(entity.get("color", [0.65, 0.67, 0.68])), shape, metadata))
    if not solids:
        raise BuildError("Model has no visible solids")
    return solids


def model_semantic_hash(contract: Contract, solids: list[EntitySolid]) -> str:
    return sha256_data({"contract": contract.hash, "entities": [
        {"id": item.id, "class": item.entity_class, "bbox": item.bbox,
         "volume_mm3": item.shape.Volume(), "area_mm2": item.shape.Area(),
         "face_count": len(item.shape.Faces()), "source": item.metadata.get("source")}
        for item in solids]})


def export_step(solids: list[EntitySolid], path: Path) -> str:
    if not solids:
        raise BuildError("Cannot export an empty assembly")
    path.parent.mkdir(parents=True, exist_ok=True)
    assembly = cq.Assembly(name="MVT_MODEL")
    for item in solids:
        assembly.add(item.shape, name=item.id, color=cq.Color(*item.color))
    try:
        assembly.save(str(path), exportType="STEP")
    except Exception as exc:
        raise BuildError(f"STEP export failed: {exc}") from exc
    return sha256_file(path)
