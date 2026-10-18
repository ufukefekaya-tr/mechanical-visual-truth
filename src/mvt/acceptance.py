from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from mvt.contracts import Contract
from mvt.errors import AuditRed
from mvt.util import atomic_json, owned_path, read_json, sha256_file, utc_now


def ledger_path(contract: Contract) -> Path:
    return owned_path(contract.project_dir, "acceptance-ledger.json")


def load_ledger(contract: Contract) -> dict[str, Any]:
    return read_json(ledger_path(contract), {"accepted": [], "rejected": []})


def accept(contract: Contract, image: Path) -> dict[str, Any]:
    image = image.resolve()
    if not image.exists():
        raise FileNotFoundError(image)
    ledger = load_ledger(contract)
    digest = sha256_file(image)
    if any(item["sha256"] == digest for item in ledger["rejected"]):
        raise AuditRed("Rejected artifact cannot be accepted without a new file revision")
    accepted_dir = owned_path(contract.project_dir, "accepted")
    accepted_dir.mkdir(exist_ok=True)
    destination = accepted_dir / f"{image.stem}-{digest[:12]}{image.suffix.lower()}"
    if not destination.exists():
        shutil.copy2(image, destination)
    record = {"source": str(image), "path": str(destination), "relative_path": destination.relative_to(contract.project_dir).as_posix(), "sha256": digest, "accepted_at": utc_now()}
    if not any(item["sha256"] == digest for item in ledger["accepted"]):
        ledger["accepted"].append(record)
    atomic_json(ledger_path(contract), ledger)
    return record


def reject(contract: Contract, image: Path, reason: str) -> dict[str, Any]:
    image = image.resolve()
    if not image.exists():
        raise FileNotFoundError(image)
    ledger = load_ledger(contract)
    record = {"source": str(image), "sha256": sha256_file(image), "reason": reason, "rejected_at": utc_now()}
    if not any(item["sha256"] == record["sha256"] for item in ledger["rejected"]):
        ledger["rejected"].append(record)
    atomic_json(ledger_path(contract), ledger)
    return record


def verify_accepted(contract: Contract) -> list[dict[str, Any]]:
    findings = []
    for item in load_ledger(contract)["accepted"]:
        path = Path(item.get("relative_path", item["path"]))
        if not path.is_absolute():
            path = contract.project_dir / path
        path = path.resolve()
        if not path.is_relative_to(contract.project_dir.resolve()):
            findings.append({"status": "RED", "reason": "accepted path escapes project"})
            continue
        actual = sha256_file(path) if path.is_file() else None
        findings.append({"path": str(path), "expected": item["sha256"], "actual": actual, "status": "PASS" if actual == item["sha256"] else "RED"})
    return findings
