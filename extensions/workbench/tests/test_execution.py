import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from quant_workbench.adapters.executors import SubprocessExecutor
from quant_workbench.application import WorkbenchService
from quant_workbench.execution import (
    ExecutionService, PreconditionFailed, attempt_dto, utc_now,
)
from quant_workbench.storage import LocalResultRepository, SCHEMA_VERSION


class StubExecutor(SubprocessExecutor):
    """Real subprocess lifecycle with cheap commands; no engine is started."""

    executor_id = "stub_subprocess"
    kinds = ("stub.sleep", "stub.exit")

    def __init__(self, root: Path, available: bool = True):
        super().__init__(repo_root=root, source_root=root)
        self.available = available
        self.outcome_calls = 0

    def checks(self):
        return [{"id": "stub.ready", "status": "ok" if self.available else "missing",
                 "detail": "stub is ready" if self.available else "stub is disabled",
                 "required_for": list(self.kinds)}]

    def describe(self, kind):
        return {"label": f"stub {kind}", "description": "test entry", "probe": False,
                "data_nature": "test", "params": [{"name": "seconds", "type": "string", "required": False},
                                                   {"name": "script", "type": "string", "required": False}]}

    def workspace(self, attempt_id, kind, params):
        return self.repo_root / "runs" / f"{attempt_id}-{kind.replace('.', '_')}"

    def command(self, attempt_id, kind, params, run_dir):
        if kind == "stub.sleep":
            return ["/bin/sh", "-c", "sleep %s" % (params.get("seconds") or "30")]
        return ["/bin/sh", "-c", params.get("script") or "exit 0"]

    def config_fingerprint(self):
        return "f" * 64

    def outcome(self, attempt):
        self.outcome_calls += 1
        return {"result_import": "manual_import_required", "artifacts": {"workspace": Path(attempt["workspace"]).name}}


