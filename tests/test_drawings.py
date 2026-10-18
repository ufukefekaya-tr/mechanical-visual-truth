from __future__ import annotations

import xml.etree.ElementTree as ET

import cadquery as cq
import pytest

from mvt.drawings import export_shape_drawing, export_step_drawing, section_edges, section_plane_edges
from mvt.errors import BuildError
from mvt.step_io import verify_step_roundtrip


def test_orthographic_views_come_from_reloaded_cad_and_escape_title(tmp_path):
    shape = cq.Workplane("XY").box(20, 12, 4).faces(">Z").workplane().hole(4).val()
    step = tmp_path / "part.step"
    exported = verify_step_roundtrip(shape, step)
    output = tmp_path / "part.svg"
    report = export_step_drawing(step, output, title="Fixture <A> & bracket", show_hidden=True)
    root = ET.parse(output).getroot()
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    assert root.find("svg:title", namespace).text == "Fixture <A> & bracket"
    text = " ".join(root.itertext())
    for label in ("Top (X / Y)", "Front (X / Z)", "Right (Y / Z)", "20.000", "12.000", "4.000"):
        assert label in text
    assert report["source_sha256"] == exported["sha256"]
    assert report["projection"] == "third_angle"
    assert report["source_geometry"]["solid_count"] == 1
    assert len(root.findall(".//svg:path", namespace)) > 10
    assert not root.findall(".//svg:image", namespace)
    assert not root.findall(".//svg:script", namespace)


def test_section_is_native_geometry_in_world_coordinates():
    shape = cq.Workplane("XY").box(20, 12, 4).translate((8, 2, 10)).val()
    edges = section_edges(shape, axis="z", offset_mm=10)
    assert len(edges) == 4
    assert sum(edge.Length() for edge in edges) == pytest.approx(64)
    for edge in edges:
        box = edge.BoundingBox()
        assert box.zmin == pytest.approx(10)
        assert box.zmax == pytest.approx(10)
    assert section_edges(shape, axis="z", offset_mm=-20) == []


def test_tilted_section_uses_declared_plane():
    shape = cq.Workplane("XY").box(10, 10, 10).val()
    edges = section_plane_edges(shape, origin=(0, 0, 0), normal=(1, 1, 0))
    assert len(edges) == 4
    assert sum(edge.Length() for edge in edges) == pytest.approx(20 + 20 * 2**0.5)
    for edge in edges:
        point = edge.positionAt(0.5)
        assert point.x + point.y == pytest.approx(0, abs=1e-8)
    with pytest.raises(BuildError, match="nonzero"):
        section_plane_edges(shape, origin=(0, 0, 0), normal=(0, 0, 0))


@pytest.mark.parametrize("axis,offset", [("bad", 0), ("x", float("inf")), ("z", True)])
def test_invalid_section_plane_rejected(axis, offset):
    shape = cq.Workplane("XY").box(2, 3, 4).val()
    with pytest.raises(BuildError, match="axis|offset"):
        section_edges(shape, axis=axis, offset_mm=offset)


def test_drawing_preserves_existing_file(tmp_path):
    output = tmp_path / "accepted.svg"
    output.write_bytes(b"original")
    with pytest.raises(BuildError, match="overwrite"):
        export_shape_drawing(cq.Workplane("XY").box(2, 3, 4).val(), output)
    assert output.read_bytes() == b"original"
