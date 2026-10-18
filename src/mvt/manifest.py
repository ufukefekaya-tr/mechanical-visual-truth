from __future__ import annotations

import platform
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mvt.contracts import Contract
from mvt.util import atomic_json, owned_path, read_json, sha256_file, utc_now


@dataclass
class Run:
    directory: Path
    manifest_path: Path
    data: dict[str, Any]

    def output(self, *parts: str) -> Path:
        return owned_path(self.directory, *parts)

    def add_artifact(self, path: Path, kind: str, **metadata: Any) -> None:
        if not path.resolve().is_relative_to(self.directory.resolve()):
            raise ValueError("Artifact path escapes its run")
        self.data["artifacts"] = [item for item in self.data["artifacts"] if item.get("path") != str(path)]
        self.data["artifacts"].append({"path": str(path), "relative_path": path.resolve().relative_to(self.directory.resolve()).as_posix(), "kind": kind, "sha256": sha256_file(path), **metadata})
        self.save()

    def save(self) -> None:
        atomic_json(self.manifest_path, self.data)


def runs_dir(contract: Contract) -> Path:
    return owned_path(contract.project_dir, "runs")


def create_run(contract: Contract, parent_run_id: str | None = None) -> Run:
    run_id = f"{utc_now()[:10].replace('-', '')}-{uuid.uuid4().hex[:10]}"
    directory = runs_dir(contract) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    data = {
        "run_id": run_id, "created_at": utc_now(), "project_id": contract.project_id,
        "contract_hash": contract.hash, "model_hash": None, "status": "IN_PROGRESS",
        "parent_run_id": parent_run_id, "tools": {"python": platform.python_version()},
        "artifacts": [], "audit": {},
    }
    run = Run(directory, directory / "run-manifest.json", data)
    run.save()
    atomic_json(runs_dir(contract) / "latest.json", {"run_id": run_id})
    return run


def latest_run(contract: Contract) -> Run | None:
    root = runs_dir(contract).resolve()
    if not root.is_relative_to(contract.project_dir.resolve()):
        raise ValueError("Run directory escapes its project")
    pointer_path = root / "latest.json"
    if not pointer_path.resolve().is_relative_to(root):
        raise ValueError("Run pointer escapes its project")
    pointer = read_json(pointer_path)
    if not pointer:
        return None
    identifier = pointer.get("run_id", "") if isinstance(pointer, dict) else ""
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9]{8}-[0-9a-f]{10}", identifier):
        raise ValueError("Invalid run identifier")
    path = (root / identifier / "run-manifest.json").resolve()
    if not path.is_relative_to(root):
        raise ValueError("Run manifest escapes its project")
    if not path.exists():
        return None
    data = read_json(path)
    if not isinstance(data, dict) or data.get("project_id") != contract.project_id or data.get("run_id") != identifier:
        raise ValueError("Run manifest identity mismatch")
    for artifact in data.get("artifacts", []):
        if artifact.get("relative_path"):
            artifact["path"] = str(owned_path(path.parent, artifact["relative_path"]))
        elif not Path(artifact.get("path", "")).resolve().is_relative_to(path.parent):
            raise ValueError("Artifact escapes its run")
    return Run(path.parent, path, data)
