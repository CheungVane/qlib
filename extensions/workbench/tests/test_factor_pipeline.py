"""Feature/label pipeline: calendar-step labels, tradability filters and Rank IC."""

import math
import unittest
import unittest.mock
from datetime import date

from quant_workbench import factor_pipeline as fp
from quant_workbench.data_directory import DataDirectoryError


class LabelTests(unittest.TestCase):
    def test_forward_return_uses_calendar_steps_and_keeps_missing(self):
        closes = [1.0, float("nan"), 3.0, 4.0, 5.0, 6.0]
        labels = fp.forward_return(closes, horizon=2)
        self.assertAlmostEqual(labels[0], 2.0)          # 3/1-1
        self.assertTrue(math.isnan(labels[1]))          # endpoint missing
        self.assertAlmostEqual(labels[2], 5 / 3 - 1)
        self.assertAlmostEqual(labels[3], 6 / 4 - 1)
        self.assertTrue(math.isnan(labels[4]))          # no future data
        self.assertTrue(math.isnan(labels[5]))

    def test_horizon_must_be_positive(self):
        with self.assertRaises(DataDirectoryError):
            fp.forward_return([1.0, 2.0], horizon=0)


class TradabilityTests(unittest.TestCase):
    days = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)]
    values = {"high": [9.2, 9.2, 10.0, 8.2], "low": [8.9, 9.2, 10.0, 8.0],
              "change": [0.01, 0.01, 0.10, -0.05]}
    enrichment = {
        "2026-09-21": {"turn": 1.0, "tradestatus": 1, "isST": 0},
        "2026-09-22": {"turn": 0.0, "tradestatus": 0, "isST": 0},   # suspended
        "2026-09-23": {"turn": 1.0, "tradestatus": 1, "isST": 0},   # one-word limit up
        "2026-09-24": {"turn": 1.0, "tradestatus": 1, "isST": 1},   # ST
    }

    def test_excludes_suspension_one_word_board_and_st(self):
        flags = fp.tradable(self.values, self.days, self.enrichment)
        self.assertEqual(flags, [True, False, False, False])

    def test_st_can_be_allowed_explicitly(self):
        flags = fp.tradable(self.values, self.days, self.enrichment, exclude_st=False)
        self.assertEqual(flags, [True, False, False, True])

    def test_missing_enrichment_is_not_tradable(self):
        flags = fp.tradable(self.values, self.days, {})
        self.assertEqual(flags, [False, False, False, False])


