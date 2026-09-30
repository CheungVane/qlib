"""Explicit schema6→7 maintenance migration, conservation and CLI behavior."""
import contextlib
import hashlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quant_workbench import cli
from quant_workbench.adapters.storage import migrations
from quant_workbench.adapters.storage.storage import LocalResultRepository
from quant_workbench.adapters.storage.storage_base import SCHEMA_VERSION, SchemaVersionError


def seed(repo, extra_attempts=()):
    attempts = [("A1", "succeeded", "2026-09-30T00:00:02.000Z"),
                ("A2", "failed", "2026-09-30T00:00:03.000Z"), *extra_attempts]
    with repo._connection() as conn:
        for run_id, external in (("R1", "ext1"), ("R2", "ext2")):
            conn.execute(
                "INSERT INTO runs(run_id,source_instance_id,external_id,created_at,latest_revision_id) "
                "VALUES(?,?,?,?,?)",
                (run_id, "src", external, "2026-09-30T00:00:00.000Z", None))
        conn.execute(
            "INSERT INTO revisions(revision_id,run_id,content_hash,adapter_version,object_key,published_at) "
            "VALUES(?,?,?,?,?,?)",
            ("V1", "R1", "content-hash", "adapter-1", "objects/v1.json", "2026-09-30T00:00:01.000Z"))
        for attempt_id, status, ended_at in attempts:
            conn.execute(
                "INSERT INTO attempts(attempt_id,kind,executor_id,label,status,idempotency_key,"
                "created_at,queued_at,started_at,ended_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (attempt_id, "qlib.cn_synthetic_backtest", "qlib_subprocess", attempt_id, status,
                 "key-" + attempt_id, "2026-09-30T00:00:00.000Z", "2026-09-30T00:00:00.000Z",
                 "2026-09-30T00:00:01.000Z", ended_at, "2026-09-30T00:00:04.000Z"))
        conn.execute(
            "INSERT INTO imports(receipt_id,attempt_id,run_id,revision_id,source_instance_id,external_id,"
            "adapter_version,status,reason,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("I1", "A1", "R1", "V1", "src", "ext1", "adapter-1", "imported", None,
             "2026-09-30T00:00:05.000Z"))
        conn.execute(
            "INSERT INTO factors(factor_id,name,source_instance_id,external_id,created_at) VALUES(?,?,?,?,?)",
            ("F1", "factor-1", "src", "fext", "2026-09-30T00:00:00.000Z"))
        conn.execute(
            "INSERT INTO factor_panels(panel_id,factor_id,content_hash,object_key,date_count,"
            "instrument_count,cell_count,valid_count,published_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("P1", "F1", "panel-hash", "objects/p1.json", 10, 5, 50, 40, "2026-09-30T00:00:00.000Z"))
        conn.execute(
            "INSERT INTO agent_budget(policy_revision,scope,kind,used,updated_at) VALUES(?,?,?,?,?)",
            ("policy-1", "global", "calls", 3, "2026-09-30T00:00:00.000Z"))


def counts(path, tables=("runs", "revisions", "imports", "factors", "factor_panels", "agent_budget")):
    conn = sqlite3.connect(path)
    try:
        return {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
    finally:
        conn.close()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "store"
        self.db = migrations.database_path(self.root)
        self.backup = Path(self._tmp.name) / "backup.sqlite3"
        self.repo = LocalResultRepository(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_supported_schema_matches_running_store(self):
        self.assertEqual(SCHEMA_VERSION, migrations.SUPPORTED_SCHEMA)

    def test_status_does_not_create_a_missing_database(self):
        missing = Path(self._tmp.name) / "absent"
        report = migrations.status(missing)
        self.assertFalse(report["exists"])
        self.assertFalse(migrations.database_path(missing).exists())

    def test_migration_preserves_rows_and_schema7_refuses_schema6_startup(self):
        seed(self.repo)
        before = counts(self.db)
        status = migrations.status(self.root)
        self.assertEqual(6, status["user_version"])
        self.assertEqual([], status["open_attempts"])

        receipt = migrations.migrate(self.root, self.backup)
        self.assertTrue(receipt["changed"])
        self.assertEqual((6, 7), (receipt["source_version"], receipt["target_version"]))
        self.assertEqual("sha256:" + hashlib.sha256(self.backup.read_bytes()).hexdigest(),
                         receipt["backup_digest"])
        self.assertEqual(before, counts(self.db))
        self.assertEqual("ok", migrations.verify(self.db)["integrity_check"])

        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(7, conn.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(2, conn.execute("SELECT count(*) FROM runs").fetchone()[0])
            self.assertEqual(2, conn.execute("SELECT count(*) FROM external_run_bindings").fetchone()[0])
            self.assertEqual("V1", conn.execute("SELECT revision_id FROM revisions").fetchone()[0])
            columns = [row[1] for row in conn.execute("PRAGMA table_info(attempts)")]
            self.assertIn("launch_token", columns)
            self.assertIn("run_id", columns)
        finally:
            conn.close()

        with self.assertRaises(SchemaVersionError):
            LocalResultRepository(self.root)
        again = migrations.migrate(self.root, self.backup)
        self.assertFalse(again["changed"])
        self.assertTrue(self.backup.exists())

    def test_open_or_end_evidence_missing_attempts_require_exact_confirmation(self):
        seed(self.repo, extra_attempts=[("A3", "running", None), ("A4", "interrupted",
                                                                  "2026-09-30T00:00:03.000Z")])
        status = migrations.status(self.root)
        self.assertEqual({"A3", "A4"}, {row["attempt_id"] for row in status["open_attempts"]})
        for provided, code in (([], "migration_blocked_open_attempts"),
                               (["A3"], "migration_blocked_open_attempts"),
                               (["A3", "NOPE"], "migration_invalid_confirmation"),
                               (["A3", "A3", "A4"], "migration_invalid_confirmation")):
            with self.subTest(provided=provided), self.assertRaises(migrations.MigrationError) as caught:
                migrations.migrate(self.root, self.backup, provided)
            self.assertEqual(code, caught.exception.code)
        self.assertFalse(self.backup.exists())
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(6, conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()
        receipt = migrations.migrate(self.root, self.backup, ["A3", "A4"])
        self.assertTrue(receipt["changed"])
        self.assertEqual(["A3", "A4"], receipt["open_attempts"])

    def test_unknown_schema_is_refused_without_touching_the_database(self):
        conn = sqlite3.connect(self.db)
        conn.execute("PRAGMA user_version=5")
        conn.close()
        with self.assertRaises(migrations.MigrationError) as caught:
            migrations.migrate(self.root, self.backup)
        self.assertEqual("migration_unknown_schema", caught.exception.code)
        self.assertFalse(self.backup.exists())

    def test_failed_statement_rolls_back_and_keeps_backup(self):
        seed(self.repo)
        broken = ("CREATE TABLE entities (entity_id TEXT PRIMARY KEY)", "SELECT * FROM no_such_table")
        with patch.object(migrations, "SCHEMA7_STATEMENTS", broken):
            with self.assertRaises(migrations.MigrationError) as caught:
                migrations.migrate(self.root, self.backup)
        self.assertEqual("migration_failed", caught.exception.code)
        self.assertEqual(4, caught.exception.exit_code)
        self.assertTrue(self.backup.exists())
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(6, conn.execute("PRAGMA user_version").fetchone()[0])
            columns = [row[1] for row in conn.execute("PRAGMA table_info(runs)")]
            self.assertIn("source_instance_id", columns)
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("entities", tables)
        finally:
            conn.close()

    def test_cli_status_and_blocked_migrate_exit_codes(self):
        seed(self.repo, extra_attempts=[("A3", "running", None)])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(0, cli.main(["--root", str(self.root), "storage", "status", "--json"]))
        self.assertEqual(6, __import__("json").loads(out.getvalue())["user_version"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = cli.main(["--root", str(self.root), "storage", "migrate",
                             "--backup", str(self.backup), "--json"])
        self.assertEqual(3, code)
        self.assertEqual("migration_blocked_open_attempts", __import__("json").loads(err.getvalue())["code"])


if __name__ == "__main__":
    unittest.main()
