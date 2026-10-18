from __future__ import annotations

import json
import mimetypes
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from mvt.util import redact, sha256_file, utc_now


TEXT_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json", ".jsonl", ".py", ".toml"}
IGNORED_PARTS = {".git", ".venv", "__pycache__", "frames", "accepted", "node_modules", ".cache"}


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            document_id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_path TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE, event_time TEXT, record_time TEXT NOT NULL,
            validity_as_of TEXT, trust_level TEXT NOT NULL, sensitivity TEXT NOT NULL,
            supersedes TEXT, content TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            document_id UNINDEXED, content, source_path, source_type
        );
    """)
    return db


def _files(root: Path, exports: Iterable[Path]) -> Iterable[tuple[Path, str, str]]:
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root) or any(part in IGNORED_PARTS for part in path.parts) or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        source_type = "run" if "runs" in path.parts else "repo"
        yield path, source_type, "trusted_repo" if source_type == "repo" else "generated_record"
    for export in exports:
        path = export.resolve()
        if root not in path.parents:
            raise ValueError(f"Chat export must be inside this repository: {path}")
        if path.suffix.lower() not in {".json", ".jsonl"}:
            raise ValueError(f"Chat export must be JSON/JSONL: {path}")
        yield path, "chat_export", "untrusted_content"


def rebuild_index(root: Path, db_path: Path, exports: Iterable[Path] = ()) -> dict[str, Any]:
    db = _connect(db_path)
    inserted = skipped = 0
    try:
        for path, source_type, trust in _files(root.resolve(), exports):
            digest = sha256_file(path)
            if db.execute("SELECT 1 FROM documents WHERE sha256=?", (digest,)).fetchone():
                skipped += 1
                continue
            try:
                content = redact(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            document_id = digest[:24]
            stat = path.stat()
            relative = str(path.relative_to(root.resolve()))
            sensitivity = "untrusted" if source_type == "chat_export" else "internal"
            event_time = None
            supersedes = None
            if path.suffix.lower() in {".json", ".jsonl"}:
                try:
                    first = json.loads(content.splitlines()[0] if path.suffix.lower() == ".jsonl" else content)
                    if isinstance(first, dict):
                        event_time = first.get("event_time") or first.get("created_at")
                        supersedes = first.get("supersedes")
                except json.JSONDecodeError:
                    pass
            record = (document_id, source_type, relative, digest, event_time, utc_now(), utc_now(), trust, sensitivity, supersedes, content)
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?)", record)
            db.execute("INSERT INTO documents_fts(document_id,content,source_path,source_type) VALUES (?,?,?,?)", (document_id, content, relative, source_type))
            inserted += 1
        db.commit()
    finally:
        db.close()
    return {"status": "PASS", "inserted": inserted, "skipped_duplicate_hash": skipped, "database": str(db_path)}


def query_index(db_path: Path, query: str, limit: int = 10) -> list[dict[str, Any]]:
    db = _connect(db_path)
    try:
        rows = db.execute("""
            SELECT d.document_id,d.source_type,d.source_path,d.event_time,d.record_time,d.validity_as_of,
                   d.trust_level,d.sensitivity,d.supersedes,snippet(documents_fts,1,'[',']','…',18)
            FROM documents_fts JOIN documents d USING(document_id)
            WHERE documents_fts MATCH ?
              AND NOT EXISTS (SELECT 1 FROM documents newer WHERE newer.supersedes=d.document_id)
            ORDER BY bm25(documents_fts) LIMIT ?
        """, (query, limit)).fetchall()
        keys = ["document_id", "source_type", "source_path", "event_time", "record_time", "validity_as_of", "trust_level", "sensitivity", "supersedes", "snippet"]
        return [dict(zip(keys, row)) for row in rows]
    finally:
        db.close()
