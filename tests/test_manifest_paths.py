from __future__ import annotations

import json
import shutil

import pytest

from mvt.contracts import load_contract
from mvt.manifest import create_run, latest_run


def test_latest_run_survives_project_move(tmp_path, repo):
    project = tmp_path / "first"
    shutil.copytree(repo / "examples" / "fixture-stage", project)
    contract = load_contract(project)
    run = create_run(contract)
    proof = run.directory / "proof.png"
    proof.write_bytes(b"synthetic-proof")
    run.add_artifact(proof, "proof-render")
    destination = tmp_path / "moved"
    project.rename(destination)
    moved = latest_run(load_contract(destination))
    assert moved is not None
    assert moved.data["run_id"] == run.data["run_id"]
    assert moved.directory.is_relative_to(destination)
    assert moved.data["artifacts"][0]["path"] == str(moved.directory / "proof.png")


def test_run_pointer_cannot_redirect_to_external_json(tmp_path, repo):
    project = tmp_path / "project"
    shutil.copytree(repo / "examples" / "fixture-stage", project)
    contract = load_contract(project)
    run = create_run(contract)
    (project / "runs" / "latest.json").write_text(json.dumps({
        "run_id": "../../private", "path": str(tmp_path / "private.json")}))
    with pytest.raises(ValueError, match="identifier"):
        latest_run(contract)


def test_run_manifest_symlink_escape_is_rejected(tmp_path, repo):
    project = tmp_path / "project"
    shutil.copytree(repo / "examples" / "fixture-stage", project)
    contract = load_contract(project)
    run = create_run(contract)
    run.manifest_path.unlink()
    external = tmp_path / "private.json"
    external.write_text('{"not": "a run"}')
    run.manifest_path.symlink_to(external)
    with pytest.raises(ValueError, match="escapes"):
        latest_run(contract)


def test_run_creation_rejects_symlinked_output_root(tmp_path, repo):
    project = tmp_path / "project"
    shutil.copytree(repo / "examples" / "fixture-stage", project)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "runs").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        create_run(load_contract(project))
    assert list(outside.iterdir()) == []
