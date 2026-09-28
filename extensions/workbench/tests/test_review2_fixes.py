"""Regression gates for the second review (B-3/B-5/B-6/B-7 and identity split)."""

import json
import tempfile
import unittest
from pathlib import Path

from quant_workbench.application import WorkbenchService, display_run_title
from quant_workbench.execution import ExecutionService
from quant_workbench.storage import LocalResultRepository

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "extensions/workbench/examples/generic-result.json"


def package(title="synthetic run", version="content-v1"):
    payload = json.loads(FIXTURE.read_text())
    payload["run"]["title"] = title
    payload["run"]["dataset"] = {"id": "dataset1", "version": version}
    payload["series"] = payload["series"][:1]
    return payload


class Review2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repository = LocalResultRepository(Path(self.tmp.name))
        self.service = WorkbenchService(self.repository)

    def client(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app
        return TestClient(create_app(self.service))

    def test_revisions_are_paginated(self):
        run_id = self.service.import_package("test", "one", "generic_v1", package())["run_id"]
        for index in range(2):
            payload = package()
            payload["run"]["created_at"] = f"2021-07-0{index + 1}T00:00:00+00:00"
            self.service.import_package("test", "one", f"generic_v{index}", payload)
        first = self.service.list_revisions_page(run_id, limit=2)
        self.assertEqual(len(first["items"]), 2)
        self.assertTrue(first["next_cursor"])
        second = self.service.list_revisions_page(run_id, limit=2, cursor=first["next_cursor"])
        self.assertEqual(len(second["items"]), 1)
        self.assertIsNone(second["next_cursor"])
        seen = {row["revision_id"] for row in first["items"]} | {row["revision_id"] for row in second["items"]}
        self.assertEqual(len(seen), 3)
        with self.assertRaises(ValueError):
            self.service.list_revisions_page(run_id, limit=0)
        body = self.client().get(f"/v1/runs/{run_id}/revisions?limit=2").json()
        self.assertEqual(sorted(body), ["items", "next_cursor"])

    def test_display_title_is_composed_on_the_server(self):
        self.assertEqual(display_run_title({"title": "我的实验", "engine": {"id": "qlib"}}), "我的实验")
        composed = display_run_title({"title": "mlflow_recorder", "engine": {"id": "qlib"},
                                      "created_at": "2026-09-26T12:52:33Z"})
        self.assertIn("qlib", composed)
        self.assertIn("2026-09-26", composed)
        run_id = self.service.import_package("test", "named", "generic_v1",
                                             package(title="mlflow_recorder"))["run_id"]
        listed = self.service.list_runs(limit=5)["items"][0]
        self.assertEqual(listed["display_title"], display_run_title(listed["run"]))
        fetched = self.service.get_run(run_id)
        self.assertEqual(fetched["display_title"], listed["display_title"])
        revision = self.client().get(f"/v1/runs/{run_id}/revisions/{fetched['revision_id']}").json()
        self.assertEqual(revision["display_title"], listed["display_title"])

    def test_widget_registry_separates_unsupported_from_unknown(self):
        client = self.client()
        unknown = client.get("/v1/widgets/not.a.query")
        self.assertEqual(unknown.status_code, 404)
        unsupported = client.get("/v1/widgets/runs.success_rate.24h")
        self.assertEqual(unsupported.status_code, 200)
        self.assertEqual(unsupported.json()["availability"], "unsupported")
        self.assertIsNone(unsupported.json()["data"])
        self.assertTrue(unsupported.json()["reason"])

    def test_execution_catalog_declares_result_destination(self):
        from quant_workbench.adapters.executors import QlibCNExecutor, RDAgentExecutor
        execution = ExecutionService(self.repository, [QlibCNExecutor(repo_root=ROOT),
                                                       RDAgentExecutor(repo_root=ROOT, agent_root=ROOT)])
        service = WorkbenchService(self.repository, None, None, execution)
        items = {item["kind"]: item for item in service.execution_catalog()["items"]}
        self.assertEqual(items["qlib.cn_synthetic_backtest"]["result_destination"], "auto_import")
        self.assertEqual(items["rdagent.factor.loop"]["result_destination"], "manual_export_required")

    def test_compare_table_loads_each_revision_once(self):
        for index in range(2):
            self.service.import_package("test", f"run-{index}", "generic_v1", package())
        run_ids = [row["run_id"] for row in self.service.list_runs(limit=5)["items"]]
        calls = []
        original = self.repository.get_revision

        def counting(run_id, revision_id=None):
            calls.append(run_id)
            return original(run_id, revision_id)

        self.repository.get_revision = counting
        table = self.service.compare_table(run_ids)
        self.assertTrue(table["rows"])
        self.assertEqual(len([c for c in calls if c in run_ids]), len(run_ids),
                         "比较表应每个运行只加载一次 revision，而不是每行重读")

    def test_metric_groups_are_registered_and_only_backtest_ranks(self):
        from quant_workbench.metrics import metric_group
        self.assertEqual(metric_group("platform.equity"), "backtest")
        self.assertEqual(metric_group("native.qlib.total_cost"), "backtest")
        self.assertEqual(metric_group("native.qlib.mlflow.l2.train"), "training")
        self.assertEqual(metric_group("native.rdagent.IC"), "research")
        self.assertEqual(metric_group("something.unknown"), "other")
        for index in range(2):
            payload = json.loads(FIXTURE.read_text())
            payload["run"]["dataset"] = {"id": "dataset1", "version": "content-v1"}
            payload["series"] = payload["series"][:2]  # platform.equity + native.generic.train_loss
            self.service.import_package("test", f"group-{index}", "generic_v1", payload)
        run_ids = [row["run_id"] for row in self.service.list_runs(limit=5)["items"]]
        table = self.service.compare_table(run_ids, ["platform.equity", "native.generic.train_loss"])
        rows = {row["metric_id"]: row for row in table["rows"]}
        self.assertEqual(rows["platform.equity"]["group"], "backtest")
        self.assertEqual(rows["native.generic.train_loss"]["group"], "training")
        self.assertFalse(rows["native.generic.train_loss"]["ranking_allowed"],
                         "训练组指标只并排，不参与排名")
        self.assertIn("group_only_side_by_side:training", rows["native.generic.train_loss"]["reasons"])
        self.assertEqual([cell["mark"] for cell in rows["native.generic.train_loss"]["cells"]], [None, None])


if __name__ == "__main__":
    unittest.main()
