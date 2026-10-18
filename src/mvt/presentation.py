from __future__ import annotations

from pathlib import Path
from typing import Any

from mvt.acceptance import load_ledger, verify_accepted
from mvt.contracts import Contract
from mvt.errors import AuditRed
from mvt.util import atomic_json


def prepare(contract: Contract, output: Path) -> dict[str, Any]:
    verification = verify_accepted(contract)
    if any(item["status"] == "RED" for item in verification):
        raise AuditRed("Accepted reference hash mismatch")
    accepted = load_ledger(contract)["accepted"]
    rejected_hashes = {item["sha256"] for item in load_ledger(contract)["rejected"]}
    references = [item for item in accepted if item["sha256"] not in rejected_hashes]
    package = {
        "contract_hash": contract.hash, "authoritative_references": references,
        "camera_lock": [camera["id"] for camera in contract.data["cameras"]],
        "entity_counts": contract.data.get("requirements", {}).get("counts", {}),
        "immutable": ["silhouette", "entity counts", "clearances", "station placement", "camera projection"],
        "allowed_changes": ["materials", "lighting", "studio background", "micro-surface realism"],
        "prohibited": ["new geometry", "removed geometry", "changed count", "rejected reference", "technical-master promotion"],
        "prompt": "Preserve the supplied deterministic geometry, camera, counts, gaps, and silhouette exactly. Improve only materials, lighting, and studio realism.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, package)
    return package
