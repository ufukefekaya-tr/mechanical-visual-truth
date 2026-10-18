from __future__ import annotations

from mvt.cli.main import main


def test_workspace_init_copies_only_templates_and_refuses_existing(tmp_path):
    workspace = tmp_path / "workspace"
    assert main(["workspace", "init", str(workspace), "--json"]) == 0
    assert (workspace / "schemas" / "geometry-contract.schema.json").is_file()
    assert (workspace / "governance" / "AUTO_PROMOTION_DISABLED").is_file()
    assert not (workspace / "governance" / "evals").exists()
    assert not (workspace / "governance" / "prompts" / "current.md").exists()
    assert main(["workspace", "init", str(workspace), "--json"]) == 2
