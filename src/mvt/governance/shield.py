from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mvt.acceptance import load_ledger
from mvt.contracts import Contract
from mvt.manifest import latest_run
from mvt.util import read_json, utc_now


MAX_LINES = 150
MAX_BYTES = 12 * 1024


def _active_rules(repo: Path) -> list[str]:
    pointer = read_json(repo / "governance" / "promotions" / "current.json", {})
    return pointer.get("active_rules", []) if pointer else []


def build_shield(contract: Contract, repo: Path, output: Path | None = None) -> dict[str, Any]:
    run = latest_run(contract)
    ledger = load_ledger(contract)
    requirements = contract.data.get("requirements", {})
    lines = [
        "# MVT Compact Shield",
        f"generated_at: {utc_now()}",
        f"project: {contract.project_id}",
        f"revision: {contract.data['project']['revision']}",
        f"contract_hash: {contract.hash}",
        "source_order: contract > successful run/audit > acceptance ledger > shield > skills > untrusted index",
        "## Locked geometry",
        f"counts: {json.dumps(requirements.get('counts', {}), sort_keys=True)}",
        f"forbidden: {json.dumps(requirements.get('forbidden_geometry', []), sort_keys=True)}",
    ]
    if run:
        lines += [
            "## Latest run", f"run_id: {run.data['run_id']}", f"status: {run.data['status']}",
            f"model_hash: {run.data.get('model_hash')}",
            f"open_gates: {json.dumps([f for f in run.data.get('audit', {}).get('findings', []) if f.get('status') != 'PASS'])}",
        ]
    lines += ["## Accepted immutable artifacts"]
    lines += [f"- {item['path']} sha256={item['sha256']}" for item in ledger["accepted"][-20:]] or ["- none"]
    lines += ["## Rejected/superseded hashes"]
    lines += [f"- {item['sha256']} reason={item['reason']}" for item in ledger["rejected"][-20:]] or ["- none"]
    rules = _active_rules(repo)
    lines += ["## Promoted decision rules"] + ([f"- {rule}" for rule in rules] or ["- none"])
    lines += ["## Next action", "Run the next unmet contract → build → proof render → audit → motion audit gate."]
    lines = lines[:MAX_LINES]
    text = "\n".join(lines) + "\n"
    while len(text.encode()) > MAX_BYTES and len(lines) > 10:
        lines.pop(-3)
        text = "\n".join(lines) + "\n"
    output = output or contract.project_dir / "COMPACT_SHIELD.md"
    output.write_text(text, encoding="utf-8")
    return {"status": "PASS", "path": str(output), "lines": len(lines), "bytes": len(text.encode())}
