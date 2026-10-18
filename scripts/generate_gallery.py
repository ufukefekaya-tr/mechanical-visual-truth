#!/usr/bin/env python3
"""Regenerate the public gallery from synthetic contracts using the MVT CLI.

Run with the same Python environment used for MVT. No external projects, vendor
CAD, raster generation services, or machine-specific paths are needed.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import platform
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EXAMPLES = (
    ("fixture-stage", "Two-rail fixture stage", "Coupled carriage + payload motion"),
    ("linear-actuator", "Compact screw actuator", "Guide rods, screw envelope, and carriage"),
    ("instrument-enclosure", "Open instrumentation enclosure", "Shell panels, controls, and internal module"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(*args: str, allowed_statuses: tuple[str, ...] = ("PASS",)) -> dict:
    from mvt.cli.main import main

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = main([*args, "--json"])
    result = json.loads(output.getvalue())
    if code or result.get("status") not in allowed_statuses:
        raise RuntimeError(f"MVT command failed ({code}): {args!r}\n{output.getvalue()}")
    return result


def font(size: int, bold: bool = False):
    from PIL import ImageFont

    # Pillow bundles a scalable default font. No platform-specific font path.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def overview(assets: Path) -> None:
    from PIL import Image, ImageDraw

    canvas = Image.new("RGB", (1920, 740), "#101c29")
    draw = ImageDraw.Draw(canvas)
    draw.text((52, 34), "MECHANICAL VISUAL TRUTH", font=font(34, True), fill="#f5f7fa")
    draw.text((54, 89), "One contract. The same geometry in STEP, proof renders, and sampled motion.", font=font(23), fill="#aebecb")
    for index, (slug, title, subtitle) in enumerate(EXAMPLES):
        x = 42 + index * 626
        draw.rounded_rectangle((x, 155, x + 604, 657), radius=15, fill="#1a2a3a")
        with Image.open(assets / slug / "isometric.png") as source:
            proof = source.convert("RGB").resize((580, 362))
        canvas.paste(proof, (x + 12, 167))
        draw.text((x + 20, 550), title, font=font(24, True), fill="#f4f6f8")
        draw.text((x + 20, 591), subtitle, font=font(17), fill="#b0c3cf")
        draw.text((x + 20, 621), "SYNTHETIC EXAMPLE  /  CAD-DERIVED EVIDENCE", font=font(14), fill="#70d4ba")
    draw.text((54, 695), "Actual MVT CAD renders  |  Original public examples  |  No customer CAD  |  Concept geometry, not manufacturing drawings", font=font(17), fill="#99adbc")
    canvas.save(assets / "gallery-overview.png", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-animation", action="store_true", help="omit motion generation for a faster static preview")
    args = parser.parse_args()
    assets = ROOT / "docs" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="mvt-public-gallery-") as temporary:
        for slug, title, subtitle in EXAMPLES:
            project = Path(temporary) / slug
            shutil.copytree(ROOT / "examples" / slug, project, ignore=shutil.ignore_patterns("runs", "__pycache__"))
            command("contract", "validate", str(project))
            build = command("build", str(project))
            command("render", str(project), "--set", "proofs")
            audit = command("audit", str(project), allowed_statuses=("PASS", "YELLOW"))
            destination = assets / slug
            destination.mkdir(parents=True, exist_ok=True)
            run = project / "runs" / build["run_id"]
            shutil.copy2(run / f"{slug}.step", destination / f"{slug}.step")
            import cadquery as cq
            from mvt.contracts import load_contract
            from mvt.drawings import export_step_drawing
            from mvt.geometry.model import build_model
            from mvt.step_io import compare_shapes, load_step

            source_shape = cq.Compound.makeCompound([item.shape for item in build_model(load_contract(project))])
            step_verification = compare_shapes(source_shape, load_step(destination / f"{slug}.step"))
            if step_verification["status"] != "PASS":
                raise RuntimeError(f"Public STEP reload verification failed: {slug}")
            (destination / "step-verification.json").write_text(json.dumps(step_verification, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            export_step_drawing(destination / f"{slug}.step", destination / "drawing.svg", title=title, overwrite=True)
            for view in ("isometric", "top", "front"):
                shutil.copy2(run / "proofs" / f"{view}.png", destination / f"{view}.png")
            # An audit is portable evidence. Runtime run identifiers and paths are
            # intentionally omitted from the public provenance record.
            portable_audit = {key: value for key, value in audit.items() if key != "run_id"}
            (destination / "audit.json").write_text(json.dumps(portable_audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            record = {
                "id": slug, "title": title, "source": "synthetic-public-example",
                "contract": f"examples/{slug}/contract.yaml", "contract_hash": build["contract_hash"],
                "model_hash": build["model_hash"], "audit_status": audit["status"],
                "entity_count": audit["entity_count"], "views": ["isometric", "top", "front"],
                "notes": subtitle, "drawing": "drawing.svg", "step_verification_status": step_verification["status"],
                "geometry_status": audit.get("geometry_status", audit["status"]),
                "physical_status": audit.get("physical_status", "NOT_QUALIFIED"),
                "safety_status": audit.get("safety_status", "NOT_QUALIFIED"),
            }
            if slug == "fixture-stage" and not args.skip_animation:
                animation = command("animate", "build", str(project), "--sequence", "shuttle")
                motion_source = run / "animations" / "shuttle"
                for filename in ("shuttle.mp4", "shuttle_preview.gif", "shuttle_contact_sheet.jpg"):
                    shutil.copy2(motion_source / filename, destination / filename)
                portable_animation = {key: value for key, value in animation.items() if key not in {"artifacts", "status"}}
                portable_animation["artifacts"] = [
                    {"path": Path(item["path"]).name, "sha256": item["sha256"]}
                    for item in animation["artifacts"]
                ]
                (destination / "animation-manifest.json").write_text(json.dumps(portable_animation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                record["animation"] = "docs/assets/fixture-stage/shuttle_preview.gif"
                record["motion_audit_status"] = animation["motion_audit"]["status"]
            records.append(record)
            print(f"PASS {slug}: STEP reload, native SVG, three proof renders, declared audit gates", flush=True)
    overview(assets)
    import cadquery
    import vtk
    from mvt import __version__

    manifest = {
        "schema_version": 1,
        "provenance": {
            "source": "synthetic-public-examples",
            "geometry": "Original primitive geometry declared in the bundled example contracts.",
            "rendering": "MVT proof renderer; no image generation or geometry retouching.",
            "scope": "Count, envelope, and explicitly declared clearance/motion constraints only; not manufacturing certification.",
            "reproduce": "python scripts/generate_gallery.py",
        },
        "tools": {"mvt": __version__, "python": platform.python_version(), "cadquery": cadquery.__version__, "vtk": vtk.vtkVersion.GetVTKVersion()},
        "examples": records,
        "artifacts": [{"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}
                      for path in sorted(assets.rglob("*")) if path.is_file() and path.name != "gallery-manifest.json"],
    }
    (assets / "gallery-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