class RacingExecutor(StubExecutor):
    """Cancelling while a refresh reconciles the just-killed process."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.service = None

    def poll(self, attempt):
        return {"state": "interrupted", "exit_code": None,
                "error_code": "process_lost_without_exit_evidence",
                "error_message": "process exited with -15 but wrote no exit marker",
                "ended_at": utc_now(), "evidence": {"exit_marker": False}}

    def cancel(self, attempt):
        # the UI refresh runs concurrently with the cancel signal
        self.service.reconcile([attempt["attempt_id"]])
        return {"confirmed": True, "state": "cancelled", "exit_code": None,
                "reason": "process_end_confirmed", "evidence": {"signals": ["SIGTERM"]}}


def wait_for(predicate, timeout=10.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        # find_repo_root() only accepts a candidate that looks like the checkout; mark the
        # sandbox so no stub attempt can leak work into the real working tree.
        (self.root / "configs/cn").mkdir(parents=True)
        (self.root / "configs/cn/profile.json").write_text("{}", encoding="utf-8")
        (self.root / "scripts").mkdir()
        self.repo = LocalResultRepository(self.root / "store")
        self.executor = StubExecutor(self.root)
        self.execution = ExecutionService(self.repo, [self.executor])
        self.service = WorkbenchService(self.repo, None, None, self.execution)

    def tearDown(self):
        for process in list(self.executor._processes.values()):
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        self.temp.cleanup()

    def submit(self, kind="stub.sleep", params=None, key=None):
        result = self.execution.submit(kind, params or {"seconds": "30"}, key or f"key-{time.time_ns()}", "req-1")
        return result

    # -- lifecycle -------------------------------------------------------
    def test_submit_is_idempotent_and_isolates_attempt_workspaces(self):
        first = self.submit(key="dup-key", params={"seconds": "30"})
        self.assertTrue(first["created"])
        second = self.submit(key="dup-key", params={"seconds": "30"})
        self.assertFalse(second["created"])
        self.assertEqual(first["attempt"]["attempt_id"], second["attempt"]["attempt_id"])
        self.assertEqual(self.repo.list_attempts()["items"].__len__(), 1)
        third = self.submit(key="other-key", params={"seconds": "30"})
        workspaces = {row["workspace"] for row in self.repo.list_attempts()["items"]}
        self.assertEqual(len(workspaces), 2)
        self.assertNotEqual(third["attempt"]["attempt_id"], first["attempt"]["attempt_id"])
        for row in self.repo.list_attempts()["items"]:
            workspace = Path(row["workspace"])
            self.assertTrue(workspace.is_dir())
            self.assertTrue(workspace.resolve().is_relative_to(self.root.resolve()), workspace)


    def test_confirmed_cancel_clears_a_racing_interrupted_label(self):
        executor = RacingExecutor(self.root)
        service = ExecutionService(self.repo, [executor])
        executor.service = service
        result = service.submit("stub.sleep", {"seconds": "30"}, "race-key", "req-race")
        attempt_id = result["attempt"]["attempt_id"]
        self.repo.update_attempt(attempt_id, status="running", pid=12345)

        cancelled = service.cancel(attempt_id)

        self.assertTrue(cancelled["cancel_confirmed"])
        self.assertEqual(cancelled["attempt"]["status"], "cancelled")
        self.assertIsNone(cancelled["attempt"]["error_code"])
        self.assertIsNone(cancelled["attempt"]["error_message"])

    def test_missing_preconditions_block_submission_without_attempt(self):
        self.executor.available = False
        with self.assertRaises(PreconditionFailed) as caught:
            self.submit(key="blocked-key")
        self.assertEqual(caught.exception.reasons, ["stub.ready"])
        self.assertEqual(self.repo.list_attempts()["items"], [])

    def test_crash_without_exit_marker_is_interrupted_not_succeeded(self):
        result = self.submit("stub.exit", {"script": "kill -9 $PPID"}, key="crash-key")
        attempt_id = result["attempt"]["attempt_id"]
        self.assertTrue(wait_for(lambda: self.execution.get(attempt_id)["status"] == "interrupted"))
        attempt = self.execution.get(attempt_id)
        self.assertIsNone(attempt["exit_code"])
        self.assertEqual(attempt["error_code"], "process_lost_without_exit_evidence")

    def test_nonzero_exit_is_failed_and_collects_outcome(self):
        result = self.submit("stub.exit", {"script": "exit 3"}, key="fail-key")
        attempt_id = result["attempt"]["attempt_id"]
        self.assertTrue(wait_for(lambda: self.execution.get(attempt_id)["status"] == "failed"))
        attempt = self.execution.get(attempt_id)
        self.assertEqual(attempt["exit_code"], 3)
        self.assertEqual(attempt["error_code"], "nonzero_exit")
        self.assertEqual(attempt["outcome"]["result_import"], "manual_import_required")
        self.assertEqual(self.executor.outcome_calls, 1)

    def test_success_requires_exit_evidence(self):
        result = self.submit("stub.exit", {"script": "exit 0"}, key="ok-key")
        attempt_id = result["attempt"]["attempt_id"]
        self.assertTrue(wait_for(lambda: self.execution.get(attempt_id)["status"] == "succeeded"))
        self.assertEqual(self.execution.get(attempt_id)["exit_code"], 0)

    # -- cancellation ----------------------------------------------------
    def test_cancel_waits_for_confirmed_process_end(self):
        result = self.submit("stub.sleep", {"seconds": "60"}, key="cancel-key")
        attempt_id = result["attempt"]["attempt_id"]
        cancelled = self.execution.cancel(attempt_id)
        self.assertTrue(cancelled["cancel_confirmed"])
        self.assertEqual(cancelled["attempt"]["status"], "cancelled")
        self.assertTrue(cancelled["attempt"]["cancel_requested_at"])
        self.assertFalse(cancelled["attempt"]["cancel_pending"])
        again = self.execution.cancel(attempt_id)
        self.assertFalse(again["cancel_confirmed"])
        self.assertEqual(again["reason"], "already_terminal")
        self.assertEqual(again["attempt"]["status"], "cancelled")

    def test_late_cancel_does_not_overwrite_real_terminal_evidence(self):
        result = self.submit("stub.exit", {"script": "exit 0"}, key="race-key")
        attempt_id = result["attempt"]["attempt_id"]
        row = self.repo.get_attempt(attempt_id)
        marker = Path(row["workspace"]) / "exit_code"
        self.assertTrue(wait_for(lambda: marker.is_file()), "exit marker was never written")
        outcome = self.execution.cancel(attempt_id)
        self.assertFalse(outcome["cancel_confirmed"])
        self.assertEqual(outcome["reason"], "terminal_evidence_wins")
        self.assertEqual(outcome["attempt"]["status"], "succeeded")
        self.assertEqual(outcome["attempt"]["exit_code"], 0)

    # -- API -------------------------------------------------------------
    def client(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app
        return TestClient(create_app(self.service))

    def test_http_writes_require_same_origin_and_are_idempotent(self):
        client = self.client()
        payload = {"kind": "stub.sleep", "params": {"seconds": "30"}, "idempotency_key": "http-key"}
        cross = client.post("/v1/executions", json=payload, headers={"Origin": "http://evil.test"})
        self.assertEqual(cross.status_code, 403)
        self.assertEqual(self.repo.list_attempts()["items"], [])
        preflight = client.post("/v1/executions", json=payload, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(preflight.status_code, 403)
        created = client.post("/v1/executions", json=payload, headers={"Origin": "http://testserver"})
        self.assertEqual(created.status_code, 201)
        replay = client.post("/v1/executions", json=payload, headers={"Origin": "http://testserver"})
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(created.json()["attempt"]["attempt_id"], replay.json()["attempt"]["attempt_id"])
        body = created.json()["attempt"]
        self.assertNotIn(str(self.root), json.dumps(body))
        self.assertTrue(body["workspace_label"])
        listed = client.get("/v1/executions").json()
        self.assertEqual(listed["items"][0]["attempt_id"], body["attempt_id"])
        fetched = client.get(f"/v1/executions/{body['attempt_id']}").json()
        self.assertEqual(fetched["status"], "running")

    def test_http_unknown_kind_and_blocked_preconditions(self):
        client = self.client()
        unknown = client.post("/v1/executions", json={"kind": "nope", "idempotency_key": "k1"})
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json()["code"], "unknown_kind")
        self.executor.available = False
        blocked = client.post("/v1/executions",
                              json={"kind": "stub.sleep", "idempotency_key": "k2", "params": {}})
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["code"], "precondition_failed")
        self.assertEqual(blocked.json()["details"]["reasons"], ["stub.ready"])
        self.assertEqual(self.repo.list_attempts()["items"], [])

    def test_read_endpoints_never_start_or_mutate_execution(self):
        client = self.client()
        client.get("/v1/executions")
        client.get("/v1/executions/catalog")
        self.assertEqual(self.repo.list_attempts()["items"], [])
        created = client.post("/v1/executions",
                              json={"kind": "stub.exit", "params": {"script": "exit 0"}, "idempotency_key": "ro-key"})
        attempt_id = created.json()["attempt"]["attempt_id"]
        self.assertTrue(wait_for(lambda: self.execution.get(attempt_id)["status"] == "succeeded"))
        client.get(f"/v1/executions/{attempt_id}")
        client.get("/v1/executions")
        row = self.repo.get_attempt(attempt_id)
        self.assertEqual(row["exit_code"], 0)
        self.assertEqual(self.executor.outcome_calls, 1)

    def test_log_tail_is_bounded_and_redacted(self):
        client = self.client()
        script = "echo 'token sk-abcdefghijklmnop1234'; echo done"
        created = client.post("/v1/executions",
                              json={"kind": "stub.exit", "params": {"script": script}, "idempotency_key": "log-key"})
        attempt_id = created.json()["attempt"]["attempt_id"]
        self.assertTrue(wait_for(lambda: self.execution.get(attempt_id)["status"] == "succeeded"))
        payload = client.get(f"/v1/executions/{attempt_id}/log?tail=20").json()
        self.assertTrue(payload["available"])
        text = "\n".join(payload["lines"])
        self.assertIn("done", text)
        self.assertNotIn("sk-abcdefghijklmnop1234", text)
        self.assertEqual(client.get(f"/v1/executions/{attempt_id}/log?tail=0").status_code, 422)
        self.assertEqual(client.get("/v1/executions/missing-attempt").status_code, 404)

    def test_cancel_endpoint_returns_confirmed_state(self):
        client = self.client()
        created = client.post("/v1/executions",
                              json={"kind": "stub.sleep", "params": {"seconds": "60"}, "idempotency_key": "http-cancel"})
        attempt_id = created.json()["attempt"]["attempt_id"]
        cancelled = client.post(f"/v1/executions/{attempt_id}/cancel")
        self.assertEqual(cancelled.status_code, 200)
        self.assertTrue(cancelled.json()["cancel_confirmed"])
        self.assertEqual(cancelled.json()["attempt"]["status"], "cancelled")
        self.assertEqual(client.post("/v1/executions/unknown/cancel").status_code, 404)

    # -- contract --------------------------------------------------------
    def test_storage_migrates_v1_without_touching_published_results(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        db = legacy / "workbench.sqlite3"
        with sqlite3.connect(db) as conn:
            conn.executescript("""
            CREATE TABLE runs (run_id TEXT PRIMARY KEY, source_instance_id TEXT NOT NULL, external_id TEXT NOT NULL,
                created_at TEXT NOT NULL, latest_revision_id TEXT, UNIQUE(source_instance_id, external_id));
            CREATE TABLE revisions (revision_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
                content_hash TEXT NOT NULL, adapter_version TEXT NOT NULL, object_key TEXT NOT NULL,
                published_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                UNIQUE(run_id, content_hash, adapter_version));
            CREATE INDEX revisions_run ON revisions(run_id, published_at);
            PRAGMA user_version=1;
            INSERT INTO runs(run_id,source_instance_id,external_id,created_at) VALUES('run-1','fixture','old','2026-01-01T00:00:00Z');
            """)
        migrated = LocalResultRepository(legacy)
        self.assertEqual(migrated.health()["schema_version"], SCHEMA_VERSION)
        with migrated._connect() as conn:
            self.assertEqual(conn.execute("SELECT external_id FROM runs").fetchone()[0], "old")
            self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE name='attempts'").fetchone())

    def test_unknown_schema_version_is_rejected(self):
        root = self.root / "future"
        root.mkdir()
        db = root / "workbench.sqlite3"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")
            conn.execute("PRAGMA user_version=99")
        from quant_workbench.storage import SchemaVersionError
        with self.assertRaises(SchemaVersionError):
            LocalResultRepository(root)

    def test_dto_hides_paths_and_credentials(self):
        row = {"attempt_id": "a", "kind": "k", "executor_id": "e", "label": "l", "probe": True, "status": "failed",
               "created_at": "2026-01-01T00:00:00Z", "params": {"api_key": "sk-secret-value-123456"},
               "workspace": "/Users/someone/private/run", "log_path": "/Users/someone/private/run/attempt.log",
               "error_message": "failed with sk-abcdefghijklmnop1234", "outcome": None, "idempotency_key": "key"}
        dto = attempt_dto(row)
        self.assertEqual(dto["workspace_label"], "run")
        self.assertNotIn("/Users/someone", json.dumps(dto))
        self.assertNotIn("sk-abcdefghijklmnop1234", json.dumps(dto))
        self.assertEqual(dto["params"]["api_key"], "[REDACTED]")

    def test_cli_and_http_share_the_execution_service(self):
        script = Path(__file__).resolve().parents[3] / "extensions/workbench/.venv/bin/qwb"
        if not script.is_file():
            self.skipTest("workbench virtualenv is not available")
        result = subprocess.run(
            [str(script), "--root", str(self.root / "cli-store"), "execution-catalog"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        kinds = {item["kind"] for item in payload["items"]}
        self.assertIn("qlib.cn_synthetic_backtest", kinds)
        self.assertIn("rdagent.factor.baseline", kinds)


if __name__ == "__main__":
    unittest.main()
