"""Workspace-scoped stdio MCP interface; no shell or arbitrary Python tool.

Copyright 2026 Ufuk Efe Kaya
SPDX-License-Identifier: MIT OR Apache-2.0
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from functools import wraps
from pathlib import Path
from typing import Any

import yaml
from mcp.server import MCPServer
from mcp.server.mcpserver import Image as MCPImage
from mcp.types import ToolAnnotations

from mvt import __version__
from mvt.contracts import load_contract
from mvt.contracts.loader import validate_contract
from mvt.operations import initialize_project, templates
from mvt.util import sha256_data, sha256_file

MAX_CONTRACT_BYTES = 1024 * 1024
MAX_ENTITIES = 1000
MAX_RENDER_PIXELS = 4096 * 4096
MAX_ANIMATION_FRAMES = 300
MAX_SOURCE_BYTES = 128 * 1024 * 1024


class Workspace:
    """Constrain all tool paths and serialized CAD worker processes to one root."""

    def __init__(self, root: str | Path, timeout: int = 180):
        self.root = Path(root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Workspace must be an existing directory")
        self.timeout = timeout
        self.lock = threading.RLock()

    def path(self, value: str, *, must_exist: bool = True) -> Path:
        candidate = Path(value)
        if not value or candidate.is_absolute() or any(p in {"..", ".git", ".env"} for p in candidate.parts):
            raise ValueError("Use a workspace-relative path without parent traversal")
        result = (self.root / candidate).resolve()
        if not result.is_relative_to(self.root):
            raise ValueError("Path escapes the configured workspace")
        if must_exist and not result.exists():
            raise FileNotFoundError(value)
        return result

    def contract(self, project: str):
        path = self.path(project)
        file = path if path.suffix in {".yaml", ".yml"} else path / "contract.yaml"
        file = file.resolve(strict=True)
        if not file.is_relative_to(self.root) or file.stat().st_size > MAX_CONTRACT_BYTES:
            raise ValueError("Contract is outside the workspace or exceeds 1 MiB")
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Contract root must be a mapping")
        if len(data.get("entities", [])) > MAX_ENTITIES:
            raise ValueError(f"MCP limit: {MAX_ENTITIES} entities")
        for camera in data.get("cameras", []):
            size = camera.get("size", []) if isinstance(camera, dict) else []
            if len(size) == 2 and all(isinstance(x, (int, float)) for x in size) and size[0] * size[1] > MAX_RENDER_PIXELS:
                raise ValueError("MCP render resolution limit exceeded")
        from mvt.contracts.loader import source_path
        for source in data.get("sources", []):
            if not isinstance(source, dict):
                continue
            for name, limit in (("path", MAX_SOURCE_BYTES), ("sidecar_path", MAX_CONTRACT_BYTES)):
                if name in source and source_path(file.parent, source[name]).stat().st_size > limit:
                    raise ValueError("MCP source file size limit exceeded")
        contract = load_contract(file)
        return contract

    def step(self, path: str) -> Path:
        result = self.path(path)
        if not result.is_file() or result.suffix.lower() not in {".step", ".stp"}:
            raise ValueError("Choose a STEP file")
        if result.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("MCP STEP file limit is 128 MiB")
        return result

    def portable(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self.portable(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.portable(v) for v in value]
        if isinstance(value, str):
            return value.replace(str(self.root) + os.sep, "")
        return value

    def command(self, *arguments: str) -> dict[str, Any]:
        """Run a bounded, serialized CLI worker; keep stdout exclusively JSON."""
        env = dict(os.environ, MVT_WORKSPACE=str(self.root))
        with self.lock:
            process = subprocess.Popen(
                [sys.executable, "-I", "-m", "mvt.cli.main", *arguments, "--json"],
                cwd=self.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, start_new_session=(os.name == "posix"),
            )
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.communicate()
                raise TimeoutError(f"CAD worker exceeded {self.timeout} seconds") from None
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            # Native CAD diagnostics are not protocol content and may expose paths.
            raise RuntimeError("CAD worker did not return a valid MVT response") from None
        if not isinstance(result, dict):
            raise RuntimeError("Unexpected CAD worker result")
        return self.portable(result)


def build_server(workspace: str | Path, *, timeout: int = 180) -> MCPServer:
    ws = Workspace(workspace, timeout)
    server = MCPServer(
        "Mechanical Visual Truth", version=__version__,
        instructions=("Use workspace-relative paths. Validate a geometry contract, build, render and audit in order. "
                      "Outputs are CAD evidence only at their declared validation tier; physical/safety approval is separate. "
                      "There is no shell, arbitrary Python execution, publication or automatic acceptance tool."),
    )
    read = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
    write = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

    def serialized(function):
        @wraps(function)
        def guarded(*args, **kwargs):
            # Keep resource checks and worker execution in one critical section.
            with ws.lock:
                return function(*args, **kwargs)
        return guarded

    @server.tool(annotations=read)
    @serialized
    def mvt_templates() -> dict[str, Any]:
        """List bundled, synthetic project templates and server resource limits."""
        return {"templates": templates(), "version": __version__, "limits": {
            "entities": MAX_ENTITIES, "contract_bytes": MAX_CONTRACT_BYTES,
            "render_pixels": MAX_RENDER_PIXELS, "animation_frames": MAX_ANIMATION_FRAMES,
            "step_file_bytes": MAX_SOURCE_BYTES,
            "worker_timeout_seconds": ws.timeout}}

    @server.tool(annotations=write)
    @serialized
    def mvt_project_create(project: str, template: str = "fixture-stage") -> dict[str, Any]:
        """Create a new project from a public template; never overwrite an existing project."""
        with ws.lock:
            return ws.portable(initialize_project(ws.path(project, must_exist=False), template))

    @server.tool(annotations=read)
    @serialized
    def mvt_contract_read(project: str) -> dict[str, Any]:
        """Read a validated project contract and its canonical hash."""
        with ws.lock:
            contract = ws.contract(project)
            return {"contract": contract.data, "contract_hash": contract.hash}

    @server.tool(annotations=write)
    @serialized
    def mvt_contract_write(project: str, contract: dict[str, Any], expected_hash: str | None = None) -> dict[str, Any]:
        """Save validated declarative geometry; an existing contract requires its current hash."""
        encoded = yaml.safe_dump(contract, sort_keys=False)
        if len(encoded.encode()) > MAX_CONTRACT_BYTES or len(contract.get("entities", [])) > MAX_ENTITIES:
            raise ValueError("Contract exceeds MCP limits")
        errors = validate_contract(contract)
        if errors:
            raise ValueError("Invalid contract: " + "; ".join(errors[:10]))
        with ws.lock:
            target = ws.path(project, must_exist=False)
            if target.suffix in {".yaml", ".yml"}:
                path = target
            else:
                path = target / "contract.yaml"
            if path.exists():
                current = ws.contract(project)
                if expected_hash != current.hash:
                    raise ValueError("Existing contract hash required; read the latest contract first")
            elif expected_hash is not None:
                raise ValueError("Cannot compare a hash for a missing contract")
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".contract-", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(encoded)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {"status": "PASS", "contract_hash": sha256_data(contract)}

    @server.tool(annotations=read)
    @serialized
    def mvt_contract_validate(project: str) -> dict[str, Any]:
        """Validate the geometry, references and locked source hashes."""
        ws.contract(project)
        return ws.command("contract", "validate", str(ws.path(project)))

    @server.tool(annotations=write)
    @serialized
    def mvt_model_build(project: str, export_step: bool = True) -> dict[str, Any]:
        """Build actual B-rep geometry; optionally export and independently reload STEP."""
        ws.contract(project)
        args = ["build", str(ws.path(project))]
        if not export_step:
            args.append("--no-step")
        return ws.command(*args)

    @server.tool(annotations=write)
    @serialized
    def mvt_render_proofs(project: str, camera: str | None = None) -> dict[str, Any]:
        """Render the current contract geometry using a declared proof camera, or all cameras."""
        contract = ws.contract(project)
        args = ["render", str(ws.path(project))]
        if camera is not None:
            contract.camera(camera)
            args.extend(["--camera", camera])
        return ws.command(*args)

    @server.tool(annotations=write)
    @serialized
    def mvt_model_audit(project: str) -> dict[str, Any]:
        """Check declared counts, geometry, clearance and accepted artifact integrity."""
        ws.contract(project)
        return ws.command("audit", str(ws.path(project)))

    @server.tool(annotations=write)
    @serialized
    def mvt_animation_build(project: str, sequence: str) -> dict[str, Any]:
        """Build and audit a bounded deterministic animation from declared keyframes."""
        contract = ws.contract(project)
        animation = contract.animation(sequence)
        if animation["truth_mode"] != "deterministic_cad":
            raise ValueError("MCP animation requires deterministic_cad")
        if animation["fps"] * animation["duration"] + 1 > MAX_ANIMATION_FRAMES:
            raise ValueError("MCP animation frame limit exceeded")
        return ws.command("animate", "build", str(ws.path(project)), "--sequence", sequence)

    @server.tool(annotations=read)
    @serialized
    def mvt_step_inspect(path: str) -> dict[str, Any]:
        """Reload a STEP file and inspect real solids, B-rep validity, volume and bounds."""
        return ws.command("step", "inspect", str(ws.step(path)))

    @server.tool(annotations=write)
    @serialized
    def mvt_step_drawing(path: str, output: str, title: str = "Mechanical part") -> dict[str, Any]:
        """Create a native SVG orthographic drawing from STEP; refuse overwriting a file."""
        source = ws.step(path)
        destination = ws.path(output, must_exist=False)
        if destination.suffix.lower() != ".svg" or destination.exists():
            raise ValueError("Choose a new .svg output path")
        return ws.command("step", "drawing", str(source), str(destination), "--title", title)

    @server.tool(annotations=read)
    @serialized
    def mvt_artifacts(project: str) -> dict[str, Any]:
        """List current build artifacts and content hashes without accepting any output."""
        from mvt.manifest import latest_run
        contract = ws.contract(project)
        run = latest_run(contract)
        if run is None:
            return {"status": "EMPTY", "artifacts": []}
        return ws.portable({"status": run.data["status"], "run_id": run.data["run_id"],
                            "contract_hash": run.data["contract_hash"], "artifacts": run.data["artifacts"]})

    @server.tool(annotations=read, structured_output=False)
    @serialized
    def mvt_artifact_preview(project: str, path: str) -> MCPImage:
        """Return a hash-verified PNG/JPEG proof from the current run as an MCP image."""
        from mvt.manifest import latest_run
        from PIL import Image
        with ws.lock:
            contract = ws.contract(project)
            run = latest_run(contract)
            if run is None or run.data["contract_hash"] != contract.hash:
                raise ValueError("No current run")
            artifact = ws.path(path)
            if artifact.suffix.lower() not in {".png", ".jpg", ".jpeg"} or artifact.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Preview must be a PNG/JPEG of at most 8 MiB")
            entry = next((a for a in run.data["artifacts"] if Path(a["path"]).resolve() == artifact), None)
            if entry is None or not artifact.is_relative_to(run.directory.resolve()) or sha256_file(artifact) != entry["sha256"]:
                raise ValueError("Artifact is not a verified member of the current run")
            with Image.open(artifact) as image:
                if image.width * image.height > MAX_RENDER_PIXELS:
                    raise ValueError("Preview resolution limit exceeded")
                image.verify()
            return MCPImage(path=artifact)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Existing directory exposed to this local MCP server")
    parser.add_argument("--timeout", type=int, default=180, help="Maximum seconds per isolated CAD operation")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 1800:
        parser.error("--timeout must be between 1 and 1800 seconds")
    build_server(args.workspace, timeout=args.timeout).run(transport="stdio")


if __name__ == "__main__":
    main()
