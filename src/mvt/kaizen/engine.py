from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from mvt.errors import GovernanceError
from mvt.util import atomic_json, read_json, sha256_data, utc_now


SCORE_KEYS = {
    "severity": 25, "evidence_quality": 25, "reproducibility": 20,
    "independent_recurrence": 15, "generality": 10, "regression_strength": 5,
}


def score_lesson(lesson: dict[str, Any]) -> int:
    scores = lesson["scores"]
    for key, maximum in SCORE_KEYS.items():
        value = scores.get(key)
        if not isinstance(value, int) or not 0 <= value <= maximum:
            raise GovernanceError(f"Invalid {key} score")
    return sum(scores[key] for key in SCORE_KEYS)


def evaluate_lesson(repo: Path, lesson: dict[str, Any]) -> dict[str, Any]:
    schema = json.loads((repo / "schemas" / "lesson.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(lesson))
    total = score_lesson(lesson)
    reasons: list[str] = [error.message for error in errors]
    regression = lesson.get("regression", {})
    if not regression.get("failed_before") or not regression.get("passes_after"):
        reasons.append("missing before-fail/after-pass regression")
    if regression.get("baseline_regression"):
        reasons.append("baseline regression")
    if not lesson.get("evidence"):
        reasons.append("missing evidence")
    if re.search(r"(?i)(password|private key|api[_-]?key|\bsk-)", json.dumps(lesson)):
        reasons.append("secret/PII scan failed")
    if total < 85:
        reasons.append("score below 85")
    layer = None
    if not reasons:
        layer = "shield_skill"
        recurrence = lesson["scores"]["independent_recurrence"]
        critical = bool(lesson.get("critical_deterministic"))
        if total >= 92 and (recurrence >= 2 or critical):
            layer = "agents"
        if total >= 95 and (recurrence >= 3 or critical):
            layer = "system_prompt"
    result = {"lesson_id": lesson["id"], "total": total, "eligible": not reasons, "target_layer": layer, "reasons": reasons}
    evaluations = repo / "governance" / "evals"
    evaluations.mkdir(exist_ok=True)
    atomic_json(evaluations / f"{lesson['id']}.json", result)
    return result


def _current(repo: Path) -> dict[str, Any]:
    return read_json(repo / "governance" / "promotions" / "current.json", {
        "version": 0, "active_rules": [], "skill_rules": [], "agents_rules": [], "prompt_rules": [], "soak": {},
    })


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _materialize(repo: Path, state: dict[str, Any]) -> None:
    """Compile versioned repo-local layers from the active promotion pointer."""
    version = int(state.get("version", 0))
    agents_base = (repo / "governance" / "templates" / "AGENTS.base.md").read_text(encoding="utf-8").rstrip()
    agents_rules = state.get("agents_rules", [])
    agents_text = agents_base + "\n"
    if agents_rules:
        agents_text += "\n## Auto-promoted rules\n\n" + "\n".join(f"- {rule}" for rule in agents_rules) + "\n"
    agents_version = repo / "governance" / "versions" / f"AGENTS.v{version}.md"
    _atomic_text(agents_version, agents_text)
    _atomic_text(repo / "AGENTS.md", agents_text)

    skill_rules = state.get("skill_rules", [])
    skill_text = "# Auto-promoted rules\n\n" + ("\n".join(f"- {rule}" for rule in skill_rules) if skill_rules else "No promoted rules are active.") + "\n"
    skill_version = repo / "governance" / "versions" / f"skill-rules.v{version}.md"
    _atomic_text(skill_version, skill_text)
    _atomic_text(repo / "skills" / "mvt-governance" / "references" / "promoted-rules.md", skill_text)

    if state.get("prompt_rules") and (repo / "governance" / "prompts" / "current.md").exists():
        from mvt.governance.prompt import build_prompt

        build_prompt(repo)


def promote_lessons(repo: Path, lesson_paths: list[Path] | None = None) -> dict[str, Any]:
    if (repo / "governance" / "AUTO_PROMOTION_DISABLED").exists():
        return {"status": "DISABLED", "reason": "kill-switch active", "promoted": []}
    lesson_paths = lesson_paths or sorted((repo / "governance" / "promotions" / "candidates").glob("*.json"))
    previous = _current(repo)
    state = json.loads(json.dumps(previous))
    promoted: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    existing = set(state["active_rules"])
    for path in lesson_paths:
        lesson = read_json(path)
        result = evaluate_lesson(repo, lesson)
        rule = lesson["rule"].strip()
        if not result["eligible"]:
            quarantined.append({"id": lesson["id"], "reasons": result["reasons"]})
            continue
        if rule in existing:
            quarantined.append({"id": lesson["id"], "reasons": ["duplicate rule"]})
            continue
        inverse = re.sub(r"(?i)^always ", "never ", rule)
        if inverse in existing:
            quarantined.append({"id": lesson["id"], "reasons": ["conflicting rule"]})
            continue
        state["active_rules"].append(rule)
        state["skill_rules"].append(rule)
        if result["target_layer"] in {"agents", "system_prompt"}:
            state["agents_rules"].append(rule)
        if result["target_layer"] == "system_prompt":
            state["prompt_rules"].append(rule)
        state["soak"][lesson["id"]] = {"remaining_runs": 5, "status": "SOAKING"}
        existing.add(rule)
        promoted.append({"id": lesson["id"], "rule": rule, "target_layer": result["target_layer"], "score": result["total"]})
    if not promoted:
        return {"status": "NO_CHANGE", "promoted": [], "quarantined": quarantined}
    promotion_id = f"promotion-{utc_now().replace(':', '').replace('+00:00', 'Z')}-{uuid.uuid4().hex[:8]}"
    state["version"] = int(previous.get("version", 0)) + 1
    state["promotion_id"] = promotion_id
    state["previous_version"] = previous.get("version", 0)
    state["activated_at"] = utc_now()
    versions = repo / "governance" / "promotions" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    atomic_json(versions / f"v{state['version']}.json", state)
    atomic_json(repo / "governance" / "rollback" / f"{promotion_id}.json", previous)
    atomic_json(repo / "governance" / "promotions" / "current.json", state)
    _materialize(repo, state)
    ledger_path = repo / "governance" / "promotions" / "ledger.jsonl"
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"promotion_id": promotion_id, "at": utc_now(), "promoted": promoted, "quarantined": quarantined, "state_hash": sha256_data(state)}) + "\n")
    return {"status": "PASS", "promotion_id": promotion_id, "promoted": promoted, "quarantined": quarantined}


