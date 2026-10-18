"""Project-independent technical views and real CAD section extraction."""
from __future__ import annotations

import math
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import cadquery as cq
from cadquery.occ_impl.exporters.svg import getPaths
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.BRepLib import BRepLib
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.gp import gp_Ax2, gp_Dir, gp_Pln, gp_Pnt

from mvt.errors import BuildError
from mvt.step_io import load_step, shape_signature
from mvt.util import sha256_file

_SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", _SVG)


def _element(parent: ET.Element, tag: str, **attributes: Any) -> ET.Element:
    return ET.SubElement(parent, f"{{{_SVG}}}{tag}", {key.replace("_", "-"): str(value) for key, value in attributes.items()})


def _text(parent: ET.Element, x: float, y: float, value: str, **attributes: Any) -> ET.Element:
    node = _element(parent, "text", x=x, y=y, **attributes)
    node.text = value
    return node


def _projection_paths(shape: cq.Shape, normal: tuple[int, int, int], x_direction: tuple[int, int, int]) -> tuple[list[str], list[str]]:
    """Use native hidden-line removal with explicit drawing coordinate axes."""
    algorithm = HLRBRep_Algo()
    algorithm.Add(shape.wrapped)
    frame = gp_Ax2(gp_Pnt(), gp_Dir(*normal), gp_Dir(*x_direction))
    algorithm.Projector(HLRAlgo_Projector(frame))
    algorithm.Update()
    algorithm.Hide()
    converter = HLRBRep_HLRToShape(algorithm)
    visible, hidden = [], []
    for result, shapes in (
        (converter.VCompound(), visible), (converter.Rg1LineVCompound(), visible),
        (converter.OutLineVCompound(), visible), (converter.HCompound(), hidden),
        (converter.OutLineHCompound(), hidden),
    ):
        if not result.IsNull():
            # OpenCascade's HLR output needs 3-D curves before edge sampling.
            BRepLib.BuildCurves3d_s(result, 1e-7)
            shapes.append(cq.Shape(result))
    if not visible:
        raise BuildError("Native CAD projection contains no visible edges")
    return getPaths(visible, hidden)


def _horizontal_dimension(parent: ET.Element, a: float, b: float, y: float, reference: float, label: str) -> None:
    for x in (a, b):
        _element(parent, "line", x1=x, y1=reference + 5, x2=x, y2=y + 6, stroke="#9baeb8", stroke_width=0.8)
    _element(parent, "line", x1=a, y1=y, x2=b, y2=y, stroke="#26628b", marker_start="url(#arrow)", marker_end="url(#arrow)")
    _text(parent, (a + b) / 2, y - 7, label, text_anchor="middle", fill="#26628b", font_size=13)


def _vertical_dimension(parent: ET.Element, a: float, b: float, x: float, reference: float, label: str) -> None:
    for y in (a, b):
        _element(parent, "line", x1=reference - 5, y1=y, x2=x - 6, y2=y, stroke="#9baeb8", stroke_width=0.8)
    _element(parent, "line", x1=x, y1=a, x2=x, y2=b, stroke="#26628b", marker_start="url(#arrow)", marker_end="url(#arrow)")
    mid = (a + b) / 2
    _text(parent, x - 8, mid, label, text_anchor="middle", fill="#26628b", font_size=13, transform=f"rotate(-90 {x - 8} {mid})")