class FactorTests(unittest.TestCase):
    def test_momentum_volatility_and_mean(self):
        closes = [1.0, 1.1, 1.21, 1.331]
        momentum = fp.momentum(closes, 2)
        self.assertTrue(math.isnan(momentum[0]))
        self.assertAlmostEqual(momentum[2], 1.21 / 1.0 - 1)
        self.assertAlmostEqual(fp.mean_of([1.0, 2.0, 3.0], 2)[2], 2.5)
        self.assertGreater(fp.volatility([1.0, 1.1, 1.0, 1.1], 2)[3], 0)

    def test_cross_sectional_rank_handles_ties(self):
        ranks = fp.cross_sectional_rank({"a": 1.0, "b": 2.0, "c": 2.0, "d": 4.0, "e": float("nan")})
        self.assertEqual(ranks["a"], 0.0)
        self.assertAlmostEqual(ranks["b"], 0.5)
        self.assertAlmostEqual(ranks["c"], 0.5)
        self.assertEqual(ranks["d"], 1.0)
        self.assertNotIn("e", ranks)

    def test_rank_ic_matches_perfect_and_inverse_ordering(self):
        labels = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
        self.assertAlmostEqual(fp.rank_ic({"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}, labels), 1.0)
        self.assertAlmostEqual(fp.rank_ic({"a": 4.0, "b": 3.0, "c": 2.0, "d": 1.0}, labels), -1.0)

    def test_rank_ic_needs_enough_overlap(self):
        self.assertIsNone(fp.rank_ic({"a": 1.0, "b": 2.0}, {"a": 1.0, "b": 2.0}))
        self.assertIsNone(fp.rank_ic({"a": 1.0, "b": 2.0, "c": 3.0}, {"a": 1.0}))


class ExposureTests(unittest.TestCase):
    def test_load_symbol_series_reads_all_factor_fields(self):
        # aligned_series is patched, so the reader is never touched
        with unittest.mock.patch.object(fp, "aligned_series", return_value=[1.0, 2.0]):
            series = fp.load_symbol_series(None, "SH600000",
                                           [date(2026, 9, 23), date(2026, 9, 24)],
                                           {"2026-09-24": {"turn": 0.5}})
        self.assertEqual(set(series), {"close", "high", "low", "change", "volume", "factor", "turn"})
        self.assertTrue(math.isnan(series["turn"][0]))
        self.assertEqual(series["turn"][1], 0.5)

    def test_walk_forward_windows_never_overlap_test(self):
        windows = fp.walk_forward_windows(200, folds=4, min_train=40)
        self.assertEqual(len(windows), 4)
        for train, test in windows:
            self.assertEqual(train.start, 0)
            self.assertLessEqual(train.stop, test.start)
        self.assertEqual(windows[0][1].start, 40)
        self.assertEqual(windows[-1][1].stop, 200)
        self.assertEqual(fp.walk_forward_windows(50, folds=4, min_train=120), [])
        with self.assertRaises(DataDirectoryError):
            fp.walk_forward_windows(200, folds=0)

    def test_label_requires_both_ends_tradable(self):
        flags = [True, False, True, True, True]
        self.assertEqual(fp.label_tradability(flags, horizon=1),
                         [False, False, True, True, False])
        self.assertEqual(fp.label_tradability(flags, horizon=2),
                         [True, False, True, False, False])

    def test_float_shares_and_log_cap(self):
        shares = fp.float_shares_from_series([777395.3125], [0.6796593070030212], [0.1586])
        self.assertAlmostEqual(shares[0] / 33_305_838_300, 1.0, delta=1e-3)
        self.assertTrue(math.isnan(fp.float_shares_from_series([100.0], [1.0], [0.0])[0]))
        cap = fp.log_float_cap([6.116933822631836], [0.6796593070030212],
                               [777395.3125], [0.1586])
        self.assertAlmostEqual(cap[0], math.log(9.0 * shares[0]), delta=1e-6)

    def test_rolling_industry_only_uses_past_data(self):
        import numpy as np

        dates = [date(2026, 1, 1).replace(day=1) + date.resolution * index for index in range(30)]
        window = 10
        base = {"A": [math.sin(index / 3.0) for index in range(30)],
                "B": [math.sin(index / 3.0 + 0.1) for index in range(30)],
                "C": [(-1.0) ** index for index in range(30)],
                "D": [(-1.0) ** (index + 1) for index in range(30)]}
        labels = fp.rolling_industry(base, dates, window=window, n_clusters=2, step=5)
        mutated = dict(base)
        mutated["A"] = base["A"][:15] + [999.0] * 15   # only future values change
        relabelled = fp.rolling_industry(mutated, dates, window=window, n_clusters=2, step=5)
        early = sorted(key for key in labels if key <= dates[14].isoformat())
        self.assertTrue(early)
        for key in early:
            if key in relabelled:
                self.assertEqual(labels[key], relabelled[key])
        self.assertTrue(all(date.fromisoformat(key) >= dates[window] for key in labels))

    def test_neutralize_removes_size_exposure(self):
        factor = {f"S{index:03d}": 3.0 * index + (index % 7) * 0.1 for index in range(60)}
        size = {f"S{index:03d}": float(index) for index in range(60)}
        residual = fp.neutralize(factor, [size])
        self.assertTrue(residual)
        correlation = fp.rank_ic(residual, size)
        self.assertIsNotNone(correlation)
        self.assertLess(abs(correlation), 0.35)

    def test_neutralize_handles_multiple_exposures(self):
        factor = {f"S{index:03d}": 2.0 * index + (index % 5) for index in range(80)}
        size = {f"S{index:03d}": float(index) for index in range(80)}
        beta = {f"S{index:03d}": (index % 11) / 3.0 for index in range(80)}
        industry = {f"S{index:03d}": index % 6 for index in range(80)}
        residual = fp.neutralize(factor, [size, beta], industry)
        self.assertTrue(residual)
        self.assertLess(abs(fp.rank_ic(residual, size)), 0.4)
        self.assertLess(abs(fp.rank_ic(residual, beta)), 0.4)

    def test_rolling_beta_uses_past_window_only(self):
        market = [0.01 if index % 2 else -0.01 for index in range(60)]
        symbols = {"A": [2 * value for value in market], "B": [-value for value in market]}
        betas = fp.rolling_beta(symbols, market, window=20, step=10)
        self.assertTrue(betas)
        first = min(betas)
        self.assertAlmostEqual(betas[first]["A"], 2.0, places=6)
        self.assertAlmostEqual(betas[first]["B"], -1.0, places=6)


class InferenceTests(unittest.TestCase):
    def test_rank_turnover_bounds(self):
        base = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
        self.assertAlmostEqual(fp.rank_turnover(base, base), 0.0)
        # full reversal on 4 names: mean |rank change| = (1 + 1/3 + 1/3 + 1) / 4
        self.assertAlmostEqual(fp.rank_turnover(base, {"a": 4.0, "b": 3.0, "c": 2.0, "d": 1.0}), 2 / 3)

    def test_quantile_spread_detects_monotone_label(self):
        factor = {f"S{index:02d}": float(index) for index in range(20)}
        label = {f"S{index:02d}": float(index) for index in range(20)}
        spread = fp.quantile_spread(factor, label, groups=5)
        self.assertGreater(spread["spread_top_bottom"], 0)
        self.assertEqual(len(spread["group_means"]), 5)

    def test_newey_west_t_and_p_value(self):
        self.assertIsNone(fp.newey_west_t([0.01] * 20, lags=2))  # zero variance
        series = [0.01 + (0.02 if index % 2 else -0.02) for index in range(40)]
        t_stat = fp.newey_west_t(series, lags=2)
        self.assertIsNotNone(t_stat)
        self.assertGreater(t_stat, 0)
        self.assertAlmostEqual(fp.normal_two_sided_p(1.959964), 0.05, places=4)

    def test_benjamini_hochberg_is_monotone_and_capped(self):
        q_values = fp.benjamini_hochberg({"a": 0.001, "b": 0.02, "c": 0.5, "d": 0.9})
        self.assertLessEqual(q_values["a"], q_values["b"])
        self.assertLessEqual(q_values["b"], q_values["c"])
        self.assertLessEqual(max(q_values.values()), 1.0)
        self.assertAlmostEqual(q_values["a"], 0.004, places=6)

    def test_stability_reports_sign_consistency(self):
        steady = [0.05 + (0.01 if index % 2 else -0.01) for index in range(60)]
        report = fp.stability(steady, folds=6)
        self.assertEqual(report["state"], "available")
        self.assertEqual(report["same_sign_share"], 1.0)
        mixed = [0.05 if index < 30 else -0.05 for index in range(60)]
        self.assertLess(fp.stability(mixed, folds=6)["same_sign_share"], 1.0)
        self.assertEqual(fp.stability([0.01, 0.02], folds=6)["state"], "insufficient")

    def test_cost_threshold_screens_spread_against_fees(self):
        cheap = fp.cost_threshold(0.01, 0.02, horizon=5, round_trip_cost=0.00092)
        self.assertTrue(cheap["passes"])
        thin = fp.cost_threshold(0.0001, 0.05, horizon=5, round_trip_cost=0.00092)
        self.assertFalse(thin["passes"])
        self.assertAlmostEqual(thin["assumed_turnover"], min(2.0, 5 * 0.05))


if __name__ == "__main__":
    unittest.main()
