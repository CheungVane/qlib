"""UI06 comparison table: content versions, evaluation scope and best/worst marking."""

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from quant_workbench.application import WorkbenchService
from quant_workbench.cn_market import ensure_snapshot_content, snapshot_content_digest
from quant_workbench.adapters.qlib_mlflow import QlibMlflowImporter
from quant_workbench.metrics import rank, row_value
from quant_workbench.source_safety import comparison_context
from quant_workbench.storage import LocalResultRepository

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "extensions/workbench/examples/generic-result.json"
EVALUATION = "scenario-fingerprint-1"


def package(equity=(1000000, 1010000), drawdown=(-0.05, -0.12), cost=(1200, 900),
            turnover=(0.4, 0.5), dataset_version="content-v1", evaluation_id=EVALUATION,
            execution_id=EVALUATION, initial_equity=1000000, cashflow_policy="none",
            price_basis="qlib_adjusted_account", benchmark_id="SH000905"):
    p = json.loads(FIXTURE.read_text())
    p["run"]["dataset"] = {"id": "dataset1", "version": dataset_version}
    p["run"]["synthetic"] = True
    comparison = {"execution_id": execution_id, "initial_equity": initial_equity,
                  "cashflow_policy": cashflow_policy, "price_basis": price_basis,
                  "benchmark_id": benchmark_id}
    if evaluation_id is not None:
        comparison["evaluation_id"] = evaluation_id
    p["evidence"] = {"comparison": comparison}
    days = ["2021-07-01", "2021-07-02", "2021-07-05"]

    def series(metric_id, unit, values, definition, currency=None):
        entry = {"metric_id": metric_id, "definition_id": definition, "axis": "trading_date",
                 "calendar_id": "qlib.day:dataset1", "unit": unit, "availability": "available",
                 "points": [{"x": day, "value": value} for day, value in zip(days, values)]}
        if currency:
            entry["currency"] = currency
        return entry

    p["series"] = [
        series("platform.equity", "CNY", [equity[0], equity[0], equity[1]],
               "platform.equity.account.v1", "CNY"),
        series("platform.drawdown", "ratio", [0.0, drawdown[0], drawdown[1]],
               "platform.drawdown.observed_equity.v1"),
        series("native.qlib.total_cost", "CNY", [cost[0], cost[0], cost[1]],
               "native.qlib.report.total_cost.v1", "CNY"),
        series("native.qlib.turnover", "ratio", [turnover[0], turnover[0], turnover[1]],
               "native.qlib.report.turnover.v1"),
    ]
    return p


class CompareTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = LocalResultRepository(Path(self.tmp.name))
        self.service = WorkbenchService(self.repo)

    def publish(self, payload, identity):
        return self.service.import_package("test", identity, "generic_v1", payload)["run_id"]

    def test_best_and_worst_are_marked_per_row(self):
        better = self.publish(package(equity=(1000000, 1100000), drawdown=(-0.02, -0.03),
                                      cost=(800, 600), turnover=(0.4, 0.35)), "better")
        worse = self.publish(package(equity=(1000000, 900000), drawdown=(-0.10, -0.20),
                                     cost=(1500, 1200), turnover=(0.4, 0.55)), "worse")
        table = self.service.compare_table([better, worse])
        rows = {row["label"]: row for row in table["rows"]}
        equity = rows["期末权益"]
        self.assertTrue(equity["ranking_allowed"], equity["reasons"])
        self.assertEqual([cell["mark"] for cell in equity["cells"]], ["best", "worst"])
        self.assertEqual([cell["value"] for cell in equity["cells"]], [1100000, 900000])
        drawdown = rows["最大观测回撤"]
        self.assertEqual(drawdown["direction"], "higher_better")
        self.assertEqual(drawdown["cells"][0]["mark"], "best", "更小的回撤应是最优")
        cost = rows["累计成本"]
        self.assertEqual(cost["direction"], "lower_better")
        self.assertEqual([cell["mark"] for cell in cost["cells"]], ["best", "worst"],
                         "成本越低越好，所以成本更低的运行是最优")
        self.assertEqual([cell["value"] for cell in cost["cells"]], [600, 1200])
        turnover = rows["换手率（末值）"]
        self.assertFalse(turnover["ranking_allowed"], "方向未登记时必须保持中性")
        self.assertIn("direction_not_registered", turnover["reasons"])
        self.assertEqual([cell["mark"] for cell in turnover["cells"]], [None, None])
        self.assertEqual(table["runs"][0]["dataset_version"], "content-v1")

    def test_unknown_dataset_version_blocks_the_row(self):
        a = self.publish(package(dataset_version=None), "unknown-version-a")
        b = self.publish(package(dataset_version=None), "unknown-version-b")
        table = self.service.compare_table([a, b])
        equity = next(row for row in table["rows"] if row["label"] == "期末权益")
        self.assertFalse(equity["ranking_allowed"])
        self.assertIn("dataset_version_unknown_or_differs", equity["reasons"])
        self.assertEqual([cell["mark"] for cell in equity["cells"]], [None, None])

    def test_missing_evaluation_scope_blocks_native_metric_rows(self):
        a = self.publish(package(evaluation_id=None), "no-eval-a")
        b = self.publish(package(evaluation_id=None), "no-eval-b")
        table = self.service.compare_table([a, b])
        cost = next(row for row in table["rows"] if row["label"] == "累计成本")
        self.assertFalse(cost["ranking_allowed"])
        self.assertIn("evaluation_unknown_or_differs", cost["reasons"])

    def test_ties_share_the_mark_and_equal_values_stay_neutral(self):
        a = self.publish(package(equity=(1000000, 1050000)), "tie-a")
        b = self.publish(package(equity=(1000000, 1050000)), "tie-b")
        table = self.service.compare_table([a, b], ["platform.equity"])
        row = table["rows"][0]
        self.assertFalse(row["ranking_allowed"])
        self.assertIn("values_within_tolerance", row["reasons"])
        self.assertEqual([cell["mark"] for cell in row["cells"]], [None, None])
        self.assertEqual(rank([1, 1], "higher_better")["marks"], [None, None])
        self.assertTrue(rank([1, 1], "higher_better")["within_tolerance"])

    def test_float_noise_is_not_treated_as_a_difference(self):
        noisy = self.publish(package(equity=(1000000, 982143.6629745483)), "noise-a")
        twin = self.publish(package(equity=(1000000, 982143.6629745484)), "noise-b")
        table = self.service.compare_table([noisy, twin], ["platform.equity"])
        row = table["rows"][0]
        self.assertFalse(row["ranking_allowed"], "1e-10 级差异属于数值噪声，不应标注优劣")
        self.assertIn("values_within_tolerance", row["reasons"])
        self.assertEqual([cell["mark"] for cell in row["cells"]], [None, None])
        detail = rank([1.0, 1.0 + 1e-12, 2.0], "higher_better")
        self.assertEqual(detail["marks"], ["worst", "worst", "best"])
        self.assertTrue(detail["tied_worst"])

    def test_metric_selection_and_aggregations(self):
        a = self.publish(package(), "agg-a")
        b = self.publish(package(), "agg-b")
        table = self.service.compare_table([a, b], ["native.qlib.turnover", "platform.drawdown"])
        self.assertEqual([row["label"] for row in table["rows"]],
                         ["最大观测回撤", "换手率（末值）"])
        self.assertEqual(row_value({"points": [{"x": 1, "value": 3}, {"x": 2, "value": 1}]}, "minimum"), 1)
        self.assertAlmostEqual(row_value({"points": [{"x": 1, "value": 100}, {"x": 2, "value": 150}]}, "change"), 0.5)
        self.assertIsNone(row_value({"points": []}, "last"))

    def test_comparison_context_carries_the_evaluation_scope(self):
        from quant_workbench.cn_market import load_profile
        scenario = load_profile(ROOT / "configs/cn/profile.json")
        context = comparison_context(scenario)
        self.assertEqual(context["execution_id"], scenario["execution_fingerprint"])
        self.assertEqual(context["evaluation_id"], scenario["evaluation_fingerprint"])
        self.assertEqual(context["experiment_id"], scenario["experiment_id"])
        self.assertNotEqual(context["execution_id"], context["evaluation_id"])
        self.assertNotEqual(context["execution_id"], context["experiment_id"])
        partial = comparison_context({"fingerprint": "fp-1", "account": {"initial_cash": 1000000},
                                      "research": {"benchmark": "SH000905"}})
        self.assertIsNone(partial["execution_id"], "记录不完整时身份未知，不得编造")
        self.assertIsNone(partial["evaluation_id"])


