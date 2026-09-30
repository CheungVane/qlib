"""Explicit schema6→7 maintenance migration (PHYSICAL_CONTRACT §2/§6/§6.1).

This module never runs on service startup. It is invoked only by the
``qwb storage`` maintenance command, performs a consistency backup first and
keeps every legacy row/index/object identity unchanged. The migration runs in
one explicit transaction; failures roll back and keep the backup.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

SOURCE_SCHEMA = 6
TARGET_SCHEMA = 7
# The running service still ships schema6 until G1-2/G1-5 inject the schema7
# repository; migration must therefore stay an operator-only command.
SUPPORTED_SCHEMA = 6
TERMINAL_WITH_END = ("succeeded", "failed", "cancelled")


class MigrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, exit_code: int = 3, **details: Any):
        self.code = code
        self.exit_code = exit_code
        self.details = details
        super().__init__(message)


REQUIRED_SCHEMA6 = {
    "runs": ("run_id", "source_instance_id", "external_id", "created_at", "latest_revision_id"),
    "revisions": ("revision_id", "run_id", "content_hash", "adapter_version", "object_key", "published_at"),
    "attempts": ("attempt_id", "kind", "executor_id", "label", "probe", "status", "params_json",
                 "idempotency_key", "request_id", "config_fingerprint", "workspace", "log_path", "pid",
                 "exit_code", "error_code", "error_message", "outcome_json", "created_at", "queued_at",
                 "started_at", "ended_at", "heartbeat_at", "cancel_requested_at", "updated_at",
                 "deadline_at", "policy_revision"),
    "imports": ("receipt_id", "attempt_id", "run_id", "revision_id", "source_instance_id", "external_id",
                "adapter_version", "status", "reason", "imported_at"),
    "factors": ("factor_id", "name", "source_instance_id", "external_id", "definition_json", "dataset_id",
                "dataset_version", "snapshot_label", "calendar_id", "provenance_json", "created_at"),
    "factor_panels": ("panel_id", "factor_id", "content_hash", "object_key", "date_count",
                      "instrument_count", "cell_count", "valid_count", "start_date", "end_date",
                      "published_at"),
    "agent_budget": ("policy_revision", "scope", "kind", "used", "updated_at"),
}

# Columns/primary keys must stay byte-identical across the migration.
PRESERVED = {
    "revisions": (REQUIRED_SCHEMA6["revisions"], ("revision_id",)),
    "imports": (REQUIRED_SCHEMA6["imports"], ("receipt_id",)),
    "factors": (REQUIRED_SCHEMA6["factors"], ("factor_id",)),
    "factor_panels": (REQUIRED_SCHEMA6["factor_panels"], ("panel_id",)),
    "agent_budget": (REQUIRED_SCHEMA6["agent_budget"],
                     ("policy_revision", "scope", "kind")),
    "attempts": (REQUIRED_SCHEMA6["attempts"], ("attempt_id",)),
}

RUN_COLUMNS = ("run_id", "source_instance_id", "external_id", "created_at", "latest_revision_id")

SCHEMA7_TABLES = ("entities", "artifacts", "artifact_parents", "runs", "external_run_bindings",
                  "attempts", "commands", "stages", "attempt_events", "resource_leases",
                  "budget_scopes", "budget_entries", "workflow_instances", "workflow_edges",
                  "trial_events", "publications", "pointers", "legacy_artifact_bindings",
                  "source_checkpoints", "revisions", "imports", "factors", "factor_panels",
                  "agent_budget")

SCHEMA7_INDEXES = ("artifacts_type_created", "bindings_run", "runs_experiment", "attempts_run_no",
                   "attempts_launch_token", "resource_leases_open", "trial_events_candidate",
                   "revisions_run", "attempts_created", "attempts_status", "imports_attempt",
                   "imports_run", "factor_panels_factor")

# Each statement is executed separately: executescript() would implicitly commit
# and break the single-transaction guarantee required by PHYSICAL_CONTRACT §6.
SCHEMA7_STATEMENTS = (
    """CREATE TABLE entities (
 entity_id TEXT PRIMARY KEY, entity_kind TEXT NOT NULL,
 experiment_id TEXT REFERENCES entities(entity_id), display_name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 head_artifact_id TEXT REFERENCES artifacts(artifact_id), row_version INTEGER NOT NULL DEFAULT 0 CHECK(row_version>=0),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
)""",
    """CREATE TABLE artifacts (
 artifact_id TEXT PRIMARY KEY, artifact_type TEXT NOT NULL,
 schema_version INTEGER NOT NULL CHECK(schema_version>0), content_digest TEXT NOT NULL,
 entity_id TEXT REFERENCES entities(entity_id), object_key TEXT NOT NULL,
 producer_run_id TEXT REFERENCES runs(run_id), producer_attempt_id TEXT REFERENCES attempts(attempt_id),
 created_at TEXT NOT NULL, UNIQUE(entity_id,artifact_type,content_digest)
)""",
    "CREATE INDEX artifacts_type_created ON artifacts(artifact_type,created_at,artifact_id)",
    """CREATE TABLE artifact_parents (
 child_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 role TEXT NOT NULL, ordinal INTEGER NOT NULL CHECK(ordinal>=0),
 parent_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 PRIMARY KEY(child_id,role,ordinal), CHECK(child_id<>parent_id)
)""",
    """CREATE TABLE runs_new (
 run_id TEXT PRIMARY KEY, origin TEXT NOT NULL CHECK(origin IN ('managed','imported')),
 workflow_kind TEXT, experiment_id TEXT REFERENCES entities(entity_id),
 definition_id TEXT REFERENCES artifacts(artifact_id), plan_id TEXT REFERENCES artifacts(artifact_id),
 created_at TEXT NOT NULL, latest_revision_id TEXT,
 CHECK((origin='imported' AND definition_id IS NULL AND plan_id IS NULL AND workflow_kind IS NULL AND experiment_id IS NULL)
 OR (origin='managed' AND workflow_kind IS NOT NULL AND definition_id IS NOT NULL AND
 ((workflow_kind='data_prepare' AND experiment_id IS NULL AND plan_id IS NOT NULL)
 OR (workflow_kind<>'data_prepare' AND experiment_id IS NOT NULL AND plan_id IS NULL))))
)""",
    """INSERT INTO runs_new(run_id,origin,created_at,latest_revision_id)
 SELECT run_id,'imported',created_at,latest_revision_id FROM runs""",
    """CREATE TABLE external_run_bindings (
 source_instance_id TEXT NOT NULL, external_id TEXT NOT NULL,
 run_id TEXT NOT NULL REFERENCES runs(run_id), bound_at TEXT NOT NULL,
 PRIMARY KEY(source_instance_id,external_id)
)""",
    """INSERT INTO external_run_bindings
 SELECT source_instance_id,external_id,run_id,created_at FROM runs""",
    "DROP TABLE runs",
    "ALTER TABLE runs_new RENAME TO runs",
    "CREATE INDEX bindings_run ON external_run_bindings(run_id)",
    "CREATE INDEX runs_experiment ON runs(experiment_id,created_at,run_id)",
    "ALTER TABLE attempts ADD COLUMN run_id TEXT REFERENCES runs(run_id)",
    "ALTER TABLE attempts ADD COLUMN attempt_no INTEGER",
    "ALTER TABLE attempts ADD COLUMN definition_id TEXT REFERENCES artifacts(artifact_id)",
    "ALTER TABLE attempts ADD COLUMN admission_digest TEXT",
    "ALTER TABLE attempts ADD COLUMN process_identity_json TEXT",
    "ALTER TABLE attempts ADD COLUMN end_confirmed_at TEXT",
    "ALTER TABLE attempts ADD COLUMN launch_token TEXT",
    "CREATE UNIQUE INDEX attempts_run_no ON attempts(run_id,attempt_no) WHERE run_id IS NOT NULL",
    "CREATE UNIQUE INDEX attempts_launch_token ON attempts(launch_token) WHERE launch_token IS NOT NULL",
    """CREATE TABLE commands (
 idempotency_key TEXT PRIMARY KEY, operation TEXT NOT NULL, payload_digest TEXT NOT NULL,
 response_json TEXT NOT NULL, committed_at TEXT NOT NULL
)""",
    """CREATE TABLE stages (
 attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id), stage_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal>=0),
 state TEXT NOT NULL CHECK(state IN ('pending','running','succeeded','failed','skipped')),
 inputs_json TEXT NOT NULL, outputs_json TEXT NOT NULL, reason_code TEXT,
 started_at TEXT, ended_at TEXT, PRIMARY KEY(attempt_id,stage_id), UNIQUE(attempt_id,ordinal)
)""",
    """CREATE TABLE attempt_events (
 attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id), seq INTEGER NOT NULL CHECK(seq>0),
 event_type TEXT NOT NULL, evidence_json TEXT NOT NULL, occurred_at TEXT NOT NULL,
 PRIMARY KEY(attempt_id,seq)
)""",
    """CREATE TABLE resource_leases (
 attempt_id TEXT NOT NULL REFERENCES attempts(attempt_id), resource_scope TEXT NOT NULL,
 reserved_at TEXT NOT NULL, released_at TEXT, PRIMARY KEY(attempt_id,resource_scope)
)""",
    "CREATE INDEX resource_leases_open ON resource_leases(resource_scope) WHERE released_at IS NULL",
    """CREATE TABLE budget_scopes (
 scope_id TEXT NOT NULL, dimension TEXT NOT NULL,
 policy_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 limit_value INTEGER NOT NULL CHECK(limit_value>=0), used_value INTEGER NOT NULL CHECK(used_value>=0),
 PRIMARY KEY(scope_id,dimension)
)""",
    """CREATE TABLE budget_entries (
 entry_id TEXT PRIMARY KEY, scope_id TEXT NOT NULL, dimension TEXT NOT NULL,
 event_key TEXT NOT NULL, attempt_id TEXT REFERENCES attempts(attempt_id),
 amount INTEGER NOT NULL CHECK(amount>=0), kind TEXT NOT NULL CHECK(kind IN ('reserve','legacy_opening')),
 created_at TEXT NOT NULL, FOREIGN KEY(scope_id,dimension) REFERENCES budget_scopes(scope_id,dimension),
 UNIQUE(scope_id,dimension,event_key)
)""",
    """CREATE TABLE workflow_instances (
 workflow_id TEXT PRIMARY KEY REFERENCES entities(entity_id),
 workflow_revision_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), row_version INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
)""",
    """CREATE TABLE workflow_edges (
 workflow_id TEXT NOT NULL REFERENCES workflow_instances(workflow_id),
 workflow_revision_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 parent_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id), child_kind TEXT NOT NULL,
 child_run_id TEXT NOT NULL REFERENCES runs(run_id), created_at TEXT NOT NULL,
 PRIMARY KEY(parent_artifact_id,child_kind,workflow_revision_id), UNIQUE(child_run_id)
)""",
    """CREATE TABLE trial_events (
 event_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL REFERENCES entities(entity_id),
 workflow_id TEXT REFERENCES workflow_instances(workflow_id), candidate_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 run_id TEXT REFERENCES runs(run_id), attempt_id TEXT REFERENCES attempts(attempt_id),
 event_kind TEXT NOT NULL, details_json TEXT NOT NULL, occurred_at TEXT NOT NULL
)""",
    "CREATE INDEX trial_events_candidate ON trial_events(candidate_id,occurred_at,event_id)",
    """CREATE TABLE publications (
 publication_id TEXT PRIMARY KEY, attempt_id TEXT REFERENCES attempts(attempt_id),
 stage_id TEXT, artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 publication_key TEXT NOT NULL UNIQUE, committed_at TEXT NOT NULL
)""",
    """CREATE TABLE pointers (
 pointer_name TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 row_version INTEGER NOT NULL CHECK(row_version>=0), updated_at TEXT NOT NULL
)""",
    """CREATE TABLE legacy_artifact_bindings (
 legacy_kind TEXT NOT NULL, legacy_id TEXT NOT NULL,
 artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 PRIMARY KEY(legacy_kind,legacy_id)
)""",
    """CREATE TABLE source_checkpoints (
 plan_id TEXT NOT NULL REFERENCES artifacts(artifact_id), chunk_key TEXT NOT NULL,
 raw_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
 completed_at TEXT NOT NULL, PRIMARY KEY(plan_id,chunk_key)
)""",
)


def database_path(root: str | Path) -> Path:
    return Path(root).expanduser().resolve() / "workbench.sqlite3"


def _read_only(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _canonical_row(values: Iterable[Any]) -> str:
    return json.dumps(list(values), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(conn: sqlite3.Connection, table: str, columns: tuple[str, ...],
            primary_key: tuple[str, ...]) -> dict[str, Any]:
    order = ",".join(primary_key)
    rows = conn.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY {order}").fetchall()
    digest = hashlib.sha256("\n".join(_canonical_row(row) for row in rows).encode("utf-8")).hexdigest()
    return {"count": len(rows), "digest": "sha256:" + digest}


def preserved_fingerprint(conn: sqlite3.Connection) -> dict[str, Any]:
    return {table: _digest(conn, table, columns, primary_key)
            for table, (columns, primary_key) in PRESERVED.items()}


def _run_mapping(conn: sqlite3.Connection) -> list[list[Any]]:
    rows = conn.execute(
        "SELECT run_id,source_instance_id,external_id,created_at,latest_revision_id "
        "FROM runs ORDER BY run_id").fetchall()
    return [[row[column] for column in RUN_COLUMNS] for row in rows]


def _migrated_run_mapping(conn: sqlite3.Connection) -> list[list[Any]]:
    rows = conn.execute(
        "SELECT r.run_id,b.source_instance_id,b.external_id,r.created_at,r.latest_revision_id "
        "FROM runs r LEFT JOIN external_run_bindings b ON b.run_id=r.run_id ORDER BY r.run_id").fetchall()
    return [[row[column] for column in RUN_COLUMNS] for row in rows]


def open_attempts(root: str | Path) -> list[dict[str, Any]]:
    """Attempts without confirmed end evidence; interrupted is never assumed ended."""
    conn = _read_only(database_path(root))
    try:
        rows = conn.execute(
            "SELECT attempt_id,status,ended_at,exit_code,error_code FROM attempts "
            "WHERE status NOT IN (?,?,?) OR ended_at IS NULL ORDER BY attempt_id",
            TERMINAL_WITH_END).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def status(root: str | Path) -> dict[str, Any]:
    """Read-only status; missing database is reported, never created."""
    db = database_path(root)
    root_path = Path(root).expanduser().resolve()
    if not db.is_file():
        return {"database": str(db), "exists": False, "user_version": None,
                "supported_schema": SUPPORTED_SCHEMA, "open_attempts": [],
                "object_store_root": str(root_path / "objects"), "object_store_exists": (root_path / "objects").is_dir()}
    conn = _read_only(db)
    try:
        version = _user_version(conn)
        tables = sorted(_tables(conn))
        attempts = [dict(row) for row in conn.execute(
            "SELECT attempt_id,status,ended_at,exit_code,error_code FROM attempts "
            "WHERE status NOT IN (?,?,?) OR ended_at IS NULL ORDER BY attempt_id",
            TERMINAL_WITH_END).fetchall()]
        return {"database": str(db), "exists": True, "user_version": version,
                "supported_schema": SUPPORTED_SCHEMA, "tables": tables,
                "open_attempts": attempts, "target_schema_tables": list(SCHEMA7_TABLES),
                "object_store_root": str(root_path / "objects"),
                "object_store_exists": (root_path / "objects").is_dir()}
    finally:
        conn.close()


def _check_schema6(conn: sqlite3.Connection) -> None:
    tables = _tables(conn)
    missing = sorted(set(REQUIRED_SCHEMA6) - tables)
    if missing:
        raise MigrationError("migration_schema_mismatch", "missing schema6 table(s): " + ", ".join(missing))
    for table, columns in REQUIRED_SCHEMA6.items():
        actual = _columns(conn, table)
        absent = [column for column in columns if column not in actual]
        if absent:
            raise MigrationError("migration_schema_mismatch",
                                 f"{table} is missing column(s): " + ", ".join(absent))


def _check_confirmations(conn: sqlite3.Connection, confirmed: Iterable[str]) -> list[dict[str, Any]]:
    needed_rows = conn.execute(
        "SELECT attempt_id,status,ended_at,exit_code,error_code FROM attempts "
        "WHERE status NOT IN (?,?,?) OR ended_at IS NULL ORDER BY attempt_id",
        TERMINAL_WITH_END).fetchall()
    needed = {row["attempt_id"] for row in needed_rows}
    provided = list(confirmed)
    if len(provided) != len(set(provided)):
        raise MigrationError("migration_invalid_confirmation", "confirmed attempt ids must be unique")
    unknown = sorted(set(provided) - needed)
    if unknown:
        raise MigrationError("migration_invalid_confirmation",
                             "confirmation does not match an open/no-end attempt: " + ", ".join(unknown))
    if set(provided) != needed:
        missing = sorted(needed - set(provided))
        raise MigrationError(
            "migration_blocked_open_attempts",
            "open or end-evidence-missing attempts require explicit confirmation",
            open_attempts=[dict(row) for row in needed_rows], unconfirmed=missing)
    return [dict(row) for row in needed_rows]


def _verify_in_transaction(conn: sqlite3.Connection, before: dict[str, Any],
                           runs_before: list[list[Any]]) -> dict[str, Any]:
    after = preserved_fingerprint(conn)
    mismatched = [table for table in before if before[table] != after[table]]
    if mismatched:
        raise MigrationError("migration_conservation_failed",
                             "legacy rows changed: " + ", ".join(sorted(mismatched)))
    runs_after = _migrated_run_mapping(conn)
    if runs_after != runs_before:
        raise MigrationError("migration_conservation_failed", "Run/external binding mapping changed")
    if conn.execute("SELECT count(*) FROM external_run_bindings").fetchone()[0] != len(runs_before):
        raise MigrationError("migration_conservation_failed", "binding count does not match legacy Run count")
    bad_latest = conn.execute(
        "SELECT count(*) FROM runs r WHERE r.latest_revision_id IS NOT NULL AND NOT EXISTS "
        "(SELECT 1 FROM revisions v WHERE v.revision_id=r.latest_revision_id AND v.run_id=r.run_id)"
    ).fetchone()[0]
    if bad_latest:
        raise MigrationError("migration_conservation_failed", "latest_revision_id is not owned by its Run")
    foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
    if foreign:
        raise MigrationError("migration_conservation_failed", f"foreign_key_check returned {len(foreign)} row(s)")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise MigrationError("migration_conservation_failed", f"integrity_check={integrity}")
    return {"preserved": after, "runs": len(runs_after), "bindings": len(runs_after),
            "foreign_key_check": "ok", "integrity_check": integrity}


def migrate(root: str | Path, backup_path: str | Path,
            confirmed_attempts: Iterable[str] = ()) -> dict[str, Any]:
    """Perform the explicit schema6→7 migration; caller owns scheduling/backup path."""
    db = database_path(root)
    if not db.is_file():
        raise MigrationError("migration_database_missing", f"database does not exist: {db}")
    backup = Path(backup_path).expanduser()
    conn = _read_only(db)
    try:
        version = _user_version(conn)
        if version == TARGET_SCHEMA:
            # Repeatable maintenance command: never re-run or overwrite a backup.
            return {"source_version": TARGET_SCHEMA, "target_version": TARGET_SCHEMA, "changed": False,
                    "backup_path": None, "backup_digest": None, "open_attempts": [], "preserved": {},
                    "postcheck": "already_at_target"}
        if version != SOURCE_SCHEMA:
            raise MigrationError("migration_unknown_schema",
                                 f"database schema {version}; migration supports {SOURCE_SCHEMA}→{TARGET_SCHEMA}")
        _check_schema6(conn)
        confirmed = _check_confirmations(conn, confirmed_attempts)
        before = preserved_fingerprint(conn)
        runs_before = _run_mapping(conn)
    finally:
        conn.close()

    if backup.exists():
        raise MigrationError("migration_backup_exists", f"refusing to overwrite existing backup: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(db, timeout=30)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    backup_digest = "sha256:" + hashlib.sha256(backup.read_bytes()).hexdigest()

    writer = sqlite3.connect(db, timeout=30, isolation_level=None)
    writer.row_factory = sqlite3.Row
    try:
        writer.execute("PRAGMA foreign_keys=OFF")
        writer.execute("BEGIN IMMEDIATE")
        try:
            for statement in SCHEMA7_STATEMENTS:
                writer.execute(statement)
            postcheck = _verify_in_transaction(writer, before, runs_before)
            writer.execute(f"PRAGMA user_version={TARGET_SCHEMA}")
            writer.execute("COMMIT")
        except BaseException as exc:
            writer.execute("ROLLBACK")
            if isinstance(exc, MigrationError) and exc.exit_code == 3:
                details = dict(exc.details)
                details.setdefault("backup_path", str(backup))
                details.setdefault("backup_digest", backup_digest)
                raise MigrationError(exc.code, str(exc), exit_code=4, **details) from None
            raise
    except MigrationError:
        raise
    except sqlite3.Error as exc:
        raise MigrationError("migration_failed", f"{type(exc).__name__}: {exc}",
                             exit_code=4, backup_path=str(backup), backup_digest=backup_digest) from None
    finally:
        writer.close()

    report = verify(db)
    return {"source_version": SOURCE_SCHEMA, "target_version": TARGET_SCHEMA, "changed": True,
            "backup_path": str(backup), "backup_digest": backup_digest,
            "open_attempts": [row["attempt_id"] for row in confirmed],
            "preserved": postcheck["preserved"], "postcheck": report}


def verify(path: str | Path) -> dict[str, Any]:
    """Read-only schema7 verification used by migrate and `storage verify`."""
    db = Path(path).expanduser().resolve()
    if not db.is_file():
        raise MigrationError("migration_database_missing", f"database does not exist: {db}")
    conn = _read_only(db)
    try:
        version = _user_version(conn)
        if version != TARGET_SCHEMA:
            raise MigrationError("migration_unknown_schema",
                                 f"database schema {version}; verify expects {TARGET_SCHEMA}")
        tables = _tables(conn)
        missing_tables = sorted(set(SCHEMA7_TABLES) - tables)
        if missing_tables:
            raise MigrationError("migration_schema_mismatch", "missing table(s): " + ", ".join(missing_tables))
        indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        missing_indexes = sorted(set(SCHEMA7_INDEXES) - indexes)
        if missing_indexes:
            raise MigrationError("migration_schema_mismatch", "missing index(es): " + ", ".join(missing_indexes))
        foreign = conn.execute("PRAGMA foreign_key_check").fetchall()
        if foreign:
            raise MigrationError("migration_integrity_failed", f"foreign_key_check returned {len(foreign)} row(s)")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise MigrationError("migration_integrity_failed", f"integrity_check={integrity}")
        bad_latest = conn.execute(
            "SELECT count(*) FROM runs r WHERE r.latest_revision_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM revisions v WHERE v.revision_id=r.latest_revision_id AND v.run_id=r.run_id)"
        ).fetchone()[0]
        if bad_latest:
            raise MigrationError("migration_integrity_failed", "latest_revision_id is not owned by its Run")
        orphan_imports = conn.execute(
            "SELECT count(*) FROM runs r WHERE r.origin='imported' AND NOT EXISTS "
            "(SELECT 1 FROM external_run_bindings b WHERE b.run_id=r.run_id)"
        ).fetchone()[0]
        wrong_binding = conn.execute(
            "SELECT count(*) FROM external_run_bindings b JOIN runs r ON r.run_id=b.run_id "
            "WHERE r.origin<>'imported'"
        ).fetchone()[0]
        if orphan_imports or wrong_binding:
            raise MigrationError("migration_integrity_failed",
                                 "external_run_bindings do not match imported Runs")
        return {"schema_version": version, "tables": len(tables), "indexes": len(indexes),
                "foreign_key_check": "ok", "integrity_check": integrity,
                "latest_revision_orphans": 0, "orphan_imported_runs": 0,
                "bindings_on_non_imported_runs": 0}
    finally:
        conn.close()
