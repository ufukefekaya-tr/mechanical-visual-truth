from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from mvt.util import sha256_file


SKILLS = ("mechanical-visual-truth", "mvt-governance")


def _hash_tree(path: Path) -> dict[str, str]:
    return {str(item.relative_to(path)): sha256_file(item) for item in sorted(path.rglob("*")) if item.is_file()}


def skill_action(repo: Path, action: str, target_root: Path) -> dict[str, Any]:
    target_root.mkdir(parents=True, exist_ok=True)
    results = []
    for name in SKILLS:
        source = repo / "skills" / name
        target = target_root / name
        if action == "uninstall":
            if target.exists():
                shutil.rmtree(target)
            results.append({"skill": name, "status": "removed"})
            continue
        if action in {"install", "sync"}:
            before = _hash_tree(target) if target.exists() else {}
            source_hash = _hash_tree(source)
            if before != source_hash:
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            results.append({"skill": name, "status": "current", "files": source_hash})
        elif action == "doctor":
            results.append({"skill": name, "status": "PASS" if target.exists() and _hash_tree(target) == _hash_tree(source) else "RED"})
        else:
            raise ValueError(action)
    return {"status": "PASS" if all(item["status"] != "RED" for item in results) else "RED", "target": str(target_root), "results": results}