class SnapshotContentTests(unittest.TestCase):
    def test_importer_records_currency_and_evaluation_scope(self):
        import pandas as pd

        from quant_workbench.cn_market import load_profile
        scenario = load_profile(ROOT / "configs/cn/profile.json")
        fingerprint = scenario["fingerprint"]
        report = pd.DataFrame(
            {"account": [1000000.0, 1005000.0], "return": [0.0, 0.005], "bench": [0.0, 0.001],
             "total_cost": [0.0, 1200.0], "cost": [0.0, 0.0012], "total_turnover": [0.0, 5000.0],
             "turnover": [0.0, 0.05]},
            index=pd.to_datetime(["2021-07-01", "2021-07-02"]))
        quality = {"scenario_fingerprint": fingerprint, "status": "passed_checks",
                   "valid_ic_days": 2, "constant_prediction_days": 0, "trade_days": 2}

        class Info:
            run_id = "run-1"
            artifact_uri = "file:///tmp/artifacts"
            status = "FINISHED"
            start_time = 1_600_000_000_000
            end_time = 1_600_000_060_000

        class Run:
            info = Info()

            class data:  # noqa: N801 - mirrors the MLflow client shape
                metrics = {}
                tags = {"cn_scenario": fingerprint, "mlflow.runName": "cn-attempt"}

        class FakeClient:
            def __init__(self, folder):
                self.folder = Path(folder)

            def get_run(self, external_id):
                return Run()

            def download_artifacts(self, external_id, path):
                target = self.folder / path.replace("/", "_")
                target.parent.mkdir(parents=True, exist_ok=True)
                if path.endswith(".pkl"):
                    report.to_pickle(target)
                elif path.endswith("effective.json"):
                    target.write_text(json.dumps(scenario), encoding="utf-8")
                else:
                    target.write_text(json.dumps(quality), encoding="utf-8")
                return str(target)

            def get_metric_history(self, external_id, name):
                return []

            def list_artifacts(self, external_id, path):
                class Artifact:
                    def __init__(self, value):
                        self.path = value
                return [Artifact("cn_quality/quality.json")]

        with tempfile.TemporaryDirectory() as tmp:
            package = QlibMlflowImporter()._load(
                FakeClient(tmp), "run-1", "cn-current-synthetic", "content-v1", True, None)
        series = {item["metric_id"]: item for item in package["series"]}
        self.assertEqual(series["platform.equity"]["currency"], "CNY")
        self.assertEqual(series["native.qlib.total_cost"]["currency"], "CNY",
                         "金额类序列必须带币种，否则成本行永远无法比较")
        self.assertEqual(series["native.qlib.total_turnover"]["currency"], "CNY")
        self.assertNotIn("currency", series["native.qlib.turnover"])
        comparison = package["evidence"]["comparison"]
        self.assertEqual(comparison["execution_id"], scenario["execution_fingerprint"])
        self.assertEqual(comparison["evaluation_id"], scenario["evaluation_fingerprint"])
        self.assertEqual(comparison["experiment_id"], scenario["experiment_id"])
        self.assertNotEqual(comparison["execution_id"], comparison["experiment_id"],
                            "研究实验身份必须与执行口径身份分开")
        self.assertEqual(package["run"]["dataset"]["version"], "content-v1")

    def test_content_digest_is_stable_and_content_sensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "features").mkdir()
            (root / "features" / "a.bin").write_bytes(b"one")
            (root / "instruments").mkdir()
            (root / "instruments" / "all.txt").write_text("SH000001\n", encoding="utf-8")
            first = snapshot_content_digest(root)
            self.assertEqual(first["file_count"], 2)
            record = ensure_snapshot_content(root)
            self.assertTrue((root / "content.json").is_file())
            self.assertEqual(snapshot_content_digest(root)["digest"], first["digest"],
                             "content.json 自身不参与摘要")
            self.assertEqual(ensure_snapshot_content(root)["digest"], record["digest"])
            (root / "features" / "a.bin").write_bytes(b"two")
            changed = snapshot_content_digest(root)
            self.assertNotEqual(changed["digest"], first["digest"])
            self.assertEqual(changed["file_count"], 2)


