"""Sampled deterministic CAD motion with separate physical-validation limits.

Copyright 2026 Ufuk Efe Kaya
SPDX-License-Identifier: MIT OR Apache-2.0
"""
from __future__ import annotations

from dataclasses import replace
import math
import subprocess
from pathlib import Path
from typing import Any

import imageio_ffmpeg
from PIL import Image, ImageDraw

from mvt.auditing.core import _distance, geometry_pair, result_status
from mvt.contracts import Contract
from mvt.geometry import EntitySolid
from mvt.rendering.vtk_renderer import MeshCache, render_png
from mvt.util import atomic_json, owned_path, sha256_file


_IDENTITY = {"translation": [0, 0, 0], "rotation": [0, 0, 0], "pivot": [0, 0, 0]}


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def poses_at(sequence: dict[str, Any], t: float) -> dict[str, dict[str, list[float]]]:
    """Smooth world offsets: XYZ degrees around a world pivot, then translation."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for frame in sequence["keyframes"]:
        grouped.setdefault(frame["entity"], []).append(frame)
    result = {}
    for actor, frames in grouped.items():
        frames = sorted(frames, key=lambda frame: frame["t"])
        if t <= frames[0]["t"]:
            left = right = frames[0]
            ratio = 0.0
        elif t >= frames[-1]["t"]:
            left = right = frames[-1]
            ratio = 0.0
        else:
            left, right = next((a, b) for a, b in zip(frames, frames[1:]) if a["t"] <= t <= b["t"])
            if right["t"] <= left["t"]:
                raise ValueError("Duplicate motion keyframe time")
            ratio = smoothstep((t-left["t"])/(right["t"]-left["t"]))
        result[actor] = {key: [a+(b-a)*ratio for a, b in zip(left.get(key, default), right.get(key, default))] for key, default in _IDENTITY.items()}
    return result


def transforms_at(sequence: dict[str, Any], t: float) -> dict[str, list[float]]:
    """Legacy translation-only accessor; rendering/auditing use full poses_at."""
    return {key: value["translation"] for key, value in poses_at(sequence, t).items()}


def _posed(item: EntitySolid, pose: dict[str, list[float]]) -> EntitySolid:
    shape = item.shape
    pivot = pose["pivot"]
    for axis, angle in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), pose["rotation"]):
        if angle:
            shape = shape.rotate(pivot, [pivot[i]+axis[i] for i in range(3)], angle)
    if any(pose["translation"]):
        shape = shape.translate(pose["translation"])
    return replace(item, shape=shape)


def posed_solids(sequence: dict[str, Any], solids: list[EntitySolid], t: float) -> list[EntitySolid]:
    poses = poses_at(sequence, t)
    return [_posed(item, poses.get(item.id, poses.get(item.metadata.get("actor", item.id), _IDENTITY))) for item in solids]


def camera_id_at(sequence: dict[str, Any], t: float) -> str:
    selected = sequence["camera"]
    for cut in sequence.get("camera_cuts", []):
        if cut["t"] <= t:
            selected = cut["camera"]
    return selected


def _sample_times(sequence: dict[str, Any]) -> list[float]:
    duration, fps = sequence["duration"], sequence["fps"]
    count = max(2, math.ceil(duration*fps/sequence.get("sample_every", 1))+1)
    times = [duration*i/(count-1) for i in range(count)]
    delta = min(0.5/fps, duration/1000)
    for frame in sequence["keyframes"]:
        times.extend(max(0.0, min(duration, frame["t"]+offset)) for offset in (-delta, 0.0, delta))
    return sorted(set(times))


def _candidates(by_id: dict[str, EntitySolid]):
    """Sweep world AABBs; only near pairs need an OCC intersection."""
    entries = sorted((item.bbox["min"][0], item.id, item.bbox) for item in by_id.values())
    active: list[tuple[float, str, dict[str, list[float]]]] = []
    for xmin, entity_id, box in entries:
        active = [entry for entry in active if entry[0] >= xmin-1e-7]
        for _, other_id, other_box in active:
            if _distance(box, other_box) <= 1e-7:
                yield tuple(sorted((entity_id, other_id)))
        active.append((box["max"][0], entity_id, box))


def audit_motion(sequence: dict[str, Any], solids: list[EntitySolid]) -> dict[str, Any]:
    by_id = {item.id: item for item in solids}
    actors = set(by_id) | {item.metadata.get("actor", item.id) for item in solids}
    keyed = {frame["entity"] for frame in sequence["keyframes"]}
    findings: list[dict[str, Any]] = []
    times = _sample_times(sequence)
    if len(by_id) != len(solids):
        findings.append({"gate": "entity-identity", "status": "RED", "reason": "Duplicate solid IDs"})
    for actor in sorted(set(sequence.get("required_actors", [])) | keyed):
        if actor not in actors or actor not in keyed:
            findings.append({"gate": "actor", "actor": actor, "status": "RED", "reason": "Missing entity/group or keyframe"})
    for group in sequence.get("coupled_groups", []):
        if set(group)-actors:
            findings.append({"gate": "coupled-motion", "entities": group, "status": "RED", "reason": "Unknown entity/group"})
            continue
        for t in times:
            poses = poses_at(sequence, t)
            base = poses.get(group[0], _IDENTITY)
            if any(abs(a-b) > 0.01 for actor in group[1:] for key in _IDENTITY for a,b in zip(base[key], poses.get(actor, _IDENTITY)[key])):
                findings.append({"gate": "coupled-motion", "entities": group, "time": round(t, 9), "status": "RED"})
                break
    truth = sequence["truth_mode"]
    tier = sequence.get("validation_tier", next((item.metadata["validation_tier"] for item in solids if "validation_tier" in item.metadata), "geometry"))
    limits = ["Sampled nominal CAD checks only; motion between samples, forces, tolerances and real safety remain unverified."]
    checked = 0
    peak_intersection = 0.0
    scope = sequence.get("collision_scope")
    full_scope = scope is not None and set(scope) == set(by_id) and len(scope) == len(by_id)
    if scope is not None and not full_scope:
        findings.append({"gate": "collision-coverage", "status": "RED", "reason": "Collision scope does not cover all built entities"})
    declared = sequence.get("collision_pairs", [])
    contacts = sequence.get("allowed_contact_pairs", [])
    covered = {frozenset(pair) for pair in declared}
    for pair in sequence.get("required_collision_pairs", []):
        if not full_scope and frozenset(pair) not in covered:
            findings.append({"gate": "collision-coverage", "entities": pair, "status": "RED", "reason": "Required pair is not covered"})
    valid_pairs = []
    for pair in declared+contacts:
        if len(pair) != 2 or pair[0] == pair[1] or set(pair)-set(by_id):
            findings.append({"gate": "collision", "entities": pair, "status": "RED", "reason": "Invalid entity pair"})
        else:
            valid_pairs.append(tuple(sorted(pair)))
    if truth != "deterministic_cad":
        findings.append({"gate": "truth-mode", "status": "YELLOW", "reason": "Presentation-only motion cannot prove CAD clearance/collision"})
        limits.append("Presentation-only raster motion is not CAD, physics, collision or manufacturing evidence.")
    elif not full_scope and not valid_pairs:
        findings.append({"gate": "collision-coverage", "status": "YELLOW", "reason": "No collision pairs or complete collision scope declared"})
    complete = True
    max_work = 250_000
    if truth == "deterministic_cad":
        tolerance = sequence.get("collision_volume_tolerance", 1e-7)
        for t in times:
            posed = {item.id: item for item in posed_solids(sequence, solids, t)}
            pairs = set(valid_pairs)
            if full_scope:
                pairs.update(_candidates(posed))
            for left, right in sorted(pairs):
                if checked >= max_work:
                    complete = False
                    findings.append({"gate": "collision-coverage", "status": "RED", "reason": "B-rep work limit exhausted; audit incomplete"})
                    break
                checked += 1
                try:
                    pair = geometry_pair(posed[left], posed[right])
                except Exception as exc:
                    findings.append({"gate": "collision", "entities": [left, right], "time": round(t,9), "status": "RED", "reason": "B-rep evaluation failed", "detail": type(exc).__name__})
                    continue
                volume = pair["intersection_mm3"]
                peak_intersection = max(peak_intersection, volume)
                if volume > tolerance:
                    findings.append({"gate": "collision", "entities": [left, right], "time": round(t,9), **pair, "status": "RED"})
                elif volume > 0:
                    findings.append({"gate": "collision", "entities": [left, right], "time": round(t,9), **pair, "status": "YELLOW", "reason": "Positive intersection below declared numerical threshold"})
            if not complete:
                break
    if not full_scope:
        limits.append("Collision coverage is limited to declared entity pairs.")
    return {
        "status": result_status(findings), "samples": len(times), "sample_times": [round(t,9) for t in times],
        "findings": findings, "truth_mode": truth, "validation_tier": tier,
        "geometry_status": result_status(findings) if truth == "deterministic_cad" else "NOT_APPLICABLE",
        "physical_status": "YELLOW", "safety_status": "YELLOW", "limitations": limits,
        "collision_audit": {"method": "brep", "coverage": "all_entities" if full_scope else "declared_pairs", "complete": complete, "pair_evaluations": checked, "peak_intersection_mm3": peak_intersection},
    }


def _preview_durations(indices: list[int], fps: int, frame_count: int) -> list[int]:
    """GIF ticks are 10 ms; round cumulative times to avoid frame-rate drift."""
    stops = indices[1:] + [frame_count]
    return [max(10, (round(end*100/fps)-round(start*100/fps))*10) for start, end in zip(indices, stops)]


def build_cad_animation(
    contract: Contract, solids: list[EntitySolid], model_hash: str, sequence_id: str, output: Path,
) -> dict[str, Any]:
    sequence = contract.animation(sequence_id)
    if sequence["truth_mode"] != "deterministic_cad":
        raise ValueError("Sequence is not deterministic_cad")
    camera = contract.camera(sequence["camera"])
    if any(size % 2 for size in camera["size"]):
        raise ValueError("MP4 output requires even camera dimensions")
    mesh_cache = MeshCache()
    output.mkdir(parents=True, exist_ok=True)
    frames_dir = owned_path(output, "frames")
    frames_dir.mkdir(exist_ok=True)
    fps = sequence["fps"]
    frame_count = int(sequence["duration"] * fps) + 1
    width, height = camera["size"]
    mp4 = owned_path(output, f"{sequence_id}.mp4")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-vcodec", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
           "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    previews: list[Image.Image] = []
    selected: list[Image.Image] = []
    preview_indices: list[int] = []
    preview_stride = max(1, fps // 5)
    try:
        for index in range(frame_count):
            t = sequence["duration"] * index / max(1, frame_count - 1)
            frame_path = owned_path(output, Path("frames") / f"frame-{index:04d}.png")
            frame_camera = contract.camera(camera_id_at(sequence, t))
            render_png(solids, frame_camera, frame_path, poses_at(sequence, t), "DETERMINISTIC CAD MOTION PROOF", mesh_cache)
            with Image.open(frame_path) as opened:
                frame = opened.convert("RGB")
            draw = ImageDraw.Draw(frame, "RGBA")
            draw.rounded_rectangle((18, 18, 360, 60), radius=8, fill=(10, 14, 18, 180))
            draw.text((32, 29), f"{sequence_id}  t={t:05.2f}s", fill=(255, 255, 255, 255))
            assert proc.stdin is not None
            proc.stdin.write(frame.tobytes())
            if index % preview_stride == 0:
                preview_indices.append(index)
                previews.append(frame.resize((width // 2, height // 2)).convert("P", palette=Image.Palette.ADAPTIVE, colors=160))
            if index in {round(i * (frame_count - 1) / 5) for i in range(6)}:
                selected.append(frame.copy())
    finally:
        if proc.stdin:
            proc.stdin.close()
        return_code = proc.wait()
    if return_code != 0:
        raise RuntimeError("ffmpeg animation encoding failed")
    gif = owned_path(output, f"{sequence_id}_preview.gif")
    previews[0].save(gif, save_all=True, append_images=previews[1:], duration=_preview_durations(preview_indices, fps, frame_count), loop=0, disposal=2)
    sheet = Image.new("RGB", (width * 2, height * 3), (230, 230, 230))
    for idx, frame in enumerate(selected[:6]):
        sheet.paste(frame, ((idx % 2) * width, (idx // 2) * height))
    contact = owned_path(output, f"{sequence_id}_contact_sheet.jpg")
    sheet.resize((width, int(height * 1.5))).save(contact, quality=90)
    motion_audit = audit_motion(sequence, solids)
    manifest = {
        "sequence": sequence_id, "truth_mode": sequence["truth_mode"], "contract_hash": contract.hash,
        "model_hash": model_hash, "fps": fps, "frame_count": frame_count, "camera": sequence["camera"],
        "artifacts": [{"path": str(path), "sha256": sha256_file(path)} for path in (mp4, gif, contact)],
        "motion_audit": motion_audit,
    }
    atomic_json(owned_path(output, "animation-manifest.json"), manifest)
    return manifest


def prepare_2_5d_package(contract: Contract, sequence_id: str, output: Path) -> dict[str, Any]:
    sequence = contract.animation(sequence_id)
    if sequence["truth_mode"] != "presentation_only_2_5d":
        raise ValueError("Sequence is not presentation_only_2_5d")
    output.mkdir(parents=True, exist_ok=True)
    package = {
        "sequence": sequence_id, "truth_mode": "presentation_only_2_5d", "contract_hash": contract.hash,
        "requirements": [
            "Use only accepted, hash-verified backgrounds and actor sprites.",
            "Move mechanically coupled actors with identical transforms.",
            "Keep camera fixed unless every source layer shares the same projection.",
            "Create MP4, reduced preview GIF, six-frame contact sheet, and audit report.",
            "Burn in: CONCEPT ANIMATION — NOT A MANUFACTURING DRAWING.",
        ],
        "prohibited": ["invented geometry", "rejected reference", "camera parallax from a single raster", "technical-master promotion"],
    }
    atomic_json(owned_path(output, "presentation-animation-package.json"), package)
    return package
