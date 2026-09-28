import copy
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from quant_workbench.adapters.json_result import JsonResultImporter
from quant_workbench.adapters.rdagent_status import RDAgentStatusProvider
from quant_workbench.application import WorkbenchService
from quant_workbench.dashboard import validate_dashboard
from quant_workbench.model import ContractError, validate_package
from quant_workbench.storage import LocalResultRepository, SchemaVersionError


FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "generic-result.json"
DASHBOARD = Path(__file__).resolve().parents[1] / "examples" / "dashboard.default.json"


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = LocalResultRepository(self.root)
        self.service = WorkbenchService(self.repo)
        self.package = JsonResultImporter().load(FIXTURE)

    def tearDown(self):
        self.temp.cleanup()

    def test_core_imports_without_qlib_or_mlflow(self):
        script = "import sys; import quant_workbench.application; assert 'qlib' not in sys.modules and 'mlflow' not in sys.modules"
        subprocess.run([sys.executable, "-c", script], check=True)

    def test_contract_handles_workflow_axes_and_rejects_false_values(self):
        queued = copy.deepcopy(self.package)
        queued["run"].update(status="queued", started_at=None, ended_at=None)
        validate_package(queued)
        queued["run"]["started_at"] = "2021-01-01T00:00:00+00:00"
        with self.assertRaises(ContractError):
            validate_package(queued)
        broken = copy.deepcopy(self.package)
        broken["series"][0]["points"][0]["value"] = float("nan")
        with self.assertRaises(ContractError):
            validate_package(broken)
        broken = copy.deepcopy(self.package)
        broken["series"][0]["points"][0]["value"] = None
        with self.assertRaises(ContractError):
            validate_package(broken)
        self.assertEqual(len(self.package["run"]["stages"]), 2)
        self.assertEqual({x["axis"] for x in self.package["series"]}, {"trading_date", "step", "scalar"})

    def test_dashboard_registered_queries_and_layout(self):
        dashboard = validate_dashboard(json.loads(DASHBOARD.read_text()))
        self.assertEqual(len(dashboard["widgets"]), 3)
        duplicate = copy.deepcopy(dashboard)
        duplicate["widgets"].append(copy.deepcopy(duplicate["widgets"][0]))
        with self.assertRaises(ContractError):
            validate_dashboard(duplicate)
        invalid = copy.deepcopy(dashboard)
        invalid["widgets"][0]["query"] = {"id": "SELECT * FROM runs"}
        with self.assertRaises(ContractError):
            validate_dashboard(invalid)
        invalid = copy.deepcopy(dashboard)
        invalid["widgets"][0]["layout"]["w"] = 13
        with self.assertRaises(ContractError):
            validate_dashboard(invalid)

    def test_idempotence_cross_source_and_revision_history(self):
        first = self.service.import_package("fixture-A", "ext-1", "json-v1", self.package)
        second = self.service.import_package("fixture-A", "ext-1", "json-v1", self.package)
        self.assertEqual(first["revision_id"], second["revision_id"])
        self.assertFalse(second["created"])
        other = self.service.import_package("fixture-B", "ext-1", "json-v1", self.package)
        self.assertNotEqual(first["run_id"], other["run_id"])
        changed = copy.deepcopy(self.package)
        changed["series"][0]["points"][-1]["value"] = 999800
        newer = self.service.import_package("fixture-A", "ext-1", "json-v1", changed)
        self.assertEqual(first["run_id"], newer["run_id"])
        self.assertNotEqual(first["revision_id"], newer["revision_id"])
        old = self.service.get_revision(first["run_id"], first["revision_id"])
        self.assertEqual(old["result"]["series"][0]["points"][-1]["value"], 999700)
        self.assertEqual(len(self.service.list_revisions(first["run_id"])), 2)

    def test_publish_interruption_and_backup_restore(self):
        def crash():
            raise RuntimeError("injected before commit")
        failing = LocalResultRepository(self.root, before_commit=crash)
        with self.assertRaisesRegex(RuntimeError, "injected"):
            failing.publish("fixture", "ext", "v1", self.package)
        self.assertEqual(self.service.list_runs()["items"], [])
        saved = self.service.import_package("fixture", "ext", "v1", self.package)
        backup = self.root.parent / (self.root.name + "-backup")
        shutil.copytree(self.root, backup)
        restored = WorkbenchService(LocalResultRepository(backup))
        self.assertEqual(restored.get_run(saved["run_id"])["revision_id"], saved["revision_id"])
        shutil.rmtree(backup)

    def test_unknown_database_schema_refused(self):
        with sqlite3.connect(self.repo.db) as conn:
            conn.execute("PRAGMA user_version=99")
        with self.assertRaises(SchemaVersionError):
            LocalResultRepository(self.root)

    def test_cli_and_http_use_same_service_dto(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app

        imported = self.service.import_package("fixture", "ext", "json-v1", self.package)
        api = TestClient(create_app(self.service))
        expected = self.service.get_series(imported["run_id"], "platform.equity", limit=2)
        response = api.get(f"/v1/runs/{imported['run_id']}/series", params={"metric_id": "platform.equity", "limit": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        cmd = subprocess.run([sys.executable, "-m", "quant_workbench.cli", "--root", str(self.root),
                              "series", imported["run_id"], "platform.equity", "--limit", "2"],
                             check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(cmd.stdout), expected)
        not_found = api.get("/v1/runs/absent")
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(not_found.json()["request_id"], not_found.headers["X-Request-ID"])
        invalid = api.get("/v1/runs?limit=101")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["request_id"], invalid.headers["X-Request-ID"])
        self.assertEqual(api.get("/").status_code, 200)
        self.assertIn("Quant Workbench", api.get("/").text)
        self.assertIn('type="module"', api.get("/").text)
        for asset in ("app.js", "state.js", "transport.js"):
            response = api.get("/ui/" + asset)
            self.assertEqual(response.status_code, 200, asset)
            self.assertIn("javascript", response.headers["content-type"])
        self.assertEqual(api.get("/ui/not-packaged.js").status_code, 404)
        self.assertEqual(api.get("/v1/dashboards/overview").json()["dashboard_id"], "overview")
        stats = api.get("/v1/widgets/api.error_rate.5m").json()
        self.assertEqual(stats["availability"], "available")
        self.assertGreater(stats["data"]["completed_requests"], 0)
        bad = subprocess.run([sys.executable, "-m", "quant_workbench.cli", "--root", str(self.root),
                              "series", "absent", "platform.equity"], capture_output=True)
        self.assertNotEqual(bad.returncode, 0)

    def test_series_pagination_and_comparison(self):
        a = self.service.import_package("a", "one", "json-v1", self.package)["run_id"]
        b = self.service.import_package("b", "two", "json-v1", self.package)["run_id"]
        page = self.service.get_series(a, "platform.equity", limit=2)
        self.assertEqual(len(page["series"]["points"]), 2)
        self.assertEqual(page["next_offset"], 2)
        self.assertEqual(len(self.service.get_series(a, "platform.equity", limit=2, offset=2)["series"]["points"]), 1)
        self.assertEqual(self.service.compare([a, b], "platform.equity")["status"], "partial")
        with self.assertRaises(ValueError):
            self.service.get_series(a, "platform.equity", limit=2001)

    def test_rdagent_status_is_read_only_and_redacts_keys(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app

        agent_root = self.root / "RD-Agent"
        (agent_root / ".git").mkdir(parents=True)
        (agent_root / ".env").write_text(
            "CHAT_MODEL=deepseek/deepseek-flash\nDEEPSEEK_API_KEY=secret-test-value\n"
        )
        trace = agent_root / "git_ignore_folder" / "traces" / "Finance Data Building" / "demo"
        trace.mkdir(parents=True)
        observed = RDAgentStatusProvider(agent_root)
        status = observed.status()
        self.assertTrue(status["chat"]["configured"])
        self.assertFalse(status["embedding"]["configured"])
        self.assertEqual(status["traces"][0]["id"], "demo")
        self.assertNotIn("secret-test-value", json.dumps(status))
        self.assertFalse(status["baseline"]["verified"])
        (agent_root / "git_ignore_folder" / "qwb_cn_factor_template").mkdir()
        (agent_root / "git_ignore_folder" / "qwb_factor_smoke.json").write_text(json.dumps({
            "schema_version": 1, "mode": "baseline", "dataset": "synthetic_cn_demo",
            "template": "qwb_cn_factor_template", "metric_count": 19,
        }))
        status = observed.status()
        self.assertTrue(status["baseline"]["verified"])
        self.assertNotIn("factor_image_unverified", status["execution"]["reasons"])
        self.assertNotIn("secret-test-value", json.dumps(status))
        service = WorkbenchService(self.repo, observed)
        self.assertEqual(TestClient(create_app(service)).get("/v1/agents/rdagent").json(), status)


if __name__ == "__main__":
    unittest.main()