def rollback_promotion(repo: Path, promotion_id: str, reason: str = "manual rollback") -> dict[str, Any]:
    rollback = repo / "governance" / "rollback" / f"{promotion_id}.json"
    if not rollback.exists():
        raise GovernanceError(f"Unknown promotion: {promotion_id}")
    previous = read_json(rollback)
    atomic_json(repo / "governance" / "promotions" / "current.json", previous)
    _materialize(repo, previous)
    with (repo / "governance" / "promotions" / "ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"promotion_id": promotion_id, "at": utc_now(), "action": "ROLLBACK", "reason": reason}) + "\n")
    return {"status": "PASS", "rolled_back": promotion_id, "current_version": previous.get("version", 0)}


def record_soak_run(repo: Path, critical_failure: bool = False) -> dict[str, Any]:
    state = _current(repo)
    if not state.get("soak"):
        return {"status": "NO_SOAK"}
    if critical_failure and state.get("promotion_id"):
        result = rollback_promotion(repo, state["promotion_id"], "critical failure during five-run soak")
        result["status"] = "AUTO_ROLLBACK"
        return result
    for item in state["soak"].values():
        if item["status"] == "SOAKING":
            item["remaining_runs"] = max(0, item["remaining_runs"] - 1)
            if item["remaining_runs"] == 0:
                item["status"] = "ACTIVE"
    atomic_json(repo / "governance" / "promotions" / "current.json", state)
    return {"status": "PASS", "soak": state["soak"]}
