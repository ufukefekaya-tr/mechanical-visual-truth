from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from mvt.util import atomic_json, repo_root


def load_registry(repo: Path) -> dict[str, Any]:
    return yaml.safe_load((repo / "tools" / "registry.yaml").read_text(encoding="utf-8"))


def validate_registry(repo: Path) -> dict[str, Any]:
    import json

    schema = json.loads((repo / "schemas" / "tool-manifest.schema.json").read_text(encoding="utf-8"))
    findings = []
    names = set()
    for tool in load_registry(repo).get("tools", []):
        errors = [error.message for error in Draft202012Validator(schema).iter_errors(tool)]
        if tool.get("name") in names:
            errors.append("duplicate name")
        names.add(tool.get("name"))
        findings.append({"tool": tool.get("name"), "status": "RED" if errors else "PASS", "errors": errors})
    return {"status": "RED" if any(item["status"] == "RED" for item in findings) else "PASS", "findings": findings}


def set_enabled(repo: Path, name: str, enabled: bool) -> dict[str, Any]:
    path = repo / "tools" / "registry.yaml"
    data = load_registry(repo)
    matched = False
    for tool in data["tools"]:
        if tool["name"] == name:
            if enabled and validate_registry(repo)["status"] != "PASS":
                raise ValueError("Registry validation failed")
            tool["enabled"] = enabled
            matched = True
    if not matched:
        raise KeyError(name)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return {"status": "PASS", "tool": name, "enabled": enabled}
