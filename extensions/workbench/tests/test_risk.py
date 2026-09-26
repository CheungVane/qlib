"""Performance and risk metrics (RESULT_CONTRACT U22)."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from quant_workbench import risk
from quant_workbench.application import WorkbenchService
from quant_workbench.storage import LocalResultRepository

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "extensions/workbench/examples/generic-result.json"


class RiskTests(unittest.TestCase):
    def test_known_drawdown_and_returns(self):
        dates = [f"2021-01-{day:02d}" for day in range(1, 21)]
        returns = [0.1, -0.2, 0.35] + [0.0] * 17
        report = risk.performance_report(dates, returns, periods_per_year=252)
        metrics = report["metrics"]
        self.assertAlmostEqual(metrics["max_drawdown"], 0.88 / 1.1 - 1, places=10)
        self.assertAlmostEqual(metrics["total_return"], 1.1 * 0.8 * 1.35 - 1, places=10)
        self.assertAlmostEqual(metrics["mean_daily"], float(np.mean(returns)), places=10)
        episodes = report["drawdown_episodes"]
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["status"], "recovered")
        self.assertAlmostEqual(episodes[0]["depth"], 0.88 / 1.1 - 1, places=10)
        self.assertEqual(report["basis"]["parameters"]["periods_per_year"], 252)
        json.dumps(report, ensure_ascii=False, allow_nan=False)

    def test_degenerate_series_report_unavailable_instead_of_infinity(self):
        dates = [f"2021-01-{day:02d}" for day in range(1, 21)]
        flat = risk.performance_report(dates, [0.01] * 20, periods_per_year=238)
        reasons = {item["metric"] for item in flat["not_available"]}
        self.assertIn("sharpe", reasons)
        self.assertIn("sortino", reasons)
        self.assertIn("calmar", reasons)
        self.assertNotIn("Infinity", json.dumps(flat, allow_nan=False))
        mixed = risk.performance_report(dates, [(-1) ** index * (0.005 + 0.001 * index) for index in range(20)],
                                        periods_per_year=238)
        self.assertIsNotNone(mixed["metrics"]["sortino"], "下行收益有离散度时 Sortino 必须给出数值")
        self.assertIsNotNone(mixed["metrics"]["sharpe"])
        with self.assertRaises(risk.RiskError):
            risk.performance_report(dates[:5], [0.0] * 5)
        with self.assertRaises(risk.RiskError):
            risk.performance_report(dates, [0.01] * 19 + [float("nan")])
        with self.assertRaises(risk.RiskError):
            risk.performance_report(dates, [0.01] * 20, periods_per_year=0)

    def test_var_cvar_and_calendar_aggregation(self):
        dates = [f"2021-{month:02d}-{day:02d}" for month in range(1, 3) for day in range(1, 11)]
        values = [-0.05, -0.04, -0.03, -0.02, -0.01] + [0.01] * 15
        tail = [v for v in values if v <= float(np.quantile(values, 0.05))]
        report = risk.performance_report(dates, values, periods_per_year=238, var_quantile=0.05)
        metrics = report["metrics"]
        self.assertAlmostEqual(metrics["var"], float(np.quantile(values, 0.05)), places=10)
        self.assertAlmostEqual(metrics["cvar"], float(np.mean(tail)), places=10)
        monthly = report["calendar"]["monthly"]["2021"]
        self.assertEqual(len(monthly), 12)
        self.assertIsNotNone(monthly["01"])
        self.assertIsNotNone(monthly["02"])
        self.assertIsNone(monthly["03"], "缺月必须是 null，不是 0")
        self.assertEqual(set(report["calendar"]["annual"]), {"2021"})

    def test_service_and_http_share_the_risk_report(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service = WorkbenchService(LocalResultRepository(Path(tmp.name) / "store"))
        dates = [f"2021-{month:02d}-{day:02d}" for month in range(1, 4) for day in range(1, 11)]
        rng = np.random.default_rng(3)
        equity = 1_000_000 * np.cumprod(1 + rng.normal(0.001, 0.01, len(dates)))
        payload = json.loads(FIXTURE.read_text())
        payload["run"]["dataset"] = {"id": "dataset1", "version": "content-v1"}
        payload["series"] = [{"metric_id": "platform.equity", "definition_id": "platform.equity.account.v1",
                              "axis": "trading_date", "calendar_id": "qlib.day:dataset1", "unit": "CNY",
                              "currency": "CNY", "availability": "available",
                              "points": [{"x": day, "value": value} for day, value in zip(dates, equity)]}]
        run_id = service.import_package("test", "risk-1", "generic_v1", payload)["run_id"]
        report = service.risk_report([run_id], periods_per_year=238)
        self.assertEqual(report["count"], 1)
        self.assertIn("sharpe", report["items"][0]["metrics"])
        self.assertTrue(report["items"][0]["return_source"].startswith("derived"))
        client = TestClient(create_app(service))
        body = client.get(f"/v1/risk?run_id={run_id}").json()
        self.assertEqual(body["items"][0]["run_id"], run_id)
        self.assertEqual(client.get("/v1/risk?run_id=missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
