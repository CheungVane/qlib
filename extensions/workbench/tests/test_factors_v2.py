"""A34/T01-F: independent HAC answers, missing-day protection and version compatibility."""
import copy
import io
import json
import math
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

import test_factors as fixtures
from quant_workbench import factors, factors_v2, cli
from quant_workbench.api import create_app


class NeweyWestTests(unittest.TestCase):
    def compute(self, values, horizon=1, expected=None):
        dates = [f"d{i}" for i in range(len(values))]
        return factors_v2.stats([{"date": d, "ic": v} for d, v in zip(dates, values)],
                                 horizon, 2, dates if expected is None else expected)

    def test_hand_calculated_zero_lag_and_bartlett_lag(self):
        zero_lag = self.compute([-0.1, 0.1]*5)
        self.assertAlmostEqual(zero_lag["nw_omega"], 0.01)
        self.assertAlmostEqual(zero_lag["nw_se_mean"], math.sqrt(0.001))
        self.assertAlmostEqual(zero_lag["t_stat"], 0)
        self.assertEqual(zero_lag["p_value"], 1)
        # For ten alternating .1/.3: mean=.2, gamma0=.01,
        # nine lag products each -.01 give gamma1=-.009 (divide by N=10).
        one_lag = self.compute([0.1, 0.3]*5, 2)
        self.assertAlmostEqual(one_lag["nw_omega"], 0.001)
        self.assertAlmostEqual(one_lag["nw_se_mean"], 0.01)
        self.assertAlmostEqual(one_lag["t_stat"], 20)
        self.assertTrue(one_lag["significance_available"])

    def test_constant_and_short_samples_never_get_artificial_significance(self):
        constant = self.compute([0.1]*10)
        self.assertEqual(constant["nw_omega"], 0)
        self.assertIsNone(constant["nw_se_mean"])
        self.assertIsNone(constant["p_value"])
        self.assertIsNone(constant["icir"])
        self.assertTrue(constant["available"])
        self.assertEqual(constant["significance_reason"], "nonpositive_long_run_variance")
        short = self.compute([-.1, .1]*4)
        self.assertEqual(short["significance_reason"], "insufficient_observations")
        high_lag = self.compute([-.1, .1]*5, 10)
        self.assertEqual(high_lag["significance_reason"], "insufficient_observations")

    def test_gap_does_not_compress_time(self):
        report = self.compute([-.1, .1]*10, expected=["absent", *[f"d{i}" for i in range(20)]])
        self.assertTrue(report["available"])
        self.assertFalse(report["significance_available"])
        self.assertEqual(report["significance_reason"], "missing_trading_day_ic")
        self.assertIsNone(report["t_stat"])

    def test_signed_daily_cancellation_and_perfect_pairs(self):
        dates = ["2021-01-01", "2021-01-02"]
        instruments = list("ABCDE")
        values = [1, 2, 3, 4, 5]
        panels = [factors.canonical_panel(fixtures.panel(name, dates, instruments, cells)) for name, cells in [
            ("base", values*2), ("same", values*2), ("opposite", values[::-1]*2),
            ("cancel", values+values[::-1]), ("missing", [None]*10)]]
        report = factors_v2.correlations(panels)
        self.assertAlmostEqual(report["matrix"][0][1], 1)
        self.assertAlmostEqual(report["matrix"][0][2], -1)
        self.assertAlmostEqual(report["matrix"][0][3], 0)
        self.assertEqual(report["valid_days"][0][3], 2)
        self.assertIsNone(report["matrix"][0][4])
        self.assertIsNone(report["matrix"][4][4])
        self.assertEqual(report["valid_days"][4][4], 0)


