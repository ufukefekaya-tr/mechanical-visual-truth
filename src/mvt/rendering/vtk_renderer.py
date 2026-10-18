"""Native CAD proof rendering without replacing source geometry.

Copyright 2026 Ufuk Efe Kaya
SPDX-License-Identifier: MIT OR Apache-2.0
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageStat

from mvt.errors import BuildError
from mvt.geometry import EntitySolid
from mvt.util import owned_path


class MeshCache:
    """Bounded cache of the exact source shape, never a similar-looking substitute."""

    def __init__(self, max_bytes: int = 256 * 1024 * 1024):
        self.max_bytes = max_bytes
        self.used_bytes = 0
        self._entries: dict[tuple[int, float], tuple[Any, Any]] = {}

    def mapper(self, item: EntitySolid, tolerance: float):
        import vtk

        key = (id(item.shape), tolerance)
        if key in self._entries:
            return self._entries[key][1]
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(_polydata(item.shape, tolerance))
        size = max(4096, mapper.GetInput().GetActualMemorySize() * 1024)
        if size <= self.max_bytes - self.used_bytes:
            # Keeping the shape alive also prevents reuse of its Python object ID.
            self._entries[key] = (item.shape, mapper)
            self.used_bytes += size
        return mapper


def _polydata(shape: Any, tolerance: float = 0.8):
    import vtk

    vertices, triangles = shape.tessellate(tolerance)
    if not vertices or not triangles:
        raise BuildError("CAD tessellation produced no visible surface")
    points = vtk.vtkPoints()
    points.SetDataTypeToDouble()
    for vertex in vertices:
        points.InsertNextPoint(float(vertex.x), float(vertex.y), float(vertex.z))
    cells = vtk.vtkCellArray()
    for triangle in triangles:
        cells.InsertNextCell(3)
        for index in triangle:
            cells.InsertCellPoint(int(index))
    data = vtk.vtkPolyData()
    data.SetPoints(points)
    data.SetPolys(cells)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(data)
    normals.ComputePointNormalsOn()
    normals.SplittingOn()
    normals.SetFeatureAngle(30.0)
    normals.Update()
    return normals.GetOutput()


def _vtk_pose(pose: dict[str, list[float]]):
    """Match OCC: rotate world geometry X/Y/Z around pivot, then translate."""
    import vtk

    transform = vtk.vtkTransform()
    transform.PostMultiply()
    pivot = pose.get("pivot", [0, 0, 0])
    transform.Translate(*(-value for value in pivot))
    for axis, angle in zip("XYZ", pose.get("rotation", [0, 0, 0])):
        getattr(transform, f"Rotate{axis}")(angle)
    transform.Translate(*pivot)
    transform.Translate(*pose.get("translation", [0, 0, 0]))
    return transform


def _actor(item: EntitySolid, transform: list[float] | dict[str, list[float]] | None = None, tolerance: float = 0.8, cache: MeshCache | None = None):
    import vtk

    mapper = cache.mapper(item, tolerance) if cache else vtk.vtkPolyDataMapper()
    if cache is None:
        mapper.SetInputData(_polydata(item.shape, tolerance))
    mapper.ScalarVisibilityOff()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetColor(*item.color)
    prop.SetInterpolationToPhong()
    material = item.material.lower()
    if any(word in material for word in ("wood", "carton", "paper")):
        values = (0.22, 0.78, 0.055, 12.0)
    elif any(word in material for word in ("steel", "stainless", "aluminium", "aluminum")):
        values = (0.18, 0.70, 0.32, 48.0)
    elif "paint" in material:
        values = (0.20, 0.74, 0.14, 30.0)
    else:
        values = (0.20, 0.76, 0.12, 24.0)
    ambient, diffuse, specular, power = values
    prop.SetAmbient(ambient)
    prop.SetDiffuse(diffuse)
    prop.SetSpecular(specular)
    prop.SetSpecularPower(power)
    if isinstance(transform, dict):
        actor.SetUserTransform(_vtk_pose(transform))
    elif transform is not None:
        actor.SetPosition(*transform)
    return actor


def _edge_actor(surface: Any):
    import vtk

    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(surface.GetMapper().GetInput())
    clean.ToleranceIsAbsoluteOn()
    clean.SetAbsoluteTolerance(0.0)
    edges = vtk.vtkFeatureEdges()
    edges.SetInputConnection(clean.GetOutputPort())
    edges.FeatureEdgesOn()
    edges.BoundaryEdgesOn()
    edges.NonManifoldEdgesOn()
    edges.ManifoldEdgesOff()
    edges.SetFeatureAngle(30.0)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(edges.GetOutputPort())
    mapper.ScalarVisibilityOff()
    mapper.SetResolveCoincidentTopologyToPolygonOffset()
    mapper.SetRelativeCoincidentTopologyLineOffsetParameters(-1.0, -1.0)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.SetPosition(*surface.GetPosition())
    if surface.GetUserTransform() is not None:
        actor.SetUserTransform(surface.GetUserTransform())
    prop = actor.GetProperty()
    prop.SetColor(0.12, 0.14, 0.16)
    prop.SetOpacity(0.65)
    prop.SetLineWidth(1.0)
    prop.LightingOff()
    return actor


def _studio_lighting(renderer: Any, camera: dict[str, Any]) -> None:
    import vtk

    renderer.RemoveAllLights()
    focus, eye, up = camera["focal_point"], camera["position"], camera["up"]
    view = [eye[i] - focus[i] for i in range(3)]
    length = math.sqrt(sum(value * value for value in view))
    if length <= 1e-9:
        raise BuildError("Camera position equals focal point")
    view = [value / length for value in view]
    right = [view[1]*up[2]-view[2]*up[1], view[2]*up[0]-view[0]*up[2], view[0]*up[1]-view[1]*up[0]]
    length = math.sqrt(sum(value * value for value in right))
    if length <= 1e-9:
        raise BuildError("Camera up is parallel to view")
    right = [value / length for value in right]
    true_up = [right[1]*view[2]-right[2]*view[1], right[2]*view[0]-right[0]*view[2], right[0]*view[1]-right[1]*view[0]]
    for side, height, front, intensity, color in (
        (-0.75, 0.85, 1.0, 0.90, (1.0, 0.97, 0.93)),
        (0.95, 0.22, 0.65, 0.38, (0.88, 0.94, 1.0)),
        (0.15, 1.0, -0.70, 0.42, (1.0, 1.0, 1.0)),
    ):
        light = vtk.vtkLight()
        light.SetLightTypeToSceneLight()
        light.SetPositional(False)
        light.SetPosition(*(focus[i] + side*right[i] + height*true_up[i] + front*view[i] for i in range(3)))
        light.SetFocalPoint(*focus)
        light.SetColor(*color)
        light.SetIntensity(intensity)
        renderer.AddLight(light)


def _proof_labels(solids: list[EntitySolid], watermark: str | None) -> list[str]:
    labels = [watermark] if watermark else []
    if any(item.metadata.get("validation_tier") == "concept_visual" for item in solids):
        labels.append("CONCEPT VISUAL - PHYSICAL VALIDATION PENDING")
    if any(item.metadata.get("representation") == "concept_proxy" for item in solids):
        labels.append("CONCEPT PROXY GEOMETRY")
    if any("commercially_unverified" in (item.metadata.get("commercial_status"), item.metadata.get("status")) for item in solids):
        labels.append("commercially_unverified")
    return list(dict.fromkeys(labels))


def render_png(
    solids: list[EntitySolid], camera: dict[str, Any], path: Path,
    transforms: dict[str, list[float] | dict[str, list[float]]] | None = None,
    watermark: str | None = None, mesh_cache: MeshCache | None = None,
) -> Path:
    import vtk

    if not solids:
        raise BuildError("Cannot render an empty model")
    path = owned_path(path.parent, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    renderer = vtk.vtkRenderer()
    # A gradient has enough variance to hide an empty or off-camera scene.
    renderer.SetBackground(*camera.get("background", [0.92, 0.93, 0.94]))
    for item in solids:
        pose = (transforms or {}).get(item.id, (transforms or {}).get(item.metadata.get("actor", item.id)))
        surface = _actor(item, pose, camera.get("tessellation_tolerance", 0.8), mesh_cache)
        renderer.AddActor(surface)
        if camera.get("show_edges", True):
            renderer.AddActor(_edge_actor(surface))
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetMultiSamples(4)
    width, height = camera["size"]
    window.SetSize(width, height)
    window.AddRenderer(renderer)
    cam = vtk.vtkCamera()
    cam.SetPosition(*camera["position"])
    cam.SetFocalPoint(*camera["focal_point"])
    cam.SetViewUp(*camera["up"])
    if camera["projection"] == "parallel":
        cam.ParallelProjectionOn()
        cam.SetParallelScale(camera.get("parallel_scale", 1000))
    else:
        cam.SetViewAngle(camera.get("view_angle", 30))
    renderer.SetActiveCamera(cam)
    _studio_lighting(renderer, camera)
    renderer.ResetCameraClippingRange()
    try:
        window.Render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.SetInputBufferTypeToRGB()
        capture.ReadFrontBufferOff()
        capture.Update()
        writer = vtk.vtkPNGWriter()
        writer.SetFileName(str(path))
        writer.SetInputConnection(capture.GetOutputPort())
        writer.Write()
    finally:
        window.Finalize()
    if not path.exists() or path.stat().st_size < 1000:
        raise BuildError(f"Empty render: {path}")
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    if sum(ImageStat.Stat(image).var) < 2.0:
        raise BuildError(f"Background-only render detected: {path}")
    labels = _proof_labels(solids, watermark)
    if labels:
        draw = ImageDraw.Draw(image, "RGBA")
        font = ImageFont.load_default(size=max(10, min(18, width // 60)))
        line_height = max(18, min(26, height // 24))
        top = max(4, height-16-line_height*len(labels)-16)
        label_width = max(draw.textbbox((0, 0), label, font=font)[2] for label in labels)
        draw.rounded_rectangle((8, top, min(width-8, 28+label_width), height-8), radius=6, fill=(10, 14, 18, 210))
        for index, label in enumerate(labels):
            draw.text((16, top+6+index*line_height), label, font=font, fill=(255, 255, 255, 255))
        image.save(path)
    return path
