from __future__ import annotations

from mvt.indexing import query_index, rebuild_index


def test_index_deduplicates_and_redacts(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "note.md").write_text("bridge clearance API_KEY=super-secret-value", encoding="utf-8")
    db = root / "index.sqlite3"
    first = rebuild_index(root, db)
    second = rebuild_index(root, db)
    assert first["inserted"] == 1
    assert second["skipped_duplicate_hash"] >= 1
    rows = query_index(db, "bridge")
    assert rows
    assert "super-secret-value" not in rows[0]["snippet"]


def test_chat_export_must_be_inside_repo(tmp_path):
    root = tmp_path / "repo"; root.mkdir()
    external = tmp_path / "external.json"; external.write_text("{}")
    try:
        rebuild_index(root, root / "index.sqlite3", [external])
    except ValueError as exc:
        assert "inside this repository" in str(exc)
    else:
        raise AssertionError("external export accepted")