class T03IdentityCounterexampleTests(unittest.TestCase):
    """T03 / A13：身份缺失或差异时必须并排、不得排名，且 mode 不能绕过口径。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = WorkbenchService(LocalResultRepository(Path(self.tmp.name)))

    def publish(self, payload, identity):
        return self.service.import_package("test", identity, "generic_v1", payload)["run_id"]

    def pair(self, **overrides):
        left = self.publish(package(**overrides), "left")
        right = self.publish(package(), "right")
        return left, right

    def test_equity_mode_requires_evaluation_identity(self):
        left, right = self.pair(evaluation_id="scenario-fingerprint-2")
        result = self.service.compare([left, right], "platform.equity", "equity")
        self.assertFalse(result["ranking_allowed"])
        self.assertIn("evaluation_unknown_or_differs", result["reasons"])

    def test_metric_mode_cannot_bypass_execution_identity(self):
        left, right = self.pair(execution_id="scenario-fingerprint-2")
        result = self.service.compare([left, right], "native.qlib.total_cost", "metric")
        self.assertFalse(result["ranking_allowed"], "不同成本情景不得默认排名")
        self.assertIn("execution_scenario_unknown_or_differs", result["reasons"])
        self.assertTrue(result["overlay_allowed"], "并排查看仍然允许")

    def test_metric_mode_requires_funding_basis_for_money_rows(self):
        left, right = self.pair(initial_equity=500000)
        result = self.service.compare([left, right], "native.qlib.total_cost", "metric")
        self.assertFalse(result["ranking_allowed"])
        self.assertIn("initial_equity_unknown_or_differs", result["reasons"])

    def test_metric_mode_requires_known_cashflow_policy(self):
        left, right = self.pair(cashflow_policy="unknown")
        result = self.service.compare([left, right], "native.qlib.total_cost", "metric")
        self.assertFalse(result["ranking_allowed"])
        self.assertTrue({"cashflow_policy_unknown_or_differs", "cashflow_not_supported"}
                        & set(result["reasons"]))

    def test_ratio_only_row_is_exempt_from_money_fields(self):
        left, right = self.pair(initial_equity=500000)
        result = self.service.compare([left, right], "native.qlib.turnover", "metric")
        self.assertNotIn("initial_equity_unknown_or_differs", result["reasons"])

    def test_declared_applicability_table_covers_first_batch(self):
        from quant_workbench import metrics

        for row in metrics.COMPARE_ROWS:
            table = metrics.field_applicability(row["metric_id"])
            self.assertEqual(table["metric_id"], row["metric_id"])
            self.assertTrue(table["requires_evaluation_id"])
        self.assertTrue(metrics.field_applicability("platform.equity")["requires_money_basis"])
        self.assertTrue(metrics.field_applicability("native.qlib.return")["requires_money_basis"])
        self.assertTrue(metrics.field_applicability("platform.drawdown")["requires_money_basis"])
        turnover = metrics.field_applicability("native.qlib.turnover")
        self.assertFalse(turnover["requires_money_basis"])
        self.assertTrue(turnover["requires_execution_id"], "纯比率行仍要执行身份")


if __name__ == "__main__":
    unittest.main()
