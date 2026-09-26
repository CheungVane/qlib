"""SQLite schema, connection handling, object store and shared helper methods."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from .model import validate_package, _instant
from datetime import datetime, timedelta, timezone

def instant_order(value):
    delta = _instant(value, "created_at") - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds



SCHEMA_VERSION = 4
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

V3_IMPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    receipt_id TEXT PRIMARY KEY,
    attempt_id TEXT,
    run_id TEXT,
    revision_id TEXT,
    source_instance_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    imported_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS imports_attempt ON imports(attempt_id, imported_at);
CREATE INDEX IF NOT EXISTS imports_run ON imports(run_id, imported_at);
PRAGMA user_version=3;
"""

IMPORT_STATUSES = ("imported", "reused", "failed")

V4_FACTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS factors (
    factor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_instance_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    definition_json TEXT NOT NULL DEFAULT '{}',
    dataset_id TEXT,
    dataset_version TEXT,
    snapshot_label TEXT,
    calendar_id TEXT,
    provenance_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(source_instance_id, external_id, dataset_version)
);
CREATE TABLE IF NOT EXISTS factor_panels (
    panel_id TEXT PRIMARY KEY,
    factor_id TEXT NOT NULL REFERENCES factors(factor_id),
    content_hash TEXT NOT NULL,
    object_key TEXT NOT NULL,
    date_count INTEGER NOT NULL,
    instrument_count INTEGER NOT NULL,
    cell_count INTEGER NOT NULL,
    valid_count INTEGER NOT NULL,
    start_date TEXT,
    end_date TEXT,
    published_at TEXT NOT NULL,
    UNIQUE(factor_id, content_hash)
);
CREATE INDEX IF NOT EXISTS factor_panels_factor ON factor_panels(factor_id, published_at);
PRAGMA user_version=4;
"""


class SchemaVersionError(RuntimeError):
    pass



class LocalObjectStore:
    """Content-addressed local object store (swap for an object-storage adapter later)."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, content_hash: str, data: bytes) -> str:
        key = f"{content_hash[:2]}/{content_hash}.json"
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
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

    def read(self, key: str) -> bytes:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise RuntimeError("invalid object key")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != path.stem:
            raise RuntimeError(f"object digest mismatch: {key}")
        return data


class SqliteStore:
    def __init__(self, root: str | Path, before_commit: Callable[[], None] | None = None,
                 object_store=None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.object_store = object_store or LocalObjectStore(self.root / "objects")
        self.objects = self.object_store.root
        self.db = self.root / "workbench.sqlite3"
        self.before_commit = before_commit
        self._init_db()

    def _write_object(self, content_hash: str, data: bytes) -> str:
        return self.object_store.write(content_hash, data)

    def _read_object(self, key: str) -> dict[str, Any]:
        return json.loads(self.object_store.read(key))
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
            if version not in (0, 1, 2, 3, SCHEMA_VERSION):
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
                version = 2
            if version == 2:
                conn.executescript(V3_IMPORT_SCHEMA)
                version = 3
            if version == 3:
                conn.executescript(V4_FACTOR_SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")

    def health(self) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "schema_version": SCHEMA_VERSION}

    # -- factors and factor panels (FACTOR_ANALYSIS U19) ------------------
