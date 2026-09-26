"""SQLite manifest and immutable local objects for the single-machine workbench."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from .model import validate_package, _instant
from datetime import datetime, timezone

def instant_order(value):
    delta = _instant(value, "created_at") - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds



SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    pass


class LocalResultRepository:
    def __init__(self, root: str | Path, before_commit: Callable[[], None] | None = None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects = self.root / "objects"
        self.objects.mkdir(exist_ok=True)
        self.db = self.root / "workbench.sqlite3"
        self.before_commit = before_commit
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.create_function("instant_order", 1, instant_order, deterministic=True)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION and version != 0:
                raise SchemaVersionError(f"database schema {version}; expected {SCHEMA_VERSION}; no automatic migration")
            if version == 0 and any(row[0] != "sqlite_sequence" for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )):
                raise SchemaVersionError("existing unversioned database; refusing to modify it")
            if version == 0:
                conn.executescript("""
                CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY,
                    source_instance_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    latest_revision_id TEXT,
                    UNIQUE(source_instance_id, external_id)
                );
                CREATE TABLE revisions (
                    revision_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    content_hash TEXT NOT NULL,
                    adapter_version TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    published_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    UNIQUE(run_id, content_hash, adapter_version)
                );
                CREATE INDEX revisions_run ON revisions(run_id, published_at);
                PRAGMA user_version=1;
                """)
            conn.execute("PRAGMA journal_mode=WAL")

    def _write_object(self, content_hash: str, data: bytes) -> str:
        key = f"{content_hash[:2]}/{content_hash}.json"
        target = self.objects / key
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            fd, temp = tempfile.mkstemp(prefix=".pending-", dir=target.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp, target)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        return key

    def publish(self, source_instance_id: str, external_id: str, adapter_version: str,
                package: dict[str, Any]) -> dict[str, Any]:
        if not all(isinstance(x, str) and x.strip() for x in (source_instance_id, external_id, adapter_version)):
            raise ValueError("source_instance_id, external_id and adapter_version are required")
        canonical = validate_package(package)
        data = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        content_hash = hashlib.sha256(data).hexdigest()
        key = self._write_object(content_hash, data)
        identity = json.dumps([source_instance_id, external_id], ensure_ascii=False, separators=(",", ":"))
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"quant-workbench:{identity}"))
        if self.before_commit:
            self.before_commit()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT run_id FROM runs WHERE source_instance_id=? AND external_id=?",
                (source_instance_id, external_id),
            ).fetchone()
            if previous:
                run_id = previous["run_id"]
            else:
                conn.execute("INSERT INTO runs(run_id,source_instance_id,external_id,created_at) VALUES(?,?,?,?)",
                             (run_id, source_instance_id, external_id, canonical["run"]["created_at"]))
            revision_id = hashlib.sha256(f"{run_id}:{content_hash}:{adapter_version}".encode()).hexdigest()[:32]
            existing = conn.execute("SELECT 1 FROM revisions WHERE revision_id=?", (revision_id,)).fetchone()
            if not existing:
                conn.execute("INSERT INTO revisions(revision_id,run_id,content_hash,adapter_version,object_key) VALUES(?,?,?,?,?)",
                             (revision_id, run_id, content_hash, adapter_version, key))
                conn.execute("UPDATE runs SET latest_revision_id=? WHERE run_id=?", (revision_id, run_id))
        return {"run_id": run_id, "revision_id": revision_id, "created": not bool(existing)}

    def _summary(self, row: sqlite3.Row) -> dict[str, Any]:
        obj = self._read_object(row["object_key"])
        return {
            "run_id": row["run_id"], "source_instance_id": row["source_instance_id"],
            "external_id": row["external_id"], "revision_id": row["revision_id"],
            "published_at": row["published_at"], "run": obj["run"],
        }

    def list_runs(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) != 36):
            raise ValueError("invalid cursor")
        query = """SELECT r.*,v.revision_id,v.object_key,v.published_at FROM runs r
                   JOIN revisions v ON v.revision_id=r.latest_revision_id"""
        params: list[Any] = []
        if cursor:
            with self._connect() as conn:
                anchor = conn.execute("SELECT created_at,run_id FROM runs WHERE run_id=?", (cursor,)).fetchone()
            if anchor is None:
                raise ValueError("unknown cursor")
            query += " WHERE (instant_order(r.created_at) < instant_order(?) OR (instant_order(r.created_at) = instant_order(?) AND r.run_id < ?))"
            params.extend((anchor["created_at"], anchor["created_at"], anchor["run_id"]))
        query += " ORDER BY instant_order(r.created_at) DESC,r.run_id DESC LIMIT ?"
        params.append(limit + 1)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        more = len(rows) > limit
        items = [self._summary(row) for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["run_id"] if more else None}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("""SELECT r.*,v.revision_id,v.object_key,v.published_at FROM runs r
                                  JOIN revisions v ON v.revision_id=r.latest_revision_id WHERE r.run_id=?""",
                               (run_id,)).fetchone()
        return self._summary(row) if row else None

    def list_revisions(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT revision_id,content_hash,adapter_version,published_at FROM revisions WHERE run_id=? ORDER BY published_at,revision_id",
                                (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_revision(self, run_id: str, revision_id: str | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("""SELECT v.* FROM revisions v JOIN runs r ON r.run_id=v.run_id
                                  WHERE v.run_id=? AND v.revision_id=COALESCE(?,r.latest_revision_id)""",
                               (run_id, revision_id)).fetchone()
        if not row:
            return None
        return {"run_id": run_id, "revision_id": row["revision_id"], "published_at": row["published_at"],
                "adapter_version": row["adapter_version"], "content_hash": row["content_hash"],
                "result": self._read_object(row["object_key"])}

    def _read_object(self, key: str) -> dict[str, Any]:
        path = (self.objects / key).resolve()
        if not path.is_relative_to(self.objects):
            raise RuntimeError("invalid object key")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != path.stem:
            raise RuntimeError(f"object digest mismatch: {key}")
        return json.loads(data)

    def health(self) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "schema_version": SCHEMA_VERSION}
