"""Validation statistics: purged folds, uniqueness, PSR/DSR and PBO (VALIDATION.md)."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from statistics import NormalDist

import numpy as np

from quant_workbench import validation
from quant_workbench.application import WorkbenchService
from quant_workbench.storage import LocalResultRepository

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "extensions/workbench/examples/generic-result.json"


def package(dates, values, metric_id="platform.equity", unit="CNY", currency="CNY"):
    payload = json.loads(FIXTURE.read_text())
    payload["run"]["dataset"] = {"id": "dataset1", "version": "content-v1"}
    payload["series"] = [{
        "metric_id": metric_id, "definition_id": f"{metric_id}.v1", "axis": "trading_date",
        "calendar_id": "qlib.day:dataset1", "unit": unit, "availability": "available",
        "points": [{"x": day, "value": value} for day, value in zip(dates, values)],
        **({"currency": currency} if currency else {}),
    }]
    payload["evidence"] = {"comparison": {"evaluation_id": "eval-1", "execution_id": "exec-1",
                                          "initial_equity": 1000000, "cashflow_policy": "none",
                                          "price_basis": "adjusted", "benchmark_id": "bench"}}
    return payload


class LeakageTests(unittest.TestCase):
    def test_purged_folds_exclude_overlapping_labels(self):
        spans = [(index, index + 2) for index in range(20)]
        report = validation.purged_folds(20, spans, n_splits=4, embargo=1)
        self.assertEqual(report["n_splits"], 4)
        self.assertTrue(all(fold["purged"] > 0 for fold in report["folds"]))
        for fold in report["folds"]:
            low, high = fold["test_start"], fold["test_end"]
            self.assertEqual(fold["test"], list(range(low, high + 1)))
            for index in fold["train"]:
                start, end = spans[index]
                self.assertTrue(end < low or start > high, "训练样本标签不得与测试窗口重叠")
                if index > high:
                    self.assertGreater(index, high + report["embargo"],
                                       "测试窗口之后的 embargo 样本也必须剔除")
        with self.assertRaises(validation.ValidationError):
            validation.purged_folds(5, None, n_splits=5, embargo=0)
        with self.assertRaises(validation.ValidationError):
            validation.purged_folds(20, spans, n_splits=1, embargo=0)

    def test_uniqueness_weights_follow_concurrency(self):
        weights = validation.uniqueness_weights([(0, 1), (0, 1)])
        self.assertAlmostEqual(weights["mean_weight"], 0.5)
        self.assertAlmostEqual(weights["effective_samples"], 1.0)
        self.assertEqual(weights["concurrency_peak"], 2)
        disjoint = validation.uniqueness_weights([(0, 0), (1, 1), (2, 2)])
        self.assertAlmostEqual(disjoint["effective_samples"], 3.0)
        self.assertAlmostEqual(disjoint["min_weight"], 1.0)


class SharpeTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(11)
        self.returns = rng.normal(0.001, 0.01, 500)

    def test_psr_matches_the_closed_form(self):
        result = validation.probabilistic_sharpe(self.returns)
        values = np.asarray(self.returns)
        std = values.std(ddof=1)
        sharpe = values.mean() / std
        centred = values - values.mean()
        skew = (centred ** 3).mean() / std ** 3
        kurtosis = (centred ** 4).mean() / std ** 4
        z_score = sharpe * math.sqrt(len(values) - 1) / math.sqrt(
            1 - skew * sharpe + ((kurtosis - 1) / 4) * sharpe ** 2)
        self.assertAlmostEqual(result["sharpe"], sharpe, places=10)
        self.assertAlmostEqual(result["psr"], NormalDist().cdf(z_score), places=10)
        with self.assertRaises(validation.ValidationError):
            validation.probabilistic_sharpe([0.01] * 30)
        with self.assertRaises(validation.ValidationError):
            validation.probabilistic_sharpe([0.01] * 5)

    def test_deflated_sharpe_penalises_more_trials(self):
        trials = [0.2, 0.5, -0.1, 0.9]
        few = validation.deflated_sharpe(self.returns, trials[:2])
        many = validation.deflated_sharpe(self.returns, trials)
        self.assertGreater(few["expected_max_sharpe"], 0)
        self.assertLess(many["dsr"], validation.probabilistic_sharpe(self.returns)["psr"],
                        "DSR 必须以多重检验为基准，比 PSR 更保守")
        self.assertEqual(many["trials"], 4)
        with self.assertRaises(validation.ValidationError):
            validation.deflated_sharpe(self.returns, [0.3, 0.3])

    def test_pbo_detects_a_dominant_and_an_overfit_configuration(self):
        rng = np.random.default_rng(5)
        rows, columns = 256, 3
        dominant = np.column_stack([rng.normal(0.01, 0.002, rows), rng.normal(0.0, 0.01, rows),
                                    rng.normal(-0.001, 0.01, rows)])
        self.assertLessEqual(validation.pbo(dominant, 8)["pbo"], 0.2)
        noise = rng.normal(0.0, 0.01, (rows, columns))
        self.assertTrue(0.2 <= validation.pbo(noise, 8)["pbo"] <= 0.8)
        half = rows // 2
        overfit = np.column_stack([
            np.concatenate([rng.normal(0.02, 0.01, half), rng.normal(-0.02, 0.01, rows - half)]),
            np.concatenate([rng.normal(-0.02, 0.01, half), rng.normal(0.02, 0.01, rows - half)]),
        ])
        self.assertGreater(validation.pbo(overfit, 8)["pbo"], 0.4,
                           "IS 最优而 OOS 反向的配置必须被 PBO 抓到")
        duplicated = validation.pbo(np.column_stack([dominant[:, 0], dominant[:, 0], dominant[:, 1]]), 8)
        self.assertTrue(duplicated["degenerate"], "完全相同的配置必须标记为退化")
        self.assertEqual(duplicated["duplicate_configurations"], [[0, 1]])
        self.assertIn("不可区分", duplicated["note"])
        with self.assertRaises(validation.ValidationError):
            validation.pbo(np.zeros((64, 1)), 8)
        with self.assertRaises(validation.ValidationError):
            validation.pbo(np.full((64, 2), np.nan), 8)
        with self.assertRaises(validation.ValidationError):
            validation.pbo(np.zeros((5, 2)), 8)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = WorkbenchService(LocalResultRepository(Path(self.tmp.name) / "store"))
        self.dates = [f"2021-{month:02d}-{day:02d}" for month in range(1, 4) for day in range(1, 11)]

    def publish(self, identity, drift):
        rng = np.random.default_rng(abs(hash(identity)) % 2 ** 31)
        equity = 1_000_000 * np.cumprod(1 + rng.normal(drift, 0.008, len(self.dates)))
        return self.service.import_package("test", identity, "generic_v1",
                                           package(self.dates, list(equity)))["run_id"]

    def test_report_composes_validation_without_inventing_data(self):
        first = self.publish("a", 0.002)
        second = self.publish("b", -0.001)
        report = self.service.strategy_validation([first, second], horizon=2, splits=4, blocks=4)
        self.assertEqual(report["basis"]["parameters"]["horizon"], 2)
        self.assertEqual(report["basis"]["parameters"]["embargo"], 2)
        self.assertEqual(len(report["configs"]), 2)
        self.assertTrue(all(config["observations"] == len(self.dates) - 1 for config in report["configs"]))
        self.assertTrue(all(config["return_source"].startswith("derived") for config in report["configs"]))
        self.assertIn("pbo", report["pbo"])
        self.assertGreaterEqual(report["pbo"]["splits"], 1)
        folds = report["leakage"]["purged_folds"]["folds"]
        self.assertTrue(all(fold["purged_ratio"] >= 0 for fold in folds))
        self.assertLess(report["leakage"]["uniqueness"]["effective_samples"], len(self.dates),
                        "重叠标签的有效样本数必须小于观测数")
        metrics = {item["metric"] for item in report["not_available"]}
        self.assertIn("live_out_of_sample", metrics)
        json.dumps(report, ensure_ascii=False, allow_nan=False)

    def test_single_configuration_has_no_pbo(self):
        run_id = self.publish("only", 0.001)
        report = self.service.strategy_validation([run_id])
        self.assertFalse(report["pbo"]["available"])
        self.assertIn("pbo", {item["metric"] for item in report["not_available"]})

    def test_http_and_service_share_the_validation(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app
        first = self.publish("h1", 0.002)
        second = self.publish("h2", 0.0005)
        client = TestClient(create_app(self.service))
        response = client.get(f"/v1/validation?run_id={first}&run_id={second}&horizon=1&blocks=4")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["configs"]), 2)
        self.assertEqual(body["basis"]["parameters"]["blocks"], 4)
        missing = client.get("/v1/validation?run_id=does-not-exist")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
