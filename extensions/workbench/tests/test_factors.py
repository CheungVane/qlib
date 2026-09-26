"""Factor layer: canonical panels, snapshot labels, statistics and overlap (FACTOR_ANALYSIS)."""

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from quant_workbench import factors
from quant_workbench.application import WorkbenchService
from quant_workbench.cn_market import snapshot_content_digest
from quant_workbench.storage import LocalResultRepository


def make_snapshot(root: Path, dates, instruments, prices) -> Path:
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    (root / "instruments").mkdir(exist_ok=True)
    (root / "instruments/all.txt").write_text(
        "".join(f"{code}\t{dates[0]}\t{dates[-1]}\n" for code in instruments), encoding="utf-8")
    for code, series in zip(instruments, prices):
        folder = root / "features" / code.lower()
        folder.mkdir(parents=True, exist_ok=True)
        np.asarray([0.0] + list(series), dtype="<f4").tofile(folder / "close.day.bin")
    return root


def panel(name, dates, instruments, values):
    return {"schema_version": 1, "name": name, "dates": list(dates), "instruments": list(instruments),
            "values": list(values), "calendar_id": "cal"}


def values_of(matrix):
    """NaN means missing for the platform: convert to null before publishing."""
    return [None if value is None or not math.isfinite(float(value)) else float(value)
            for value in np.asarray(matrix).ravel()]


