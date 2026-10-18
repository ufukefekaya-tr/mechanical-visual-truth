"""Native STEP inspection and independently reloaded export verification.

Coordinates, lengths and volumes use CadQuery's millimetre model units. Nothing
here depends on a project contract, a particular machine or an on-server path.
"""
from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Any

import cadquery as cq
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib

from mvt.errors import BuildError
from mvt.util import sha256_file


def _tolerance(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise BuildError(f"{label} must be a finite nonnegative number")
    return float(value)


def _bbox(shape: cq.Shape) -> dict[str, list[float]]:
    # Triangulation used for a render can pad CadQuery's default bounds. STEP
    # checks must depend on the native B-rep, never on prior rendering history.
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    values = box.Get()
    return {"min": list(values[:3]), "max": list(values[3:])}


def _solid_signature(solid: cq.Shape) -> dict[str, Any]:
    return {"bbox": _bbox(solid), "volume_mm3": solid.Volume(), "valid": solid.isValid()}


def shape_signature(shape: cq.Shape) -> dict[str, Any]:
    """Describe actual B-rep geometry, without guessing identity from STEP order."""
    if not isinstance(shape, cq.Shape) or shape.wrapped.IsNull():
        raise BuildError("STEP geometry is empty or is not a CadQuery shape")
    try:
        solids = shape.Solids()
        rows = [_solid_signature(solid) for solid in solids]
        result = {
            "units": "mm", "valid": shape.isValid() and all(row["valid"] for row in rows),
            "solid_count": len(solids), "face_count": len(shape.Faces()), "edge_count": len(shape.Edges()),
            "volume_mm3": sum(row["volume_mm3"] for row in rows), "bbox": _bbox(shape), "solids": rows,
        }
    except Exception as exc:
        raise BuildError(f"Native geometry inspection failed: {type(exc).__name__}") from exc
    values = result["bbox"]["min"] + result["bbox"]["max"] + [result["volume_mm3"]]
    if not all(math.isfinite(value) for value in values):
        raise BuildError("Native geometry contains nonfinite bounds or volume")
    return result


def load_step(path: str | Path) -> cq.Shape:
    """Read STEP through OpenCascade; malformed or empty files fail explicitly."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise BuildError(f"STEP file does not exist: {source}")
    if source.stat().st_size == 0:
        raise BuildError("STEP file is empty")
    try:
        values = cq.importers.importStep(str(source)).vals()
        if not values or not all(isinstance(shape, cq.Shape) for shape in values):
            raise BuildError("STEP file contains no native shapes")
        shape = values[0] if len(values) == 1 else cq.Compound.makeCompound(values)
        shape_signature(shape)
        return shape
    except BuildError:
        raise
    except Exception as exc:
        raise BuildError(f"Native STEP import failed: {type(exc).__name__}") from exc


def inspect_step(path: str | Path) -> dict[str, Any]:
    """Inspect any STEP file; shell-only and invalid solid models return RED."""
    source = Path(path).expanduser().resolve()
    signature = shape_signature(load_step(source))
    return {
        "status": "PASS" if signature["valid"] and signature["solid_count"] > 0 else "RED",
        "path": str(source), "sha256": sha256_file(source), **signature,
        "scope": "Native CAD validity and geometry only; no physical or manufacturing acceptance",
    }


def _deltas(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, float]:
    bounds = max(abs(x - y) for axis in ("min", "max") for x, y in zip(a["bbox"][axis], b["bbox"][axis]))
    return bounds, abs(a["volume_mm3"] - b["volume_mm3"])


def compare_shapes(
    reference: cq.Shape, actual: cq.Shape, *, linear_tolerance_mm: float = 2e-5,
    volume_tolerance_mm3: float = 1e-4, relative_volume_tolerance: float = 1e-8,
    check_geometry: bool = True,
) -> dict[str, Any]:
    """Compare reloaded geometry using unordered solids and real boolean cuts.

    Bounding boxes and volume alone cannot prove feature placement. By default,
    candidate solids must also have negligible symmetric-difference volume.
    Solid topology counts may change during STEP serialization and are reported,
    rather than used as a substitute for geometric equivalence.
    """
    linear = _tolerance(linear_tolerance_mm, "Linear tolerance")
    absolute = _tolerance(volume_tolerance_mm3, "Volume tolerance")
    relative = _tolerance(relative_volume_tolerance, "Relative volume tolerance")
    expected, observed = shape_signature(reference), shape_signature(actual)
    bounds_delta, volume_delta = _deltas(expected, observed)
    total_limit = max(absolute, abs(expected["volume_mm3"]) * relative)
    failures = []
    if not expected["valid"] or not observed["valid"]:
        failures.append("Invalid native solid geometry")
    if expected["solid_count"] == 0 or expected["solid_count"] != observed["solid_count"]:
        failures.append("Solid inventory differs or is empty")
    if bounds_delta > linear:
        failures.append("World-coordinate bounds differ")
    if volume_delta > total_limit:
        failures.append("Total solid volume differs")
    left, right = reference.Solids(), actual.Solids()
    unused = set(range(len(right)))
    matches = []
    for index, solid in enumerate(left):
        record = expected["solids"][index]
        limit = max(absolute, abs(record["volume_mm3"]) * relative)
        candidates = []
        for j in sorted(unused):
            bd, vd = _deltas(record, observed["solids"][j])
            if bd > linear or vd > limit:
                continue
            difference = None
            if check_geometry:
                try:
                    difference = abs(solid.cut(right[j]).Volume()) + abs(right[j].cut(solid).Volume())
                except Exception as exc:
                    raise BuildError(f"Native STEP comparison failed: {type(exc).__name__}") from exc
                if not math.isfinite(difference) or difference > limit:
                    continue
            candidates.append({"reference_index": index, "actual_index": j, "bbox_max_delta_mm": bd,
                               "volume_delta_mm3": vd, "symmetric_difference_mm3": difference})
        if not candidates:
            failures.append(f"No equivalent reloaded solid for reference index {index}")
            continue
        # Interchangeable coincident solids have no stable-ID meaning here. A
        # registry import uses the stricter match_step_solids() API below.
        match = min(candidates, key=lambda row: (row["symmetric_difference_mm3"] or 0, row["bbox_max_delta_mm"], row["actual_index"]))
        unused.remove(match["actual_index"])
        matches.append(match)
    if unused:
        failures.append("Reload contains unmatched solids")
    return {
        "status": "RED" if failures else "PASS", "reference": expected, "actual": observed,
        "bbox_max_delta_mm": bounds_delta, "volume_delta_mm3": volume_delta,
        "geometry_boolean_checked": check_geometry, "matches": matches, "failures": failures,
        "tolerances": {"linear_mm": linear, "volume_mm3": absolute, "relative_volume": relative},
    }


def verify_step_roundtrip(
    shape: cq.Shape, path: str | Path, *, overwrite: bool = False,
    linear_tolerance_mm: float = 2e-5, volume_tolerance_mm3: float = 1e-4,
    relative_volume_tolerance: float = 1e-8, check_geometry: bool = True,
) -> dict[str, Any]:
    """Export to a temporary STEP, reload and verify before publishing the file.

    The caller controls the destination. Existing artifacts are preserved unless
    overwrite is explicitly enabled, and failed exports never replace them.
    """
    output = Path(path).expanduser().resolve()
    if output.exists() and not overwrite:
        raise BuildError(f"Refusing to overwrite existing STEP artifact: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{output.stem}.", suffix=".step", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        cq.exporters.export(shape, str(temporary), exportType="STEP")
        report = compare_shapes(shape, load_step(temporary), linear_tolerance_mm=linear_tolerance_mm,
                                volume_tolerance_mm3=volume_tolerance_mm3,
                                relative_volume_tolerance=relative_volume_tolerance, check_geometry=check_geometry)
        if report["status"] != "PASS":
            raise BuildError("STEP round-trip verification failed: " + "; ".join(report["failures"]))
        digest = sha256_file(temporary)
        if overwrite:
            os.replace(temporary, output)
        else:
            # Atomic no-clobber creation, including concurrent writers.
            os.link(temporary, output)
            temporary.unlink()
        return {**report, "path": str(output), "sha256": digest}
    except BuildError:
        raise
    except Exception as exc:
        raise BuildError(f"STEP round-trip export failed: {type(exc).__name__}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def match_step_solids(
    path: str | Path, expected: list[dict[str, Any]], *, expected_sha256: str | None = None,
    linear_tolerance_mm: float = 2e-5, volume_tolerance_mm3: float = 1e-4,
    relative_volume_tolerance: float = 1e-8,
) -> dict[str, cq.Solid]:
    """Bind registry IDs to unique STEP solids by declared world bounds/volume.

    Expected records contain ``id``, ``bbox`` (min/max triples) and
    ``volume_mm3``. Ambiguous coincident solids are rejected: import order must
    never silently become a component identity. This is correspondence evidence,
    not proof of matching internal features or physical acceptance.
    """
    linear = _tolerance(linear_tolerance_mm, "Linear tolerance")
    absolute = _tolerance(volume_tolerance_mm3, "Volume tolerance")
    relative = _tolerance(relative_volume_tolerance, "Relative volume tolerance")
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise BuildError(f"STEP file does not exist: {source}")
    if expected_sha256 is not None and sha256_file(source) != expected_sha256:
        raise BuildError("Immutable STEP source hash mismatch")
    shape = load_step(source)
    signature = shape_signature(shape)
    if not signature["valid"] or signature["solid_count"] != len(expected) or not expected:
        raise BuildError("STEP and expected registry have different or invalid solid inventories")
    names = [record.get("id") for record in expected]
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        raise BuildError("Expected registry must contain unique nonempty stable IDs")
    solids = shape.Solids()
    # Check every expected record against the complete inventory. Removing
    # previously matched solids first could conceal an ambiguous source match.
    bindings = {}
    for record in expected:
        try:
            bounds = record["bbox"]
            valid_bounds = all(isinstance(bounds[key], (list, tuple)) and len(bounds[key]) == 3 for key in ("min", "max"))
            numbers = list(bounds["min"]) + list(bounds["max"]) + [record["volume_mm3"]]
            if not valid_bounds or not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in numbers):
                raise ValueError("Nonfinite or incomplete signature")
            if record["volume_mm3"] <= 0 or any(a > b for a, b in zip(bounds["min"], bounds["max"])):
                raise ValueError("Invalid bounds or volume")
        except (KeyError, TypeError, ValueError) as exc:
            raise BuildError(f"Invalid expected STEP signature: {record['id']}") from exc
        limit = max(absolute, abs(record["volume_mm3"]) * relative)
        candidates = [i for i, row in enumerate(signature["solids"])
                      if _deltas(record, row)[0] <= linear and _deltas(record, row)[1] <= limit]
        if len(candidates) != 1 or candidates[0] in bindings.values():
            raise BuildError(f"Non-unique STEP registry correspondence: {record['id']}")
        bindings[record["id"]] = candidates[0]
    return {name: solids[index] for name, index in bindings.items()}
