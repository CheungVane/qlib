"""Shared helpers introduced by the third-review refactor (C2/C3/C9)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from quant_workbench import dto, numeric, series_view
from quant_workbench.storage import LocalObjectStore

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "extensions/workbench/examples/generic-result.json"


class NumericTests(unittest.TestCase):
    def test_numpy_import_surfaces_the_callers_error(self):
        self.assertTrue(hasattr(numeric.numpy(), "asarray"))
        with patch.dict(sys.modules, {"numpy": None}):
            with self.assertRaises(ValueError) as caught:
                numeric.numpy(ValueError, "自定义错误")
        self.assertEqual(str(caught.exception), "自定义错误")

    def test_sharpe_is_annualised_only_when_asked(self):
        returns = [0.01, -0.005, 0.002, 0.004, -0.001, 0.003]
        plain = numeric.sharpe(returns)
        annual = numeric.sharpe(returns, periods_per_year=238)
        expected = float(np.mean(returns) / np.std(returns, ddof=1))
        self.assertAlmostEqual(plain, expected, places=12)
        self.assertAlmostEqual(annual, expected * np.sqrt(238), places=12)
        self.assertIsNone(numeric.sharpe([0.01] * 10), "零离散度必须返回 None")
        self.assertIsNone(numeric.sharpe([0.01]), "少于两个观测必须返回 None")

    def test_moment_stats_reports_skew_and_kurtosis(self):
        rng = np.random.default_rng(4)
        skew, kurtosis = numeric.moment_stats(rng.normal(0, 1, 20000))
        self.assertLess(abs(skew), 0.1)
        self.assertLess(abs(kurtosis - 3), 0.2)
        self.assertEqual(numeric.moment_stats([0.0, 0.0]), (None, None))
        self.assertEqual(numeric.moment_stats([1.0]), (None, None))

    def test_tolerances_are_defined_once(self):
        from quant_workbench import metrics, risk
        self.assertEqual(metrics.RANK_TOLERANCE, numeric.RANK_TOLERANCE)
        self.assertEqual(risk.ZERO_TOLERANCE, numeric.ZERO_TOLERANCE)
        self.assertNotEqual(numeric.RANK_TOLERANCE, numeric.ZERO_TOLERANCE)


class DtoTests(unittest.TestCase):
    def test_json_safe_removes_non_finite_values_recursively(self):
        payload = {"a": float("nan"), "b": [float("inf"), {"c": float("-inf"), "d": 1.5}],
                   "e": (1, 2), "f": None, "g": True}
        safe = dto.json_safe(payload)
        self.assertIsNone(safe["a"])
        self.assertIsNone(safe["b"][0])
        self.assertIsNone(safe["b"][1]["c"])
        self.assertEqual(safe["b"][1]["d"], 1.5)
        self.assertEqual(safe["e"], [1, 2])
        self.assertIsNone(safe["f"])
        self.assertIs(safe["g"], True)
        json.dumps(safe, allow_nan=False)
        self.assertEqual(dto.json_safe("text"), "text")


class SeriesViewTests(unittest.TestCase):
    def revision(self, series):
        return {"result": {"series": series}}

    def test_native_return_is_preferred(self):
        revision = self.revision([
            {"metric_id": "native.qlib.return", "availability": "available",
             "points": [{"x": "2021-01-01", "value": 0.01}, {"x": "2021-01-04", "value": None},
                        {"x": "2021-01-05", "value": -0.02}]},
            {"metric_id": "platform.equity", "availability": "available",
             "points": [{"x": "2021-01-01", "value": 100}, {"x": "2021-01-04", "value": 110}]},
        ])
        view = series_view.return_series(revision)
        self.assertEqual(view["dates"], ["2021-01-01", "2021-01-05"])
        self.assertEqual(view["values"], [0.01, -0.02])
        self.assertEqual(view["source"], series_view.NATIVE_LABEL)

    def test_equity_is_derived_when_the_native_series_is_missing(self):
        revision = self.revision([
            {"metric_id": "native.qlib.return", "availability": "not_recorded", "points": []},
            {"metric_id": "platform.equity", "availability": "available",
             "points": [{"x": "2021-01-01", "value": 100}, {"x": "2021-01-04", "value": 110},
                        {"x": "2021-01-05", "value": 99}]},
        ])
        view = series_view.return_series(revision)
        self.assertEqual(view["dates"], ["2021-01-04", "2021-01-05"])
        self.assertAlmostEqual(view["values"][0], 0.1, places=12)
        self.assertAlmostEqual(view["values"][1], 99 / 110 - 1, places=12)
        self.assertEqual(view["source"], series_view.DERIVED_LABEL)

    def test_nothing_usable_returns_none(self):
        self.assertIsNone(series_view.return_series(self.revision([])))
        self.assertIsNone(series_view.return_series(self.revision([
            {"metric_id": "native.qlib.return", "availability": "available",
             "points": [{"x": "2021-01-01", "value": None}]}])))
        fixture = json.loads(FIXTURE.read_text())
        self.assertIsNotNone(series_view.return_series({"result": fixture}),
                             "通用样本的权益序列应可用作派生收益")


if __name__ == "__main__":
    unittest.main()


class ObjectStoreTests(unittest.TestCase):
    """C4: the object store is injectable and keeps its integrity checks after the split."""

    def test_write_read_roundtrip_and_digest_check(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            store = LocalObjectStore(Path(folder) / "objects")
            payload = b'{"a": 1}'
            digest = hashlib.sha256(payload).hexdigest()
            key = store.write(digest, payload)
            self.assertTrue(key.endswith(f"{digest}.json"))
            self.assertEqual(store.read(key), payload)
            self.assertEqual(store.write(digest, payload), key, "同内容重复写入必须复用对象")
            target = store.root / key
            target.write_bytes(b'{"a": 2}')
            with self.assertRaises(RuntimeError) as caught:
                store.read(key)
            self.assertIn("digest mismatch", str(caught.exception))
            with self.assertRaises(RuntimeError):
                store.read("../../etc/passwd")
            with self.assertRaises(FileNotFoundError):
                store.read("ab/" + "c" * 64 + ".json")

    def test_repository_accepts_an_injected_store(self):
        from quant_workbench.storage import LocalResultRepository
        with tempfile.TemporaryDirectory() as folder:
            store = LocalObjectStore(Path(folder) / "elsewhere")
            repo = LocalResultRepository(Path(folder) / "store", object_store=store)
            self.assertIs(repo.object_store, store)
            self.assertEqual(repo.objects, store.root)
            self.assertTrue((Path(folder) / "store" / "workbench.sqlite3").is_file())
