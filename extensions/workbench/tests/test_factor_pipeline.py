"""Feature/label pipeline: calendar-step labels, tradability filters and Rank IC."""

import math
import unittest
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


if __name__ == "__main__":
    unittest.main()
