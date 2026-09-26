"""SQLite manifest and immutable local objects for the single-machine workbench."""

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

    def list_revisions_page(self, run_id: str, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        """Bounded revision list (ARC07); newest first with a stable cursor."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise ValueError("invalid cursor")
        query = ("SELECT revision_id,content_hash,adapter_version,published_at FROM revisions WHERE run_id=?")
        params: list[Any] = [run_id]
        if cursor:
            with self._connect() as conn:
                anchor = conn.execute(
                    "SELECT published_at FROM revisions WHERE run_id=? AND revision_id=?",
                    (run_id, cursor)).fetchone()
            if anchor is None:
                raise ValueError("unknown cursor")
            query += (" AND (instant_order(published_at) < instant_order(?) OR "
                      "(instant_order(published_at) = instant_order(?) AND revision_id < ?))")
            params.extend((anchor["published_at"], anchor["published_at"], cursor))
        query += " ORDER BY instant_order(published_at) DESC, revision_id DESC LIMIT ?"
        params.append(limit + 1)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        more = len(rows) > limit
        items = [dict(row) for row in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["revision_id"] if more else None}

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

    # -- factors and factor panels (FACTOR_ANALYSIS U19) ------------------
    def publish_factor(self, identity: dict[str, Any], panel: dict[str, Any]) -> dict[str, Any]:
        """Insert or reuse one factor and one immutable panel (content hashed)."""
        for key in ("source_instance_id", "external_id", "name"):
            if not isinstance(identity.get(key), str) or not identity[key].strip():
                raise ValueError(f"{key} is required")
        data = json.dumps(panel, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        content_hash = hashlib.sha256(data).hexdigest()
        key = self._write_object(content_hash, data)
        dataset_version = (identity.get("dataset") or {}).get("version")
        created_at = identity.get("created_at") or datetime.now(timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT factor_id FROM factors WHERE source_instance_id=? AND external_id=?
                   AND dataset_version IS ?""",
                (identity["source_instance_id"], identity["external_id"], dataset_version)).fetchone()
            if row:
                factor_id, created = row["factor_id"], False
            else:
                factor_id, created = str(uuid.uuid4()), True
                conn.execute(
                    """INSERT INTO factors(factor_id,name,source_instance_id,external_id,definition_json,
                       dataset_id,dataset_version,snapshot_label,calendar_id,provenance_json,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (factor_id, identity["name"], identity["source_instance_id"], identity["external_id"],
                     json.dumps(identity.get("definition") or {}, ensure_ascii=False, sort_keys=True),
                     (identity.get("dataset") or {}).get("id"), dataset_version,
                     (identity.get("dataset") or {}).get("snapshot_label"),
                     identity.get("calendar_id"),
                     json.dumps(identity.get("provenance") or {}, ensure_ascii=False, sort_keys=True), created_at))
            existing = conn.execute(
                "SELECT panel_id FROM factor_panels WHERE factor_id=? AND content_hash=?",
                (factor_id, content_hash)).fetchone()
            if existing:
                panel_id = existing["panel_id"]
            else:
                panel_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO factor_panels(panel_id,factor_id,content_hash,object_key,date_count,
                       instrument_count,cell_count,valid_count,start_date,end_date,published_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (panel_id, factor_id, content_hash, key, panel["date_count"], panel["instrument_count"],
                     panel["cell_count"], panel["valid_count"], panel["dates"][0] if panel["dates"] else None,
                     panel["dates"][-1] if panel["dates"] else None, created_at))
            row = conn.execute("SELECT * FROM factors WHERE factor_id=?", (factor_id,)).fetchone()
        return {"factor_id": factor_id, "panel_id": panel_id, "content_hash": content_hash,
                "created": created, "panel_created": not bool(existing), "factor": self._factor_row(row)}

    @staticmethod
    def _factor_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["definition"] = json.loads(record.pop("definition_json") or "{}")
        record["provenance"] = json.loads(record.pop("provenance_json") or "{}")
        record["dataset"] = {"id": record.pop("dataset_id", None),
                             "version": record.pop("dataset_version", None),
                             "snapshot_label": record.pop("snapshot_label", None)}
        return record

    def list_factors(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT f.*, (SELECT COUNT(*) FROM factor_panels p WHERE p.factor_id=f.factor_id) AS panel_count
                   FROM factors f ORDER BY instant_order(f.created_at) DESC, f.factor_id DESC""").fetchall()
        return [self._factor_row(row) for row in rows]

    def get_factor(self, factor_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM factors WHERE factor_id=?", (factor_id,)).fetchone()
        return self._factor_row(row) if row else None

    def list_factor_panels(self, factor_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT panel_id,factor_id,content_hash,object_key,date_count,instrument_count,cell_count,
                   valid_count,start_date,end_date,published_at FROM factor_panels WHERE factor_id=?
                   ORDER BY instant_order(published_at) DESC, panel_id DESC""", (factor_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_factor_panel(self, factor_id: str, panel_id: str | None = None) -> dict[str, Any] | None:
        panels = self.list_factor_panels(factor_id)
        if not panels:
            return None
        panel = next((row for row in panels if row["panel_id"] == panel_id), panels[0]) if panel_id else panels[0]
        payload = self._read_object(panel["object_key"])
        if hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest() != panel["content_hash"]:
            raise RuntimeError("factor panel digest mismatch")
        return {**panel, "panel": payload}

    # -- import receipts --------------------------------------------------
    def record_import(self, record: dict[str, Any]) -> dict[str, Any]:
        """Upsert one import receipt; the receipt is the platform fact for EXEC12."""
        required = ("receipt_id", "source_instance_id", "external_id", "adapter_version", "status", "imported_at")
        if not all(isinstance(record.get(key), str) and record[key].strip() for key in required):
            raise ValueError(
                "receipt_id, source_instance_id, external_id, adapter_version, status and imported_at are required")
        if record["status"] not in IMPORT_STATUSES:
            raise ValueError(f"unknown import status: {record['status']}")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """INSERT INTO imports(receipt_id,attempt_id,run_id,revision_id,source_instance_id,external_id,
                   adapter_version,status,reason,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(receipt_id) DO UPDATE SET run_id=excluded.run_id,revision_id=excluded.revision_id,
                   status=excluded.status,reason=excluded.reason,imported_at=excluded.imported_at""",
                (record["receipt_id"], record.get("attempt_id"), record.get("run_id"), record.get("revision_id"),
                 record["source_instance_id"], record["external_id"], record["adapter_version"],
                 record["status"], record.get("reason"), record["imported_at"]))
            row = conn.execute("SELECT * FROM imports WHERE receipt_id=?", (record["receipt_id"],)).fetchone()
        return dict(row)

    def latest_import(self, attempt_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM imports WHERE attempt_id=? ORDER BY instant_order(imported_at) DESC LIMIT 1",
                (attempt_id,)).fetchone()
        return dict(row) if row else None

    def list_imports(self, attempt_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        query, params = "SELECT * FROM imports", []
        if attempt_id:
            query += " WHERE attempt_id=?"
            params.append(attempt_id)
        query += " ORDER BY instant_order(imported_at) DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def attempt_stats(self, window_seconds: int = 86400) -> dict[str, Any]:
        """Attempt-level rates; cancelled and interrupted are counted apart from failures."""
        if isinstance(window_seconds, bool) or not isinstance(window_seconds, int) or not 60 <= window_seconds <= 2592000:
            raise ValueError("window_seconds must be between 60 and 2592000")
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(seconds=window_seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT kind, status, started_at, ended_at FROM attempts
                   WHERE instant_order(created_at) >= instant_order(?)""", (cutoff,)).fetchall()
            first = conn.execute(
                "SELECT created_at FROM attempts ORDER BY instant_order(created_at) ASC LIMIT 1").fetchone()
        statuses = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0, "cancelled": 0, "interrupted": 0}
        durations: list[float] = []
        by_kind: dict[str, dict[str, Any]] = {}
        for row in rows:
            status = row["status"] if row["status"] in statuses else "interrupted"
            statuses[status] += 1
            entry = by_kind.setdefault(row["kind"], {"kind": row["kind"], "total": 0, **{k: 0 for k in statuses}})
            entry["total"] += 1
            entry[status] += 1
            if row["started_at"] and row["ended_at"]:
                seconds = (_instant(row["ended_at"], "ended_at") - _instant(row["started_at"], "started_at")).total_seconds()
                if seconds >= 0:
                    durations.append(seconds)
        durations.sort()
        denominator = statuses["succeeded"] + statuses["failed"]
        p95 = durations[min(len(durations) - 1, max(0, math.ceil(0.95 * len(durations)) - 1))] if durations else None
        coverage = 0.0
        if first and first["created_at"]:
            coverage = max(0.0, (now - _instant(first["created_at"], "created_at")).total_seconds())
        total = len(rows)
        return {
            "availability": "available" if total else "empty",
            "window_seconds": window_seconds,
            "total": total,
            "statuses": statuses,
            "failure_rate": (statuses["failed"] / denominator) if denominator else None,
            "failure_denominator": denominator,
            "cancelled": statuses["cancelled"],
            "interrupted": statuses["interrupted"],
            "terminal_p95_seconds": p95,
            "by_kind": sorted(by_kind.values(), key=lambda item: (-item["total"], item["kind"])),
            "collection_started_at": first["created_at"] if first else None,
            "coverage_seconds": min(float(window_seconds), coverage),
            "observed_at": now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "scope": ("平台Attempt（本机工作台库）；窗口按Attempt创建时间；failure_rate=failed/(succeeded+failed)，"
                      "cancelled与interrupted单列；不从日志推断额外语义。"),
        }
