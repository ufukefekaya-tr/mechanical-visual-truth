from __future__ import annotations

import cadquery as cq
import pytest

from mvt.errors import BuildError
from mvt.step_io import compare_shapes, inspect_step, load_step, match_step_solids, shape_signature, verify_step_roundtrip


def test_native_step_roundtrip_preserves_separate_solids_and_world_pose(tmp_path):
    a = cq.Workplane("XY").box(20, 12, 4).val()
    b = cq.Workplane("XY").circle(3).extrude(8).translate((30, 5, 9)).val()
    source = cq.Compound.makeCompound([a, b])
    output = tmp_path / "generic-assembly.step"
    report = verify_step_roundtrip(source, output)
    inspected = inspect_step(output)
    assert report["status"] == "PASS"
    assert report["geometry_boolean_checked"] is True
    assert len(report["matches"]) == 2
    assert inspected["status"] == "PASS"
    assert inspected["solid_count"] == 2
    assert inspected["bbox"]["max"] == pytest.approx([33, 8, 17], abs=2e-5)
    assert inspected["volume_mm3"] == pytest.approx(a.Volume() + b.Volume(), rel=1e-8)
    assert len(inspected["sha256"]) == 64


def test_comparison_detects_changed_internal_features_with_same_volume_and_bounds():
    stock = cq.Workplane("XY").box(20, 20, 4).val()
    tool = cq.Workplane("XY").circle(2).extrude(8, both=True).val()
    left = stock.cut(tool.translate((-5, 0, 0)))
    right = stock.cut(tool.translate((5, 0, 0)))
    report = compare_shapes(left, right)
    assert report["bbox_max_delta_mm"] == pytest.approx(0)
    assert report["volume_delta_mm3"] == pytest.approx(0, abs=1e-8)
    assert report["status"] == "RED"
    assert report["matches"] == []
    assert compare_shapes(left, right, check_geometry=False)["status"] == "PASS"


def test_comparison_detects_displacement_and_missing_solid():
    source = cq.Workplane("XY").box(4, 5, 6).val()
    assert compare_shapes(source, source.translate((1, 0, 0)))["status"] == "RED"
    double = cq.Compound.makeCompound([source, source.translate((15, 0, 0))])
    assert compare_shapes(double, source)["status"] == "RED"


def test_signature_ignores_render_triangulation():
    shape = cq.Workplane("XY").circle(13).extrude(8).rotate((0, 0, 0), (1, 1, 0), 23).val()
    before = shape_signature(shape)
    shape.tessellate(0.8, 0.2)
    after = shape_signature(shape)
    for axis in ("min", "max"):
        assert before["bbox"][axis] == pytest.approx(after["bbox"][axis], abs=1e-10)


def test_invalid_step_and_missing_file_fail_explicitly(tmp_path):
    corrupt = tmp_path / "broken.step"
    corrupt.write_text("This is not an ISO-10303 CAD model.")
    with pytest.raises(BuildError, match="Native STEP import failed|no native shapes"):
        inspect_step(corrupt)
    with pytest.raises(BuildError, match="does not exist"):
        load_step(tmp_path / "missing.step")
    corrupt.write_text("")
    with pytest.raises(BuildError, match="empty"):
        inspect_step(corrupt)


def test_existing_artifact_is_preserved(tmp_path):
    output = tmp_path / "accepted.step"
    output.write_bytes(b"preserve this accepted artifact")
    with pytest.raises(BuildError, match="overwrite"):
        verify_step_roundtrip(cq.Workplane("XY").box(2, 3, 4).val(), output)
    assert output.read_bytes() == b"preserve this accepted artifact"


def test_registry_mapping_is_unordered_hash_checked_and_rejects_ambiguity(tmp_path):
    a = cq.Workplane("XY").box(4, 5, 6).val()
    b = cq.Workplane("XY").circle(2).extrude(3).translate((12, 0, 0)).val()
    output = tmp_path / "components.step"
    report = verify_step_roundtrip(cq.Compound.makeCompound([b, a]), output)
    records = [{"id": name, **shape_signature(shape)["solids"][0]} for name, shape in (("block", a), ("spacer", b))]
    matches = match_step_solids(output, records, expected_sha256=report["sha256"])
    assert set(matches) == {"block", "spacer"}
    assert matches["block"].Volume() == pytest.approx(a.Volume())
    with pytest.raises(BuildError, match="hash mismatch"):
        match_step_solids(output, records, expected_sha256="0" * 64)
    # Two records with the same signature cannot silently acquire different IDs.
    with pytest.raises(BuildError, match="Non-unique"):
        match_step_solids(output, [records[0], {**records[0], "id": "unrelated"}])
    with pytest.raises(BuildError, match="unique nonempty"):
        match_step_solids(output, [records[0], records[0]])


@pytest.mark.parametrize("value", [float("nan"), -1, True])
def test_invalid_tolerances_are_rejected(value):
    shape = cq.Workplane("XY").box(2, 3, 4).val()
    with pytest.raises(BuildError, match="tolerance|Tolerance"):
        compare_shapes(shape, shape, linear_tolerance_mm=value)
