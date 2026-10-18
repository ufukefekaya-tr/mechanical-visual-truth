"""Project-independent operations shared by the CLI and the MCP worker.

Copyright 2026 Ufuk Efe Kaya
SPDX-License-Identifier: MIT OR Apache-2.0
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from mvt import __version__
from mvt.acceptance import verify_accepted
from mvt.auditing import audit_contract_model
from mvt.contracts import load_contract
from mvt.errors import MVTError
from mvt.geometry.model import build_model, export_step, model_semantic_hash
from mvt.manifest import create_run, latest_run
from mvt.rendering.vtk_renderer import render_png
from mvt.util import atomic_json, resource_root


def templates() -> list[str]:
    return sorted(p.parent.name for p in (resource_root() / "examples").glob("*/contract.yaml"))


def initialize_project(target: str | Path, template: str = "fixture-stage") -> dict[str, Any]:
    if template not in templates():
        raise ValueError(f"Unknown template {template!r}; choose from {templates()}")
    target = Path(target).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Project is not empty: {target}")
    source = resource_root() / "examples" / template
    data = yaml.safe_load((source / "contract.yaml").read_text(encoding="utf-8"))
    data["project"]["id"] = target.name
    data["project"]["title"] = target.name.replace("-", " ").title()
    data["project"]["revision"] = "r0"
    data["project"]["provenance"] = [{"kind": "synthetic-public-template", "template": template}]
    # Validate before touching the target contract. A slug is a contract ID.
    from mvt.contracts.loader import validate_contract
    errors = validate_contract(data)
    if errors:
        raise ValueError("Invalid project name or template: " + "; ".join(errors))
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_file() and item.suffix in {".yaml", ".yml", ".md"} and item.name != "contract.yaml":
            shutil.copy2(item, target / item.name)
    path = target / "contract.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return {"status": "PASS", "project": str(target), "template": template}


def build_project(project: str | Path, *, write_step: bool = True) -> dict[str, Any]:
    contract = load_contract(project)
    solids = build_model(contract)
    run = create_run(contract)
    import cadquery as cq
    import vtk
    run.data["tools"].update({"mvt": __version__, "cadquery": cq.__version__, "vtk": vtk.vtkVersion.GetVTKVersion()})
    run.data["model_hash"] = model_semantic_hash(contract, solids)
    run.data["step_exported"] = write_step
    if write_step:
        from mvt.step_io import compare_shapes, load_step
        step = run.output(f"{contract.project_id}.step")
        export_step(solids, step)
        verification = compare_shapes(cq.Compound.makeCompound([item.shape for item in solids]), load_step(step))
        if verification["status"] != "PASS":
            run.data["status"] = "RED"
            run.data["step_verification"] = verification
            run.save()
            raise MVTError("STEP reload differs from the source geometry")
        run.data["step_verification"] = verification
        run.add_artifact(step, "step", semantic_model_hash=run.data["model_hash"])
        verification_path = run.output("step-verification.json")
        atomic_json(verification_path, verification)
        run.add_artifact(verification_path, "step-verification")
    run.data["status"] = "PASS"
    run.save()
    return {"status": "PASS", "run_id": run.data["run_id"], "contract_hash": contract.hash,
            "model_hash": run.data["model_hash"], "step_exported": write_step,
            "step_verification": run.data.get("step_verification"), "artifacts": run.data["artifacts"]}


def current_build(project: str | Path):
    contract = load_contract(project)
    run = latest_run(contract)
    if not run or run.data.get("contract_hash") != contract.hash or not run.data.get("model_hash"):
        raise MVTError("No current build; run mvt build first")
    solids = build_model(contract)
    if model_semantic_hash(contract, solids) != run.data["model_hash"]:
        raise MVTError("The source geometry differs from the current build")
    return contract, run, solids


def render_project(project: str | Path, *, camera_id: str | None = None) -> dict[str, Any]:
    contract, run, solids = current_build(project)
    ids = [camera_id] if camera_id else [camera["id"] for camera in contract.data["cameras"]]
    artifacts = []
    for identifier in ids:
        camera = contract.camera(identifier)
        path = run.output("proofs", f"{identifier}.png")
        render_png(solids, camera, path, watermark=f"MVT CAD PROOF | {identifier} | {contract.hash[:12]}")
        run.add_artifact(path, "proof-render", camera=identifier, projection=camera["projection"], model_hash=run.data["model_hash"])
        artifacts.append(run.data["artifacts"][-1])
    return {"status": "PASS", "run_id": run.data["run_id"], "contract_hash": contract.hash,
            "model_hash": run.data["model_hash"], "artifacts": artifacts}


def audit_project(project: str | Path) -> dict[str, Any]:
    contract, run, solids = current_build(project)
    audit = audit_contract_model(contract, solids)
    accepted = verify_accepted(contract)
    if any(item["status"] == "RED" for item in accepted):
        audit["findings"].extend({"gate": "accepted-hash", **item} for item in accepted)
        audit["status"] = "RED"
    run.data["audit"] = audit
    run.data["status"] = audit["status"]
    audit_path = run.output("audit.json")
    atomic_json(audit_path, audit)
    run.add_artifact(audit_path, "audit")
    run.save()
    return audit | {"run_id": run.data["run_id"], "model_hash": run.data["model_hash"]}