class PanelTests(unittest.TestCase):
    def test_canonical_panel_validates_and_keeps_nulls(self):
        with self.assertRaises(factors.FactorError):
            factors.canonical_panel(panel("f", ["2021-01-02", "2021-01-01"], ["A"], [1, 2]))
        with self.assertRaises(factors.FactorError):
            factors.canonical_panel(panel("f", ["2021-01-01"], ["A"], [1, 2]))
        with self.assertRaises(factors.FactorError):
            factors.canonical_panel(panel("f", ["2021-01-01"], ["A", "A"], [1, 2]))
        with self.assertRaises(factors.FactorError):
            factors.canonical_panel(panel("f", ["2021-01-01"], ["A"], [math.inf]))
        with self.assertRaises(factors.FactorError):
            factors.canonical_panel(panel("f", ["2021-01-01"], ["A"], [True]))
        with self.assertRaises(factors.FactorError):
            factors.canonical_panel(panel("f", ["2021-01-01"], [f"S{i}" for i in range(2001)], [1] * 2001))
        clean = factors.canonical_panel(panel("mom", ["2021-01-01", "2021-01-04"], ["A"], [0.5, None]))
        self.assertEqual(clean["values"], [0.5, None])
        self.assertEqual(clean["coverage"], 0.5)
        self.assertEqual(clean["valid_count"], 1)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = WorkbenchService(LocalResultRepository(Path(self.tmp.name) / "store"))
        self.identity = {"source_instance_id": "test", "external_id": "exp:factor",
                         "name": "mom_5d", "dataset": {"id": "ds", "version": "v1", "snapshot_label": "fp12"},
                         "calendar_id": "cal", "definition": {"formulation": "x"}}

    def test_publish_is_idempotent_and_content_sensitive(self):
        first = self.service.import_factor_panel(self.identity, panel("mom_5d", ["2021-01-01"], ["A"], [1.0]))
        again = self.service.import_factor_panel(self.identity, panel("mom_5d", ["2021-01-01"], ["A"], [1.0]))
        self.assertEqual(first["panel_id"], again["panel_id"])
        self.assertFalse(again["panel_created"])
        changed = self.service.import_factor_panel(self.identity, panel("mom_5d", ["2021-01-01"], ["A"], [2.0]))
        self.assertEqual(changed["factor_id"], first["factor_id"])
        self.assertNotEqual(changed["panel_id"], first["panel_id"])
        self.assertEqual(len(self.service.repository.list_factor_panels(first["factor_id"])), 2)
        listed = self.service.list_factors()["items"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["dataset"]["snapshot_label"], "fp12")
        detail = self.service.factor_detail(first["factor_id"])
        self.assertEqual(detail["panel"]["coverage"], 1.0)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dates = [f"2021-01-{day:02d}" for day in range(1, 21)]
        self.instruments = [f"S{index:02d}" for index in range(12)]
        rng = np.random.default_rng(7)
        steps = rng.normal(0, 0.01, (len(self.dates), len(self.instruments)))
        prices = 100 * np.cumprod(1 + steps, axis=0)
        self.snapshot = make_snapshot(self.root / "snapshot", self.dates, self.instruments, prices.T)
        self.digest = snapshot_content_digest(self.snapshot)
        self.returns = factors.forward_returns(self._prices(), 1)
        self.service = WorkbenchService(LocalResultRepository(self.root / "store"))
        self.dataset = {"id": "ds", "version": self.digest["digest"], "snapshot_label": "snapshot"}
        self.service.factor_snapshot_dir = lambda dataset: self.snapshot

    def _prices(self):
        loaded = factors.load_close_series(self.snapshot, self.dates, self.instruments)
        self.assertEqual(loaded["missing_instruments"], [])
        return loaded["values"]

    def _publish(self, name, values):
        identity = {"source_instance_id": "test", "external_id": name, "name": name,
                    "dataset": self.dataset, "calendar_id": "cal"}
        payload = panel(name, self.dates, self.instruments, values_of(values))
        return self.service.import_factor_panel(identity, payload)["factor_id"]

    def test_forward_returns_are_computed_from_the_recorded_snapshot(self):
        prices = self._prices()
        expected = prices[1] / prices[0] - 1
        self.assertTrue(np.allclose(self.returns[0], expected, rtol=1e-6))
        self.assertTrue(np.all(np.isnan(self.returns[-1])), "最后一个交易日没有未来收益")

    def test_ic_rank_ic_spread_and_significance(self):
        perfect = self._publish("perfect", self.returns)
        inverted = self._publish("inverted", -self.returns)
        report = self.service.factor_analysis([perfect, inverted])
        rows = {row["name"]: row for row in report["factors"]}
        self.assertAlmostEqual(rows["perfect"]["rank_ic"]["ic_mean"], 1.0, places=6)
        self.assertAlmostEqual(rows["inverted"]["rank_ic"]["ic_mean"], -1.0, places=6)
        self.assertGreater(rows["perfect"]["rank_ic"]["t_stat"], 10)
        self.assertLess(rows["perfect"]["rank_ic"]["p_value"], 1e-6)
        self.assertLess(rows["perfect"]["fdr_q"], 0.05)
        self.assertTrue(rows["perfect"]["quantile_spread"]["monotonic"])
        self.assertGreater(rows["perfect"]["quantile_spread"]["top_minus_bottom"], 0)
        self.assertEqual(report["basis"]["sample"]["dates"], len(self.dates))
        self.assertEqual(rows["perfect"]["rank_ic"]["days"], len(self.dates) - 1)
        metrics = {item["metric"] for item in report["overlap"]["not_available"]}
        self.assertEqual(metrics, {"holding_overlap", "crowding"})
        self.assertIn("formula", report["basis"])

    def test_overlap_family_reports_correlation_and_vif(self):
        base = self._publish("base", self.returns)
        twin = self._publish("twin", self.returns)
        other = self._publish("other", np.random.default_rng(3).normal(size=self.returns.shape))
        report = self.service.factor_analysis([base, twin, other])
        correlation = report["overlap"]["value_correlation"]
        index = {name: position for position, name in enumerate(correlation["labels"])}
        self.assertAlmostEqual(correlation["matrix"][index["base"]][index["twin"]], 1.0, places=6)
        self.assertLess(abs(correlation["matrix"][index["base"]][index["other"]]), 0.6)
        redundancy = {(item["left"], item["right"]): item["redundancy"]
                      for item in report["overlap"]["redundancy"]["pairs"]}
        self.assertAlmostEqual(redundancy[("base", "twin")], 0.0, places=6)
        collinearity = report["overlap"]["collinearity"]
        self.assertTrue(collinearity["available"])
        self.assertTrue(collinearity["high_collinearity"], "近似完全共线必须被标为高共线")
        self.assertTrue(collinearity["perfect_collinearity"], "完全相同的因子必须标为完全共线")
        self.assertIsNone(collinearity["vif"]["base"], "inf 在 DTO 中转为 null，并用标志位表达")
        singular = factors.collinearity({"labels": ["a", "b"], "matrix": [[1.0, 1.0], [1.0, 1.0]]})
        self.assertFalse(singular["available"], "完全共线时相关矩阵退化，必须返回原因")
        self.assertEqual(singular["reason"], "singular_correlation_matrix")

    def test_orthogonal_and_incremental_ic_reduce_a_duplicate(self):
        base = self._publish("base", self.returns)
        duplicate = self._publish("duplicate", self.returns * 0.9 + 1e-6)
        report = self.service.factor_analysis([base, duplicate])
        orthogonal = report["overlap"]["orthogonal_ic"]["duplicate"]
        self.assertLess(abs(orthogonal["ic_mean"]), 0.2, "对既有因子正交后应几乎不再有增量信息")
        incremental = {item["factor"]: item for item in report["overlap"]["incremental_ic"]}
        self.assertLess(abs(incremental["duplicate"]["delta"]), 0.05)

    def test_fail_closed_when_snapshot_version_mismatches(self):
        factor_id = self._publish("base", self.returns)
        self.service.factor_snapshot_dir = lambda dataset: self.snapshot
        with self.assertRaises(factors.FactorError):
            self.service.factor_analysis([factor_id], horizons=[0])
        self.service.repository.get_factor = lambda fid: {"factor_id": fid, "name": "base",
                                                          "dataset": {"id": "ds", "version": "wrong",
                                                                      "snapshot_label": "snapshot"},
                                                          "calendar_id": "cal"}
        with self.assertRaises(factors.FactorError):
            self.service.factor_analysis([factor_id])

    def test_bh_fdr_is_monotone_in_p_values(self):
        adjusted = factors.bh_fdr([0.01, 0.02, 0.2, 0.9])
        self.assertEqual(len(adjusted), 4)
        self.assertLessEqual(adjusted[0], adjusted[1])
        self.assertLessEqual(adjusted[1], 0.2 * 4 / 3 + 1e-9)
        self.assertAlmostEqual(factors.bh_fdr([]), [])

    def test_report_is_json_compliant_without_non_finite_numbers(self):
        report = self.service.factor_analysis([self._publish("base", self.returns)])
        text = json.dumps(report, ensure_ascii=False, allow_nan=False)
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)

    def test_http_and_cli_share_the_factor_service(self):
        from fastapi.testclient import TestClient
        from quant_workbench.api import create_app
        client = TestClient(create_app(self.service))
        payload = {"factor": {"source_instance_id": "test", "external_id": "http-factor", "name": "http",
                              "dataset": self.dataset, "calendar_id": "cal"},
                   "panel": panel("http", self.dates, self.instruments,
                                  values_of(self.returns))}
        cross = client.post("/v1/factors", json=payload, headers={"Origin": "http://evil.test"})
        self.assertEqual(cross.status_code, 403)
        created = client.post("/v1/factors", json=payload, headers={"Origin": "http://testserver"})
        self.assertEqual(created.status_code, 200, created.text)
        factor_id = created.json()["factor_id"]
        listed = client.get("/v1/factors").json()["items"]
        self.assertEqual([item["name"] for item in listed], ["http"])
        detail = client.get(f"/v1/factors/{factor_id}").json()
        self.assertEqual(detail["panel"]["cell_count"], len(self.dates) * len(self.instruments))
        analysis = client.get(f"/v1/factor-analysis?factor_id={factor_id}&horizon=1&horizon=5").json()
        self.assertEqual(analysis["basis"]["horizons"], [1, 5])
        self.assertEqual(client.get("/v1/factors/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
