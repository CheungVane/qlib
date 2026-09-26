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



SCHEMA_VERSION = 2
ATTEMPT_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "interrupted")
ATTEMPT_OPEN_STATUSES = ("queued", "running")

V1_SCHEMA = """
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
"""

V2_ATTEMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    executor_id TEXT NOT NULL,
    label TEXT NOT NULL,
    probe INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT UNIQUE,
    request_id TEXT,
    config_fingerprint TEXT,
    workspace TEXT,
    log_path TEXT,
    pid INTEGER,
    exit_code INTEGER,
    error_code TEXT,
    error_message TEXT,
    outcome_json TEXT,
    created_at TEXT NOT NULL,
    queued_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    heartbeat_at TEXT,
    cancel_requested_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_created ON attempts(created_at, attempt_id);
CREATE INDEX IF NOT EXISTS attempts_status ON attempts(status);
PRAGMA user_version=2;
"""

ATTEMPT_MUTABLE_FIELDS = (
    "status", "started_at", "ended_at", "heartbeat_at", "cancel_requested_at", "exit_code",
    "pid", "workspace", "log_path", "config_fingerprint", "error_code", "error_message", "outcome",
)


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
        """Create or migrate the platform database one version at a time.

        Migrations only add platform tables; result revisions and runs are never rewritten.
        """
        with self._connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, SCHEMA_VERSION):
                raise SchemaVersionError(
                    f"database schema {version}; supported versions are 0..{SCHEMA_VERSION}; refusing to modify")
            if version == 0 and any(row[0] != "sqlite_sequence" for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )):
                raise SchemaVersionError("existing unversioned database; refusing to modify it")
            if version == 0:
                conn.executescript(V1_SCHEMA)
                version = 1
            if version == 1:
                conn.executescript(V2_ATTEMPT_SCHEMA)
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

    @staticmethod
    def _attempt_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["probe"] = bool(record.get("probe"))
        record["params"] = json.loads(record.pop("params_json") or "{}")
        outcome = record.pop("outcome_json", None)
        record["outcome"] = json.loads(outcome) if outcome else None
        return record

    def create_attempt(self, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Insert one attempt; a duplicate idempotency key returns the existing row."""
        required = ("attempt_id", "kind", "executor_id", "label", "params", "created_at")
        if not all(record.get(key) not in (None, "") for key in required):
            raise ValueError("attempt_id, kind, executor_id, label, params and created_at are required")
        if record.get("status") not in ATTEMPT_OPEN_STATUSES:
            raise ValueError("new attempts must start queued or running")
        key = record.get("idempotency_key")
        if key is not None and (not isinstance(key, str) or not key.strip() or len(key) > 128):
            raise ValueError("idempotency_key must be a non-empty string of at most 128 characters")
        payload = (
            record["attempt_id"], record["kind"], record["executor_id"], record["label"],
            1 if record.get("probe") else 0, record["status"],
            json.dumps(record["params"], ensure_ascii=False, allow_nan=False, sort_keys=True),
            key, record.get("request_id"), record.get("config_fingerprint"), record.get("workspace"),
            record.get("log_path"), record.get("pid"), record.get("exit_code"), record.get("error_code"),
            record.get("error_message"),
            json.dumps(record["outcome"], ensure_ascii=False, allow_nan=False) if record.get("outcome") else None,
            record["created_at"], record.get("queued_at") or record["created_at"], record.get("started_at"),
            record.get("ended_at"), record.get("heartbeat_at"), record.get("cancel_requested_at"),
            record["created_at"],
        )
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute(
                    """INSERT INTO attempts(attempt_id,kind,executor_id,label,probe,status,params_json,
                       idempotency_key,request_id,config_fingerprint,workspace,log_path,pid,exit_code,error_code,
                       error_message,outcome_json,created_at,queued_at,started_at,ended_at,heartbeat_at,
                       cancel_requested_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    payload)
            except sqlite3.IntegrityError:
                if key is None:
                    raise
                row = conn.execute("SELECT * FROM attempts WHERE idempotency_key=?", (key,)).fetchone()
                if row is None:
                    raise
                return self._attempt_row(row), False
            row = conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (record["attempt_id"],)).fetchone()
        return self._attempt_row(row), True

    def get_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        return self._attempt_row(row) if row else None

    def find_attempt_by_key(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM attempts WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        return self._attempt_row(row) if row else None

    def update_attempt(self, attempt_id: str, **fields: Any) -> dict[str, Any] | None:
        unknown = set(fields) - set(ATTEMPT_MUTABLE_FIELDS)
        if unknown:
            raise ValueError(f"attempt fields are not updatable: {sorted(unknown)}")
        if not fields:
            return self.get_attempt(attempt_id)
        columns, values = [], []
        for key, value in fields.items():
            if key == "outcome":
                key, value = "outcome_json", (
                    json.dumps(value, ensure_ascii=False, allow_nan=False) if value is not None else None)
            columns.append(f"{key}=?")
            values.append(value)
        columns.append("updated_at=?")
        values.extend((datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), attempt_id))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(f"UPDATE attempts SET {','.join(columns)} WHERE attempt_id=?", values)
            if cursor.rowcount == 0:
                return None
            row = conn.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        return self._attempt_row(row)

    def list_attempts(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) != 36):
            raise ValueError("invalid cursor")
        query = "SELECT * FROM attempts"
        params: list[Any] = []
        if cursor:
            with self._connect() as conn:
                anchor = conn.execute("SELECT created_at,attempt_id FROM attempts WHERE attempt_id=?", (cursor,)).fetchone()
            if anchor is None:
                raise ValueError("unknown cursor")
            query += (" WHERE (instant_order(created_at) < instant_order(?) OR "
                      "(instant_order(created_at) = instant_order(?) AND attempt_id < ?))")
            params.extend((anchor["created_at"], anchor["created_at"], anchor["attempt_id"]))
        query += " ORDER BY instant_order(created_at) DESC, attempt_id DESC LIMIT ?"
        params.append(limit + 1)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        more = len(rows) > limit
        items = [self._attempt_row(row) for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["attempt_id"] if more else None}

    def list_open_attempts(self, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        placeholders = ",".join("?" for _ in ATTEMPT_OPEN_STATUSES)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM attempts WHERE status IN ({placeholders}) "
                "ORDER BY instant_order(created_at) ASC LIMIT ?", (*ATTEMPT_OPEN_STATUSES, limit)).fetchall()
        return [self._attempt_row(row) for row in rows]

    def health(self) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "schema_version": SCHEMA_VERSION}