def export_shape_drawing(
    shape: cq.Shape, output_svg: str | Path, *, title: str = "Mechanical part",
    show_hidden: bool = False, overwrite: bool = False, source_sha256: str | None = None,
) -> dict[str, Any]:
    """Write third-angle top/front/right SVG views from exact CAD geometry.

    All views share one scale. Dimensions describe the actual overall bounding
    box in mm; this is not automatic manufacturing-feature dimensioning, sheet
    unfolding, or a drawing certification. The SVG contains no embedded raster.
    """
    signature = shape_signature(shape)
    if not signature["valid"] or signature["solid_count"] == 0:
        raise BuildError("Technical drawing requires valid solid CAD geometry")
    low, high = signature["bbox"]["min"], signature["bbox"]["max"]
    sx, sy, sz = [b - a for a, b in zip(low, high)]
    if min(sx, sy, sz) <= 1e-9:
        raise BuildError("Technical drawing requires nonzero dimensions on all axes")
    output = Path(output_svg).expanduser().resolve()
    if output.exists() and not overwrite:
        raise BuildError(f"Refusing to overwrite existing drawing artifact: {output}")
    gap, x0, y0 = 110.0, 90.0, 130.0
    scale = min((1040 - gap) / (sx + sy), (580 - gap) / (sy + sz))
    y_front = y0 + sy * scale + gap
    x_right = x0 + sx * scale + gap
    root = ET.Element(f"{{{_SVG}}}svg", {"width": "1200", "height": "900", "viewBox": "0 0 1200 900"})
    accessible_title = _element(root, "title")
    accessible_title.text = str(title)
    description = _element(root, "desc")
    description.text = "Exact CAD orthographic projections, third-angle arrangement, common scale, overall model dimensions in mm."
    _element(root, "rect", width=1200, height=900, fill="white")
    definitions = _element(root, "defs")
    arrow = _element(definitions, "marker", id="arrow", markerWidth=7, markerHeight=7, refX=3.5, refY=3.5, orient="auto-start-reverse", markerUnits="strokeWidth")
    _element(arrow, "path", d="M 0 0 L 7 3.5 L 0 7 Z", fill="#26628b")
    content = _element(root, "g", font_family="DejaVu Sans, sans-serif", fill="#152835")
    _text(content, 45, 45, str(title)[:110], font_size=25, font_weight="bold")
    _text(content, 45, 73, "CAD ORTHOGRAPHIC VIEWS  |  THIRD ANGLE  |  mm  |  OVERALL DIMENSIONS", font_size=13, fill="#26628b")
    _element(content, "line", x1=45, x2=1155, y1=91, y2=91, stroke="#a7b6be")
    views = (
        ("Top (X / Y)", (0, 0, 1), (1, 0, 0), x0, y0, low[0], high[1]),
        ("Front (X / Z)", (0, -1, 0), (1, 0, 0), x0, y_front, low[0], high[2]),
        ("Right (Y / Z)", (1, 0, 0), (0, 1, 0), x_right, y_front, low[1], high[2]),
    )
    try:
        for label, normal, x_direction, x, y, minimum_x, maximum_y in views:
            hidden_paths, visible_paths = _projection_paths(shape, normal, x_direction)
            _text(content, x, y - 16, label, font_size=14, font_weight="bold")
            # Specify line widths in model units so SVG rasterizers that do not
            # implement vector-effect still produce consistent 1.25 px lines.
            group = _element(content, "g", transform=f"translate({x - scale * minimum_x} {y + scale * maximum_y}) scale({scale} {-scale})", fill="none", stroke="#152835", stroke_width=1.25 / scale)
            if show_hidden:
                for path in hidden_paths:
                    _element(group, "path", d=path, stroke="#91a1aa", stroke_dasharray=f"{5 / scale} {4 / scale}")
            for path in visible_paths:
                _element(group, "path", d=path)
    except BuildError:
        raise
    except Exception as exc:
        raise BuildError(f"Native CAD projection failed: {type(exc).__name__}") from exc
    base = y_front + sz * scale
    _horizontal_dimension(content, x0, x0 + sx * scale, base + 29, base, f"{sx:.3f}")
    _horizontal_dimension(content, x_right, x_right + sy * scale, base + 29, base, f"{sy:.3f}")
    _vertical_dimension(content, y_front, base, x0 - 30, x0, f"{sz:.3f}")
    _vertical_dimension(content, y0, y0 + sy * scale, x0 - 30, x0, f"{sy:.3f}")
    _element(content, "line", x1=45, x2=1155, y1=799, y2=799, stroke="#a7b6be")
    _text(content, 45, 824, f"Native solids: {signature['solid_count']}  |  Volume: {signature['volume_mm3']:.3f} mm³  |  Validity: PASS", font_size=13)
    _text(content, 45, 846, "Overall model dimensions only; specify feature dimensions, fits and tolerances separately.", font_size=12, fill="#536873")
    if source_sha256:
        _text(content, 45, 871, f"Source STEP SHA-256: {source_sha256}", font_size=10, fill="#536873")
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=".svg", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        if overwrite:
            os.replace(temporary, output)
        else:
            os.link(temporary, output)
            temporary.unlink()
    except Exception as exc:
        raise BuildError(f"Technical drawing write failed: {type(exc).__name__}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return {"status": "PASS", "path": str(output), "sha256": sha256_file(output),
            "source_sha256": source_sha256, "views": ["top", "front", "right"],
            "projection": "third_angle", "units": "mm", "dimensions": "bounding_box",
            "source_geometry": signature}


def export_step_drawing(
    step_path: str | Path, output_svg: str | Path, *, title: str = "Mechanical part",
    show_hidden: bool = False, overwrite: bool = False,
) -> dict[str, Any]:
    """Load any STEP file and create a CAD-derived technical-view SVG."""
    source = Path(step_path).expanduser().resolve()
    shape = load_step(source)
    return export_shape_drawing(shape, output_svg, title=title, show_hidden=show_hidden,
                                overwrite=overwrite, source_sha256=sha256_file(source))


def section_edges(shape: cq.Shape, *, axis: str, offset_mm: float) -> list[cq.Edge]:
    """Extract actual B-rep/plane intersection edges at a model-space datum.

    No silhouette is hand drawn and no sheet-specific geometry is inferred.
    Empty intersections return an empty list, not a fabricated profile.
    """
    axes = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}
    if axis not in axes:
        raise BuildError("Section axis must be x, y or z")
    if isinstance(offset_mm, bool) or not isinstance(offset_mm, (int, float)) or not math.isfinite(offset_mm):
        raise BuildError("Section offset must be finite")
    normal = axes[axis]
    point = tuple(value * offset_mm for value in normal)
    return section_plane_edges(shape, origin=point, normal=normal)


def section_plane_edges(
    shape: cq.Shape, *, origin: tuple[float, float, float], normal: tuple[float, float, float],
) -> list[cq.Edge]:
    """Intersect native CAD with an arbitrary explicit plane, including tilt."""
    for label, vector in (("origin", origin), ("normal", normal)):
        if not isinstance(vector, (list, tuple)) or len(vector) != 3 or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in vector
        ):
            raise BuildError(f"Section plane {label} must contain three finite coordinates")
    if math.hypot(*normal) <= 1e-12:
        raise BuildError("Section plane normal must be nonzero")
    shape_signature(shape)
    try:
        section = BRepAlgoAPI_Section(shape.wrapped, gp_Pln(gp_Pnt(*origin), gp_Dir(*normal)), False)
        section.Approximation(True)
        section.Build()
        if not section.IsDone():
            raise BuildError("Native B-rep section failed")
        result = section.Shape()
        return [] if result.IsNull() else cq.Shape(result).Edges()
    except BuildError:
        raise
    except Exception as exc:
        raise BuildError(f"Native B-rep section failed: {type(exc).__name__}") from exc
