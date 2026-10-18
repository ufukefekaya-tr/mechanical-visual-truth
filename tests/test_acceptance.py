from __future__ import annotations

from pathlib import Path

import pytest

from mvt.acceptance import accept, reject, verify_accepted
from mvt.contracts import Contract
from mvt.errors import AuditRed


def local_contract(mechanics, tmp_path):
    path = tmp_path / "contract.yaml"
    path.write_text("project: local\n", encoding="utf-8")
    return Contract(path, mechanics.data, mechanics.hash)


def test_accepted_artifact_hash_change_is_red(mechanics, tmp_path):
    contract = local_contract(mechanics, tmp_path)
    source = tmp_path / "proof.png"
    source.write_bytes(b"valid-proof")
    record = accept(contract, source)
    Path(record["path"]).write_bytes(b"changed")
    assert verify_accepted(contract)[0]["status"] == "RED"


def test_rejected_hash_cannot_be_accepted(mechanics, tmp_path):
    contract = local_contract(mechanics, tmp_path)
    source = tmp_path / "rejected.png"
    source.write_bytes(b"bad-proof")
    reject(contract, source, "wrong geometry")
    duplicate = tmp_path / "renamed.png"
    duplicate.write_bytes(source.read_bytes())
    with pytest.raises(AuditRed):
        accept(contract, duplicate)


def test_accepted_ledger_cannot_hash_foreign_files(mechanics, tmp_path):
    import json
    contract = local_contract(mechanics, tmp_path)
    (tmp_path / "acceptance-ledger.json").write_text(json.dumps({
        "accepted": [{"path": "/outside/workspace/private", "sha256": "irrelevant"}],
        "rejected": []}))
    result = verify_accepted(contract)
    assert result == [{"status": "RED", "reason": "accepted path escapes project"}]
