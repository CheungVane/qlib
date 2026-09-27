"""T05 / A40: the local data-directory adapter resolves snapshots by id, not by profile."""

import tempfile
import unittest
from pathlib import Path

from quant_workbench import data_directory as dd
from quant_workbench.adapters.local_data_directory import LocalDataDirectory


class LocalDataDirectoryTests(unittest.TestCase):
    def build(self, folder: Path) -> tuple[LocalDataDirectory, Path]:
        registry = folder / "registry"
        data_root = folder / "data"
        (data_root / "snap/calendars").mkdir(parents=True)
        (data_root / "snap/instruments").mkdir(parents=True)
        (data_root / "snap/calendars/day.txt").write_text("2026-09-23\n2026-09-24\n")
        (data_root / "snap/instruments/all.txt").write_text("SH600000\t2020-01-01\t2026-09-24\n")
        record = dd.build_snapshot_record(
            snapshot_id="snap", source={"kind": "test", "source_class": "free_community_unverified"},
            components=[{"kind": "calendar", "uri": "snap/calendars/day.txt",
                         "content_digest": "sha256:c", "source_class": "free_community_unverified",
                         "coverage_start": "2026-09-23", "coverage_end": "2026-09-24"},
                        {"kind": "universe", "uri": "snap/instruments/all.txt",
                         "content_digest": "sha256:u", "source_class": "free_community_unverified",
                         "coverage_start": "2026-09-23", "coverage_end": "2026-09-24"}],
            provenance={"completeness": "complete"},
            materializer={"name": "test", "version": "1"})
        dd.publish_snapshot(registry, record)
        return LocalDataDirectory(registry, data_root), data_root

    def test_lists_and_summarises_registered_snapshots(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter, _ = self.build(Path(folder))
            self.assertTrue(adapter.available())
            self.assertEqual(adapter.list_snapshots(), ["snap"])
            summary = adapter.summary("snap")
        self.assertEqual(summary["snapshot_id"], "snap")
        self.assertEqual(summary["calendar"], {"first": "2026-09-23", "last": "2026-09-24",
                                               "days": 2})
        self.assertEqual(summary["reproducibility"]["state"], "reproducible")
        self.assertNotIn(str(Path(folder)), str(summary), "absolute paths must not leak")

    def test_unknown_snapshot_and_empty_registry_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter, _ = self.build(Path(folder))
            with self.assertRaises(dd.DataDirectoryError):
                adapter.summary("absent")
            empty = LocalDataDirectory(Path(folder) / "nope", Path(folder))
            self.assertFalse(empty.available())
            self.assertEqual(empty.list_snapshots(), [])

    def test_summary_reports_unreadable_snapshot_instead_of_pretending(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter, data_root = self.build(Path(folder))
            (data_root / "snap/calendars/day.txt").unlink()
            summary = adapter.summary("snap")
        self.assertIsNone(summary["calendar"])
        self.assertIn("unreadable_reason", summary)


if __name__ == "__main__":
    unittest.main()
