"""Portable geometry contracts and strict project-owned source locks.

Copyright 2026 Ufuk Efe Kaya
SPDX-License-Identifier: MIT OR Apache-2.0
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from mvt.errors import ContractError
from mvt.util import resource_root, sha256_data, sha256_file


@dataclass(frozen=True)
class Contract:
    path: Path
    data: dict[str, Any]
    hash: str

    @property
    def project_dir(self) -> Path:
        return self.path.parent

    @property
    def project_id(self) -> str:
        return self.data["project"]["id"]

    @property
    def entities(self) -> list[dict[str, Any]]:
        return self.data["entities"]

    def _lookup(self, collection: str, value: str) -> dict[str, Any]:
        try:
            return next(item for item in self.data.get(collection, []) if item["id"] == value)
        except StopIteration as exc:
            raise ContractError(f"Unknown {collection}: {value}") from exc

    def entity(self, entity_id: str) -> dict[str, Any]:
        return self._lookup("entities", entity_id)

    def camera(self, camera_id: str) -> dict[str, Any]:
        return self._lookup("cameras", camera_id)

    def animation(self, sequence_id: str) -> dict[str, Any]:
        return self._lookup("animations", sequence_id)


def contract_path(project: Path) -> Path:
    path = project if project.suffix.lower() in {".yaml", ".yml"} else project / "contract.yaml"
    if not path.is_file():
        raise ContractError(f"Missing contract: {path}")
    return path


def source_path(project_dir: Path, relative: str) -> Path:
    """Resolve only files owned by this contract, including the symlink target."""
    root = project_dir.resolve()
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts:
        raise ContractError("Source paths must be contract-relative without traversal")
    target = (root / value).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ContractError(f"Source missing or outside contract directory: {relative}")
    return target


def _finite(value: Any, path: str = "<root>") -> list[str]:
    if isinstance(value, float) and not math.isfinite(value):
        return [f"{path}: numbers must be finite"]
    if isinstance(value, dict):
        return [error for key, item in value.items() for error in _finite(item, f"{path}/{key}")]
    if isinstance(value, list):
        return [error for index, item in enumerate(value) for error in _finite(item, f"{path}/{index}")]
    return []


def validate_contract(data: dict[str, Any]) -> list[str]:
    schema = json.loads((resource_root() / "schemas" / "geometry-contract.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: "/".join(map(str, e.path)))
    messages = [f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors]
    messages.extend(_finite(data))
    # Schema failures must not cause secondary TypeErrors in semantic validation.
    if messages:
        return messages
    for collection in ("entities", "sources", "stations", "cameras", "animations"):
        ids = [item["id"] for item in data.get(collection, [])]
        if len(ids) != len(set(ids)):
            messages.append(f"{collection}: IDs must be unique")
    entities = {item["id"]: item for item in data["entities"]}
    entity_ids = set(entities)
    actors = entity_ids | {item["actor"] for item in entities.values() if item.get("actor")}
    station_ids = {item["id"] for item in data.get("stations", [])}
    sources = {item["id"]: item for item in data.get("sources", [])}
    cameras = {item["id"]: item for item in data["cameras"]}
    for source in sources.values():
        for key in ("path", "sidecar_path"):
            value = source.get(key)
            if value is not None and (Path(value).is_absolute() or ".." in Path(value).parts):
                messages.append(f"sources/{source['id']}/{key}: must be contract-relative without traversal")
    for entity in entities.values():
        if entity.get("station") and entity["station"] not in station_ids:
            messages.append(f"entities/{entity['id']}: unknown station {entity['station']}")
        if entity.get("source_id") and entity["source_id"] not in sources:
            messages.append(f"entities/{entity['id']}: unknown source {entity['source_id']}")
        if entity.get("source_actor_id") and not entity.get("source_id"):
            messages.append(f"entities/{entity['id']}: source_actor_id requires source_id")
        if entity.get("primitive") == "hex_prism" and entity.get("bore_radius", 0) >= entity["across_flats"] / 2:
            messages.append(f"entities/{entity['id']}: bore must fit inside hex prism")
        actor = entity.get("actor")
        if actor and actor in entity_ids and actor != entity["id"]:
            messages.append(f"entities/{entity['id']}: actor group collides with another entity ID")
    for camera in cameras.values():
        view = [a - b for a, b in zip(camera["position"], camera["focal_point"])]
        up = camera["up"]
        cross = [view[1]*up[2]-view[2]*up[1], view[2]*up[0]-view[0]*up[2], view[0]*up[1]-view[1]*up[0]]
        if sum(value * value for value in cross) <= 1e-18:
            messages.append(f"cameras/{camera['id']}: view and up must be nonzero and nonparallel")
    requirements = data.get("requirements", {})
    for rule in requirements.get("clearances", []):
        if rule["a"] == rule["b"] or {rule["a"], rule["b"]} - entity_ids:
            messages.append(f"requirements/clearances/{rule.get('id', '')}: invalid entity pair")
    _validate_pairs(requirements.get("collision_pairs", []), entity_ids, "requirements/collision_pairs", messages)
    for sequence in data.get("animations", []):
        label = f"animations/{sequence['id']}"
        if sequence["camera"] not in cameras:
            messages.append(f"{label}: unknown camera")
        grouped: dict[str, list[float]] = {}
        for frame in sequence["keyframes"]:
            if frame["entity"] not in actors:
                messages.append(f"{label}: unknown keyframe actor {frame['entity']}")
            if frame["t"] > sequence["duration"]:
                messages.append(f"{label}: keyframe after duration")
            grouped.setdefault(frame["entity"], []).append(frame["t"])
        for actor, times in grouped.items():
            if len(times) != len(set(times)):
                messages.append(f"{label}: duplicate keyframe time for {actor}")
        keyed = set(grouped)
        # Mixing group and individual transforms would otherwise silently override one.
        for actor in keyed:
            if actor in entities and entities[actor].get("actor") in keyed and entities[actor]["actor"] != actor:
                messages.append(f"{label}: group and member both have keyframes: {actor}")
        for group in sequence.get("coupled_groups", []):
            if set(group) - actors or len(set(group)) != len(group):
                messages.append(f"{label}: invalid coupled group")
        if set(sequence.get("required_actors", [])) - keyed:
            messages.append(f"{label}: required actors need keyframes")
        for field in ("collision_pairs", "required_collision_pairs", "allowed_contact_pairs"):
            _validate_pairs(sequence.get(field, []), entity_ids, f"{label}/{field}", messages)
        if "collision_scope" in sequence and set(sequence["collision_scope"]) != entity_ids:
            messages.append(f"{label}: collision_scope must cover every entity")
        previous = -1.0
        for cut in sequence.get("camera_cuts", []):
            camera = cameras.get(cut["camera"])
            if camera is None:
                messages.append(f"{label}: unknown cut camera")
            elif sequence["camera"] in cameras and camera["size"] != cameras[sequence["camera"]]["size"]:
                messages.append(f"{label}: camera cut size differs from base camera")
            if cut["t"] <= previous or cut["t"] > sequence["duration"]:
                messages.append(f"{label}: cuts must increase within duration")
            previous = cut["t"]
    return messages


def _validate_pairs(pairs: list[list[str]], ids: set[str], label: str, messages: list[str]) -> None:
    seen: set[frozenset[str]] = set()
    for pair in pairs:
        key = frozenset(pair)
        if set(pair) - ids or len(key) != 2 or key in seen:
            messages.append(f"{label}: unknown, repeated or duplicate entity pair {pair}")
        seen.add(key)


def load_contract(project: Path | str) -> Contract:
    path = contract_path(Path(project).expanduser().resolve())
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractError(f"Invalid contract YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError("Contract root must be a mapping")
    errors = validate_contract(data)
    if errors:
        raise ContractError("Contract validation failed:\n- " + "\n- ".join(errors))
    contract = Contract(path=path, data=data, hash=sha256_data(data))
    # Even a validation-only operation checks declared source ownership/locks.
    # The builder repeats these checks before native import to detect changes.
    for source in data.get("sources", []):
        for path_key, hash_key in (("path", "sha256"), ("sidecar_path", "sidecar_sha256")):
            if path_key in source:
                native = source_path(contract.project_dir, source[path_key])
                if sha256_file(native) != source[hash_key]:
                    raise ContractError(f"Source hash mismatch: {source['id']} ({path_key})")
    return contract