class FactorV2IntegrationTests(unittest.TestCase):
    setUp = fixtures.AnalysisTests.setUp
    _prices = fixtures.AnalysisTests._prices
    _publish = fixtures.AnalysisTests._publish

    def test_version_compatibility_and_immutable_refs(self):
        first = self._publish("perfect", self.returns)
        second = self._publish("inverted", -self.returns)
        legacy = self.service.factor_analysis([first, second], [1])
        self.assertEqual(legacy, self.service.factor_analysis([first, second], [1], analysis_version=1))
        self.assertIn("redundancy", legacy["overlap"])
        before = self.service.repository.get_factor_panel(first)
        report = self.service.factor_analysis([first, second], [1], analysis_version=2)
        self.assertEqual(report["schema_version"], 2)
        self.assertNotIn("redundancy", report["overlap"])
        pair = report["overlap"]["absolute_correlation_similarity"]["pairs"][0]
        self.assertAlmostEqual(pair["value"], 1)
        self.assertEqual(pair["valid_days"], 19)
        self.assertAlmostEqual(report["overlap"]["correlation_distance"]["pairs"][0]["value"], 0)
        self.assertEqual(report["factors"][0]["panel_id"], before["panel_id"])
        refs = pair["definition"]["input_refs"]
        self.assertEqual(refs["panels"][0]["content_hash"], before["content_hash"])
        self.assertEqual(refs["dataset"]["version"], self.digest["digest"])
        self.assertEqual(self.service.repository.get_factor_panel(first), before)
        self.assertEqual(report["factors"][0]["research_status"], "exploratory")
        json.dumps(report, allow_nan=False)

    def test_missing_panel_day_is_restored_before_forward_returns(self):
        rng = np.random.default_rng(50)
        grid = rng.normal(size=self.returns.shape)
        payload = fixtures.panel("gapped", self.dates[:8]+self.dates[9:], self.instruments,
                                 fixtures.values_of(np.delete(grid, 8, axis=0)))
        identity = {"source_instance_id": "fixture", "external_id": "gap", "name": "gapped",
                    "dataset": self.dataset, "calendar_id": "cal", "provenance": {"data_nature": "synthetic"}}
        factor_id = self.service.import_factor_panel(identity, payload)["factor_id"]
        original = factors.analyze
        with patch.object(factors, "analyze", wraps=original) as analyze:
            report = self.service.factor_analysis([factor_id], [1], analysis_version=2)
        entries, returns = analyze.call_args.args
        self.assertEqual(entries[0]["panel"]["dates"], self.dates)
        self.assertTrue(all(v is None for v in entries[0]["panel"]["values"][8*12:9*12]))
        np.testing.assert_allclose(returns[1][7], self.returns[7])
        stats = report["factors"][0]["rank_ic"]
        self.assertEqual(stats["significance_reason"], "missing_trading_day_ic")
        self.assertIsNotNone(stats["ic_mean"])
        self.assertIsNone(stats["p_value"])
        self.assertIsNone(report["factors"][0]["fdr_q"])
        self.assertEqual(report["basis"]["parameters"]["tested_factor_count"], 0)
        self.assertEqual(report["factors"][0]["provenance"]["data_nature"], "synthetic")

    def test_horizon_tail_excluded_but_interior_invalid_ic_rejects_significance(self):
        grid = np.random.default_rng(12).normal(size=self.returns.shape)
        factor_id = self._publish("random", grid)
        report = self.service.factor_analysis([factor_id], [1, 5], analysis_version=2)
        for h in (1, 5):
            row = report["factors"][0]["horizons"][str(h)]["rank_ic"]
            self.assertEqual(row["expected_days"], 20-h)
            self.assertTrue(row["significance_available"])
        grid[5] = 1
        invalid = self._publish("invalid", grid)
        report = self.service.factor_analysis([invalid], [1], analysis_version=2)
        self.assertEqual(report["factors"][0]["rank_ic"]["significance_reason"], "missing_trading_day_ic")

    def test_panel_column_order_does_not_change_any_analysis(self):
        grid = np.random.default_rng(33).normal(size=self.returns.shape)
        first = self._publish("first", grid)
        second = self._publish("second", grid*0.7)
        normal = self.service.factor_analysis([first, second], [1], analysis_version=2)
        identity = {"source_instance_id": "fixture", "external_id": "reverse", "name": "reverse",
                    "dataset": self.dataset, "calendar_id": "cal"}
        reverse = self.service.import_factor_panel(identity, fixtures.panel("reverse", self.dates,
                       self.instruments[::-1], fixtures.values_of((grid*0.7)[:, ::-1])))["factor_id"]
        reordered = self.service.factor_analysis([first, reverse], [1], analysis_version=2)
        self.assertAlmostEqual(normal["factors"][1]["rank_ic"]["ic_mean"], reordered["factors"][1]["rank_ic"]["ic_mean"])
        self.assertEqual(normal["overlap"]["combined_ic"], reordered["overlap"]["combined_ic"])

    def test_api_cli_match_and_reject_invalid_version(self):
        factor_id = self._publish("random", np.random.default_rng(12).normal(size=self.returns.shape))
        expected = self.service.factor_analysis([factor_id], [1], analysis_version=2)
        client = TestClient(create_app(self.service))
        response = client.get("/v1/factor-analysis", params={"factor_id": factor_id, "horizon": 1, "analysis_version": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        self.assertEqual(client.get("/v1/factor-analysis", params={"factor_id": factor_id, "analysis_version": 3}).status_code, 422)
        for version in (True, 0, 3):
            with self.assertRaises(factors.FactorError):
                self.service.factor_analysis([factor_id], analysis_version=version)
        for version in (1, 2):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(cli, "build_service", return_value=self.service), redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["factor-analysis", factor_id, "--horizons", "1", "--analysis-version", str(version)])
            self.assertEqual(code, 0)
            if version == 2:
                self.assertEqual(json.loads(out.getvalue()), expected)
            else:
                self.assertIn("旧定义", err.getvalue())
                self.assertNotIn("schema_version", json.loads(out.getvalue()))

    def test_calendar_budget_and_unknown_calendar_are_rejected(self):
        factor_id = self._publish("random", np.random.default_rng(12).normal(size=self.returns.shape))
        with patch.dict(factors.PANEL_LIMITS, {"cells": 10}):
            with self.assertRaisesRegex(factors.FactorError, "budget"):
                self.service.factor_analysis([factor_id], analysis_version=2)

        original = self.service.repository.get_factor
        with patch.object(self.service.repository, "get_factor", side_effect=lambda fid: {**original(fid), "calendar_id": None}):
            with self.assertRaisesRegex(factors.FactorError, "calendar"):
                self.service.factor_analysis([factor_id], analysis_version=2)

    def test_new_pair_fields_apply_absolute_value_after_daily_mean(self):
        grid = np.tile(np.arange(12), (20, 1)).astype(float)
        alternating = grid.copy()
        alternating[1::2] *= -1
        first = self._publish("base", grid)
        second = self._publish("alternating", alternating)
        report = self.service.factor_analysis([first, second], [1], analysis_version=2)
        similarity = report["overlap"]["absolute_correlation_similarity"]["pairs"][0]
        distance = report["overlap"]["correlation_distance"]["pairs"][0]
        self.assertAlmostEqual(similarity["correlation"], 0)
        self.assertAlmostEqual(similarity["value"], 0)
        self.assertAlmostEqual(distance["value"], 1)
        self.assertEqual(similarity["valid_days"], 20)

    def test_fdr_discloses_only_valid_tests(self):
        valid = self._publish("random", np.random.default_rng(12).normal(size=self.returns.shape))
        invalid = self._publish("constant", np.ones_like(self.returns))
        report = self.service.factor_analysis([valid, invalid], [1], analysis_version=2)
        self.assertEqual(report["basis"]["parameters"]["requested_factor_count"], 2)
        self.assertEqual(report["basis"]["parameters"]["tested_factor_count"], 1)
        self.assertAlmostEqual(report["factors"][0]["fdr_q"], report["factors"][0]["rank_ic"]["p_value"])
        self.assertIsNone(report["factors"][1]["fdr_q"])


if __name__ == "__main__":
    unittest.main()
