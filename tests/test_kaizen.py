from __future__ import annotations

import json
import shutil

from mvt.kaizen.engine import evaluate_lesson, promote_lessons, rollback_promotion


def lesson(score=85):
    values = {"severity": 25, "evidence_quality": 25, "reproducibility": 20, "independent_recurrence": 10, "generality": 5, "regression_strength": 0}
    if score < 85:
        values["severity"] -= 85 - score
    return {
        "id": f"lesson-{score}", "rule": f"Audit lesson {score} before presentation.", "scope": "mechanical",
        "scores": values, "evidence": [{"kind": "audit", "hash": "abc"}],
        "regression": {"failed_before": True, "passes_after": True, "baseline_regression": False}, "status": "CANDIDATE",
    }


def high_lesson(score):
    result = lesson(85)
    result["id"] = f"lesson-{score}"
    result["rule"] = f"Preserve deterministic gate {score}."
    result["scores"] = {
        "severity": 25, "evidence_quality": 25, "reproducibility": 20,
        "independent_recurrence": 7 if score == 92 else 10,
        "generality": 10, "regression_strength": 5,
    }
    return result


def test_below_85_stays_candidate(repo):
    result = evaluate_lesson(repo, lesson(84))
    assert not result["eligible"]


def test_85_targets_shield_skill(repo):
    result = evaluate_lesson(repo, lesson(85))
    assert result["eligible"]
    assert result["target_layer"] == "shield_skill"


def test_92_and_95_target_expected_layers(repo):
    assert evaluate_lesson(repo, high_lesson(92))["target_layer"] == "agents"
    assert evaluate_lesson(repo, high_lesson(95))["target_layer"] == "system_prompt"


def test_kill_switch_blocks_activation(tmp_path, repo):
    local = tmp_path / "repo"
    (local / "governance" / "promotions" / "candidates").mkdir(parents=True)
    (local / "governance" / "AUTO_PROMOTION_DISABLED").write_text("")
    result = promote_lessons(local, [])
    assert result["status"] == "DISABLED"


def test_promotion_materializes_and_rolls_back(tmp_path, repo):
    local = tmp_path / "repo"
    for directory in (
        "schemas", "governance/promotions/candidates", "governance/promotions/versions",
        "governance/rollback", "governance/evals", "governance/templates", "governance/versions",
        "governance/prompts", "skills/mvt-governance/references",
    ):
        (local / directory).mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo / "schemas" / "lesson.schema.json", local / "schemas" / "lesson.schema.json")
    shutil.copy2(repo / "governance" / "templates" / "AGENTS.base.md", local / "governance" / "templates" / "AGENTS.base.md")
    candidate = local / "governance" / "promotions" / "candidates" / "lesson-95.json"
    candidate.write_text(json.dumps(high_lesson(95)), encoding="utf-8")
    result = promote_lessons(local, [candidate])
    assert result["status"] == "PASS"
    assert "Preserve deterministic gate 95" in (local / "AGENTS.md").read_text()
    assert (local / "governance" / "versions" / "AGENTS.v1.md").exists()
    rolled = rollback_promotion(local, result["promotion_id"])
    assert rolled["status"] == "PASS"
    assert "Preserve deterministic gate 95" not in (local / "AGENTS.md").read_text()
