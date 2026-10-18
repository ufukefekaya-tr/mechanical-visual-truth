from __future__ import annotations

from mvt.registry.skills import skill_action
from mvt.registry.tools import validate_registry


def test_tool_registry_valid(repo):
    assert validate_registry(repo)["status"] == "PASS"


def test_skill_install_is_idempotent(repo, tmp_path):
    first = skill_action(repo, "install", tmp_path / "skills")
    second = skill_action(repo, "sync", tmp_path / "skills")
    assert first["status"] == second["status"] == "PASS"
    assert (tmp_path / "skills" / "mechanical-visual-truth" / "SKILL.md").exists()
    skill_action(repo, "uninstall", tmp_path / "skills")
    assert not (tmp_path / "skills" / "mechanical-visual-truth").exists()
