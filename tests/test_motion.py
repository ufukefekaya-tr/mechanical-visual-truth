from __future__ import annotations

import copy
from dataclasses import replace

import cadquery as cq
import pytest

from mvt.geometry import build_model
from mvt.rendering.animation import audit_motion, posed_solids, poses_at
from mvt.rendering.vtk_renderer import _vtk_pose


def test_coupled_motion_passes(mechanics):
    result = audit_motion(mechanics.animation("transfer"), build_model(mechanics))
    assert result["status"] == "PASS", result
    assert result["physical_status"] == result["safety_status"] == "YELLOW"


def test_uncoupled_payload_is_red(mechanics):
    sequence = copy.deepcopy(mechanics.animation("transfer"))
    for frame in sequence["keyframes"]:
        if frame["entity"] == "payload" and frame["t"] > 0:
            frame["translation"] = [0,0,0]
    result = audit_motion(sequence, build_model(mechanics))
    assert any(item["gate"] == "coupled-motion" and item["status"] == "RED" for item in result["findings"])


def test_authored_key_pose_is_always_sampled(mechanics):
    sequence = copy.deepcopy(mechanics.animation("transfer"))
    sequence["sample_every"] = 1000
    sequence["keyframes"].append({"entity": "carriage", "t": 0.37, "translation": [20,0,0]})
    result = audit_motion(sequence, build_model(mechanics))
    assert 0.37 in result["sample_times"]
    assert any(item["gate"] == "collision" and item["status"] == "RED" for item in result["findings"])


def test_presentation_mode_cannot_pass_cad_validation(mechanics):
    result = audit_motion(mechanics.animation("presentation-transfer"), build_model(mechanics))
    assert result["status"] == "YELLOW"
    assert result["geometry_status"] == "NOT_APPLICABLE"
    assert result["limitations"]


def test_ring_hole_is_not_a_bbox_collision(mechanics):
    solids = build_model(mechanics)[:2]
    ring = cq.Workplane("XY").circle(10).circle(6).extrude(5, both=True).val()
    pin = cq.Workplane("XY").circle(2).extrude(4, both=True).val()
    solids = [replace(solids[0], id="ring", shape=ring), replace(solids[1], id="pin", shape=pin)]
    sequence = {"duration": 1, "fps": 1, "truth_mode": "deterministic_cad", "keyframes": [], "collision_pairs": [["ring","pin"]]}
    result = audit_motion(sequence, solids)
    assert result["status"] == "PASS", result
    assert result["collision_audit"]["peak_intersection_mm3"] == 0


def test_contact_allowance_does_not_hide_penetration(mechanics):
    solids = build_model(mechanics)[:2]
    solids = [replace(solids[0], id="a", shape=cq.Workplane("XY").box(10,10,10).val()), replace(solids[1], id="b", shape=cq.Workplane("XY").box(8,8,8).val())]
    sequence = {"duration": 1, "fps": 1, "truth_mode": "deterministic_cad", "keyframes": [], "collision_pairs": [["a","b"]], "allowed_contact_pairs": [["a","b"]]}
    assert audit_motion(sequence, solids)["status"] == "RED"


def test_rotation_render_transform_matches_cad_pose(mechanics):
    sequence = {"keyframes": [{"entity": "carriage", "t": 0, "translation": [3,-2,5], "rotation": [23,45,67], "pivot": [4,5,6]}]}
    solids = build_model(mechanics)
    original = next(item for item in solids if item.id == "carriage")
    pose = poses_at(sequence, 0)["carriage"]
    transformed = _vtk_pose(pose).TransformPoint(6,4,4)
    point = cq.Vertex.makeVertex(6,4,4)
    for axis, angle in zip(((1,0,0),(0,1,0),(0,0,1)), pose["rotation"]):
        point = point.rotate(pose["pivot"], [pose["pivot"][i]+axis[i] for i in range(3)], angle)
    point = point.translate(pose["translation"])
    assert transformed == pytest.approx(point.Center().toTuple(), abs=1e-7)
    posed = next(item for item in posed_solids(sequence, solids, 0) if item.id == "carriage")
    assert posed.shape.Volume() == pytest.approx(original.shape.Volume())


def test_full_scope_detects_an_undeclared_pair_collision(mechanics):
    solids = build_model(mechanics)[:2]
    solids = [replace(solids[0], shape=cq.Workplane("XY").box(10,10,10).val()), replace(solids[1], shape=cq.Workplane("XY").box(8,8,8).val())]
    sequence = {"duration": 1, "fps": 1, "truth_mode": "deterministic_cad", "keyframes": [], "collision_scope": [item.id for item in solids]}
    result = audit_motion(sequence, solids)
    assert result["status"] == "RED"
    assert result["collision_audit"]["coverage"] == "all_entities"


def test_gif_preview_timing_tracks_non_multiple_fps():
    from mvt.rendering.animation import _preview_durations

    # 25 MP4 frames at 8 fps include the authored end pose, i.e. 3125 ms.
    durations = _preview_durations(list(range(25)), 8, 25)
    assert abs(sum(durations)-3125) <= 10
    assert set(durations) == {120,130}


def test_animation_refuses_nested_frames_symlink_before_encoding(mechanics, tmp_path):
    from mvt.rendering.animation import build_cad_animation

    output = tmp_path / "animation"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (output / "frames").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        build_cad_animation(mechanics, [], "synthetic", "transfer", output)
    assert not list(outside.iterdir())
