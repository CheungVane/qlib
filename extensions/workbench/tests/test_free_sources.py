"""DATA_SOURCES §1A/§1B: unit conventions, survivorship-safe universe and PIT industry proxy."""

import math
import os
import unittest
from datetime import date
from pathlib import Path

from quant_workbench import free_sources
from quant_workbench.free_sources import FreeSourceError

SNAPSHOT = Path(os.path.expanduser("~/.qlib/qlib_data/free_cn_20260924"))


class UnitConventionTests(unittest.TestCase):
    """The archive is adjusted; units were verified against BaoStock and East Money."""

    def test_sh600000_2026_09_24_matches_independent_sources(self):
        # exact float32 values read from features/sh600000/*.day.bin
        close, factor, volume, amount = 6.116933822631836, 0.6796593070030212, 777395.3125, 475964.875
        self.assertAlmostEqual(free_sources.raw_price(close, factor), 9.00, places=3)
        self.assertEqual(math.ceil(free_sources.raw_volume_lots(volume, factor)), 528364)
        self.assertLess(abs(amount * 1000 - 475964884.07), 1000)

    def test_rejects_non_positive_factor(self):
        for factor in (0.0, -1.0, float("nan")):
            with self.assertRaises(FreeSourceError):
                free_sources.raw_price(6.1, factor)


class FloatShareTests(unittest.TestCase):
    """Gap 1: daily float shares are derived, not official."""

    def test_derivation_within_0_1_percent_of_quarterly_disclosure(self):
        implied = free_sources.float_shares_from_turnover(52836397, 0.1586)
        self.assertAlmostEqual(implied / 33305838300, 1.0, delta=0.001)

    def test_market_cap_matches_independent_snapshot(self):
        cap = free_sources.float_market_cap(9.00, 52836397, 0.1586)
        self.assertAlmostEqual(cap / 299752544700, 1.0, delta=0.002)

    def test_suspension_cannot_imply_shares(self):
        with self.assertRaises(FreeSourceError):
            free_sources.float_shares_from_turnover(0.0, 0.0)


class UniverseTests(unittest.TestCase):
    def sample(self):
        return free_sources.load_instruments(
            "SH600000\t2000-01-04\t2026-09-24\n"
            "SH600005\t2000-01-04\t2017-02-13\n"
            "BJ430047\t2021-11-15\t2025-09-30\n"
        )

    def test_active_universe_uses_recorded_interval(self):
        active = free_sources.active_universe(self.sample(), date(2026, 9, 24))
        self.assertEqual(active, ["SH600000"])

    def test_survivorship_separates_delisted_from_stale(self):
        report = free_sources.survivorship_report(
            self.sample(), date(2026, 9, 24), delist_dates={"SH600005": "2017-02-14"})
        self.assertEqual(report["active"], 1)
        self.assertEqual(report["delisted"], 1)
        self.assertEqual([item["symbol"] for item in report["stale_symbols"]], ["BJ430047"])

    def test_bad_line_is_rejected(self):
        with self.assertRaises(FreeSourceError):
            free_sources.load_instruments("SH600000\t2020-01-01\n")


class IndustryProxyTests(unittest.TestCase):
    """Gap 2: clustering on the trailing window is point-in-time by construction."""

    def test_separates_two_return_families(self):
        window = {}
        for index in range(6):
            # within-family differences are scale only (removed by standardisation);
            # the two families differ in shape, so the expected split is exact.
            window[f"A{index}"] = [(1 + index * 0.01) * math.sin(step / 2.0) for step in range(40)]
            window[f"B{index}"] = [(1 + index * 0.01) * (-1.0) ** step for step in range(40)]
        labels = free_sources.statistical_industry(window, n_clusters=2)
        groups = {}
        for symbol, label in labels.items():
            groups.setdefault(label, set()).add(symbol)
        self.assertEqual(sorted(len(members) for members in groups.values()), [6, 6])
        for members in groups.values():
            self.assertEqual(len({code[0] for code in members}), 1)

    def test_missing_values_fail_closed(self):
        window = {f"A{index}": [0.01] * 12 for index in range(4)}
        window["A0"] = [float("nan")] + [0.01] * 11
        with self.assertRaises(FreeSourceError):
            free_sources.statistical_industry(window, n_clusters=2)


@unittest.skipUnless(SNAPSHOT.exists(), "free snapshot is not extracted on this machine")
class RealSnapshotTests(unittest.TestCase):
    """Read-only checks against the downloaded 2026-09-27 release."""

    def test_calendar_and_fields(self):
        calendar = (SNAPSHOT / "calendars/day.txt").read_text().split()
        self.assertEqual(calendar[-1], "2026-09-24")
        fields = {path.name.split(".")[0] for path in (SNAPSHOT / "features/sh600000").iterdir()}
        self.assertEqual(fields, set(free_sources.ARCHIVE_FIELDS))

    def test_delisted_instrument_is_present(self):
        rows = free_sources.load_instruments((SNAPSHOT / "instruments/all.txt").read_text())
        by_symbol = {row["symbol"]: row for row in rows}
        self.assertIn("SH600005", by_symbol)
        self.assertEqual(by_symbol["SH600005"]["end"], date(2017, 2, 13))

    def test_beijing_coverage_gap_is_visible(self):
        rows = free_sources.load_instruments((SNAPSHOT / "instruments/all.txt").read_text())
        report = free_sources.survivorship_report(rows, date(2026, 9, 24))
        stale = [item for item in report["stale_symbols"] if item["symbol"].startswith("BJ")]
        self.assertTrue(stale, "expected the northbound coverage gap to be reported")

    def test_bin_reader_reads_last_value(self):
        head_tail = free_sources.read_bin_head_tail(SNAPSHOT / "features/sh600000/close.day.bin")
        self.assertAlmostEqual(head_tail["last"], 6.1169, places=4)


if __name__ == "__main__":
    unittest.main()
