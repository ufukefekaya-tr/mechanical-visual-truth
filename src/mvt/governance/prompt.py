from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from mvt.util import read_json, sha256_file, utc_now


MAX_PROMPT_BYTES = 16 * 1024


def build_prompt(repo: Path) -> dict[str, Any]:
    template = repo / "governance" / "prompts" / "templates" / "SYSTEM_PROMPT.template.md"
    rules_path = repo / "governance" / "rules" / "registry.yaml"
    if not template.exists() or not rules_path.exists():
        raise FileNotFoundError("Prompt template/rule registry missing")
    import yaml

    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))["rules"]
    active = [item["text"] for item in rules if item.get("active", True)]
    promotion = read_json(repo / "governance" / "promotions" / "current.json", {})
    active.extend(promotion.get("prompt_rules", []))
    if len(active) != len(set(active)):
        raise ValueError("Duplicate prompt rules")
    body = template.read_text(encoding="utf-8").replace("{{RULES}}", "\n".join(f"- {rule}" for rule in active))
    if len(body.encode()) > MAX_PROMPT_BYTES:
        raise ValueError("Prompt budget exceeded")
    contradictory = [(a, b) for a in active for b in active if a != b and a.lower().startswith("always ") and b.lower() == a.lower().replace("always ", "never ", 1)]
    if contradictory:
        raise ValueError(f"Prompt contradiction: {contradictory[0]}")
    versions = repo / "governance" / "prompts" / "versions"
    versions.mkdir(exist_ok=True)
    existing = sorted(versions.glob("SYSTEM_PROMPT.generated.v*.md"))
    version = len(existing) + 1
    target = versions / f"SYSTEM_PROMPT.generated.v{version}.md"
    target.write_text(body, encoding="utf-8")
    current = repo / "governance" / "prompts" / "current.md"
    fd, name = tempfile.mkstemp(prefix=".prompt.", dir=current.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.replace(name, current)
    return {"status": "PASS", "version": version, "path": str(target), "sha256": sha256_file(target), "generated_at": utc_now()}


def verify_prompt(repo: Path) -> dict[str, Any]:
    current = repo / "governance" / "prompts" / "current.md"
    if not current.exists():
        return {"status": "RED", "reason": "prompt not generated"}
    text = current.read_text(encoding="utf-8")
    return {"status": "PASS" if len(text.encode()) <= MAX_PROMPT_BYTES and "{{RULES}}" not in text else "RED", "bytes": len(text.encode()), "sha256": sha256_file(current)}


def rollback_prompt(repo: Path) -> dict[str, Any]:
    versions = sorted((repo / "governance" / "prompts" / "versions").glob("SYSTEM_PROMPT.generated.v*.md"))
    if len(versions) < 2:
        raise ValueError("No prior prompt version")
    previous = versions[-2]
    current = repo / "governance" / "prompts" / "current.md"
    fd, name = tempfile.mkstemp(prefix=".prompt-rollback.", dir=current.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(previous.read_text(encoding="utf-8"))
    os.replace(name, current)
    return {"status": "PASS", "path": str(previous), "sha256": sha256_file(previous)}
