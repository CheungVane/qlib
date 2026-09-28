"""T05 / A16 / A17: snapshot identity, immutability, as-of semantics, free-source reader."""

import json
import os
import struct
import tempfile
import unittest
from datetime import date
from pathlib import Path

from quant_workbench import data_directory as dd
from quant_workbench.data_directory import DataDirectoryError

DATA_ROOT = Path(os.path.expanduser("~/.qlib/qlib_data"))
SNAPSHOT_DIR = DATA_ROOT / "free_cn_20260924"


def real_record() -> dict:
    return dd.build_snapshot_record(
        snapshot_id="free_cn_20260924",
        source={"kind": "qlib_bin_release", "source_class": "free_community_unverified",
                "release_tag": "2026-09-27", "upstream": "investment_data/Tushare"},
        components=[
            {"kind": "calendar", "uri": "free_cn_20260924/calendars/day.txt",
             "content_digest": "sha256:calendar", "source_class": "free_community_unverified",
             "coverage_start": "2000-01-04", "coverage_end": "2026-09-24", "available_at": None},
            {"kind": "universe", "uri": "free_cn_20260924/instruments/all.txt",
             "content_digest": "sha256:instruments", "source_class": "free_community_unverified",
             "coverage_start": "2000-01-04", "coverage_end": "2026-09-24", "available_at": None},
            {"kind": "bar", "uri": "free_cn_20260924/features",
             "content_digest": "sha256:features", "source_class": "free_community_unverified",
             "coverage_start": "2000-01-04", "coverage_end": "2026-09-24", "available_at": None},
            {"kind": "status", "uri": "free_cn_20260924_enrichment/turnover",
             "content_digest": "sha256:turnover", "source_class": "free_community_unverified",
             "coverage_start": "2015-01-05", "coverage_end": "2026-09-24", "available_at": None},
        ],
        provenance={"completeness": "complete", "archive_sha256": "sha256:4ce65c37"},
        materializer={"name": "verify_free_snapshot", "version": "1"},
        limitations=["free community source; not official"],
    )


class ManifestTests(unittest.TestCase):
    def test_component_digest_is_order_independent_and_content_sensitive(self):
        a = {"kind": "bar", "uri": "x", "content_digest": "sha256:1", "source_class": "free"}
        b = {"kind": "calendar", "uri": "y", "content_digest": "sha256:2", "source_class": "free"}
        self.assertEqual(dd.component_digest([a, b]), dd.component_digest([b, a]))
        changed = dict(b, content_digest="sha256:3")
        self.assertNotEqual(dd.component_digest([a, b]), dd.component_digest([a, changed]))

    def test_rejects_incomplete_components(self):
        with self.assertRaises(DataDirectoryError):
            dd.build_snapshot_record(snapshot_id="s", source={},
                                     components=[{"kind": "bar", "uri": "x"}])
        with self.assertRaises(DataDirectoryError):
            dd.build_snapshot_record(snapshot_id="s", source={},
                                     components=[{"kind": "unknown", "uri": "x",
                                                  "content_digest": "d", "source_class": "free"}])
        with self.assertRaises(DataDirectoryError):
            dd.build_snapshot_record(snapshot_id="s", source={}, components=[])


class RegistryTests(unittest.TestCase):
    def test_published_snapshot_is_immutable(self):
        record = real_record()
        with tempfile.TemporaryDirectory() as folder:
            path = dd.publish_snapshot(folder, record)
            self.assertTrue(path.exists())
            self.assertEqual(dd.publish_snapshot(folder, record), path)  # idempotent replay
            changed = json.loads(json.dumps(record))
            changed["components"][0]["content_digest"] = "sha256:tampered"
            changed["content_digest"] = dd.component_digest(changed["components"])
            with self.assertRaises(DataDirectoryError):
                dd.publish_snapshot(folder, changed)

    def test_load_rejects_tampered_manifest(self):
        record = real_record()
        with tempfile.TemporaryDirectory() as folder:
            path = dd.publish_snapshot(folder, record)
            tampered = json.loads(path.read_text())
            tampered["components"][0]["content_digest"] = "sha256:other"
            path.write_text(json.dumps(tampered))
            with self.assertRaises(DataDirectoryError):
                dd.load_snapshot(folder, record["snapshot_id"])

    def test_reproducibility_requires_complete_evidence(self):
        record = real_record()
        self.assertEqual(dd.reproducibility(record)["state"], "limited")
        partial = dict(record, provenance={"completeness": "partial"})
        self.assertEqual(dd.reproducibility(partial)["state"], "limited")
        no_version = dict(record, materializer={"name": "x"})
        self.assertEqual(dd.reproducibility(no_version)["state"], "limited")

    def test_legacy_paths_are_registered_and_not_promotable(self):
        record = real_record()
        with tempfile.TemporaryDirectory() as folder:
            dd.register_legacy(folder, legacy_id="cn_data_legacy", path_label="cn_data",
                               reason="pre-existing local demo data without digest")
            legacy = dd.list_legacy(folder)
            self.assertEqual(len(legacy), 1)
            self.assertEqual(legacy[0]["source_class"], dd.LEGACY_SOURCE_CLASS)
            self.assertEqual(dd.reproducibility(legacy[0])["state"], "limited")
            with self.assertRaises(DataDirectoryError):
                dd.publish_snapshot(folder, dict(record, snapshot_id="cn_data_legacy"))

    def test_migration_upgrades_older_records_and_backs_up(self):
        record = real_record()
        stale = dict(record)
        stale["schema_version"] = 0
        stale.pop("content_digest")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / f"{record['snapshot_id']}.json"
            path.write_text(json.dumps(stale))
            summary = dd.migrate_registry(folder, backup_root=Path(folder) / "backup")
            self.assertEqual(summary["migrated"], 1)
            upgraded = json.loads(path.read_text())
            self.assertEqual(upgraded["schema_version"], dd.SCHEMA_VERSION)
            self.assertEqual(upgraded["content_digest"], record["content_digest"])
            self.assertTrue((Path(folder) / "backup" / summary["backup"] / path.name).exists())

    def test_migration_refuses_newer_schema(self):
        record = real_record()
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / f"{record['snapshot_id']}.json").write_text(
                json.dumps(dict(record, schema_version=dd.SCHEMA_VERSION + 1)))
            with self.assertRaises(DataDirectoryError):
                dd.migrate_registry(folder, backup_root=Path(folder) / "backup")

    def test_registry_restore_from_backup(self):
        record = real_record()
        stale = dict(record, schema_version=0)
        stale.pop("content_digest")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / f"{record['snapshot_id']}.json"
            path.write_text(json.dumps(stale))
            summary = dd.migrate_registry(folder, backup_root=Path(folder) / "backup")
            path.write_text(json.dumps({"tampered": True}))
            restored = dd.restore_registry(Path(folder) / "backup" / summary["backup"], folder)
            self.assertEqual(restored["restored"], 1)
            self.assertEqual(json.loads(path.read_text())["schema_version"], 0)
            with self.assertRaises(DataDirectoryError):
                dd.restore_registry(Path(folder) / "missing-backup", folder)


class FakeSnapshotTests(unittest.TestCase):
    """DATA05 checks run against hand-written bins so failures are provable."""

    calendar = ["2026-09-23", "2026-09-24"]

    def build(self, folder: Path, ohlc: dict, volume: float = 100.0) -> dd.FreeSnapshotReader:
        features = folder / "features/sh600001"
        features.mkdir(parents=True)
        for field, values in dict(ohlc, volume=[volume, volume]).items():
            payload = struct.pack("<f", 0) + struct.pack(f"<{len(values)}f", *values)
            (features / f"{field}.day.bin").write_bytes(payload)
        (folder / "calendars").mkdir()
        (folder / "calendars/day.txt").write_text("\n".join(self.calendar) + "\n")
        (folder / "instruments").mkdir()
        (folder / "instruments/all.txt").write_text("SH600001\t2020-01-01\t2026-09-24\n")
        record = dd.build_snapshot_record(
            snapshot_id="fake", source={"source_class": "free_community_unverified"},
            components=[{"kind": "bar", "uri": "features", "content_digest": "sha256:f",
                         "source_class": "free_community_unverified",
                         "coverage_start": "2026-09-23", "coverage_end": "2026-09-24"},
                        {"kind": "calendar", "uri": "calendars/day.txt",
                         "content_digest": "sha256:c", "source_class": "free_community_unverified",
                         "coverage_start": "2026-09-23", "coverage_end": "2026-09-24"},
                        {"kind": "universe", "uri": "instruments/all.txt",
                         "content_digest": "sha256:u", "source_class": "free_community_unverified",
                         "coverage_start": "2026-09-23", "coverage_end": "2026-09-24"}],
            provenance={"completeness": "complete"},
            materializer={"name": "test", "version": "1"})
        return dd.FreeSnapshotReader(folder, record)

    def test_clean_bars_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = self.build(Path(folder), {"open": [9.0, 9.1], "high": [9.2, 9.3],
                                               "low": [8.9, 9.0], "close": [9.1, 9.2]})
            report = dd.validate_bars(reader, ["SH600001"])
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["missing_points"], 0)

    def test_nan_is_counted_as_missing_not_as_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = self.build(Path(folder), {"open": [9.0, float("nan")], "high": [9.2, 9.3],
                                               "low": [8.9, 9.0], "close": [9.1, float("nan")]})
            report = dd.validate_bars(reader, ["SH600001"])
        self.assertTrue(report["ok"], report["issues"])
        self.assertEqual(report["missing_points"], 2)

    def test_ohlc_violation_and_negative_volume_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = self.build(Path(folder), {"open": [9.0, 9.1], "high": [9.05, 9.3],
                                               "low": [8.9, 9.15], "close": [9.4, 9.2]}, volume=-5.0)
            report = dd.validate_bars(reader, ["SH600001"])
        kinds = {issue["type"] for issue in report["issues"]}
        self.assertIn("low_above_body", kinds)
        self.assertIn("body_above_high", kinds)
        self.assertIn("negative_volume", kinds)
        self.assertFalse(report["ok"])

    def test_materialization_is_reproducible(self):
        with tempfile.TemporaryDirectory() as folder:
            reader = self.build(Path(folder), {"open": [9.0, 9.1], "high": [9.2, 9.3],
                                               "low": [8.9, 9.0], "close": [9.1, 9.2]})
            from quant_workbench.adapters.snapshot_files import seal_record
            raw = reader.record
            next(c for c in raw['components'] if c['kind'] == 'universe')['uri'] = 'instruments'
            reader = dd.FreeSnapshotReader(folder, seal_record(Path(folder), raw,
                {'price_basis': 'finv_adjusted_v1'}, {'passed': True}))
            record = dd.materialize_panel(reader, output=Path(folder) / "panel.csv",
                                          universe="all", fields=["close"],
                                          start=date(2026, 9, 23), end=date(2026, 9, 24), seed=7)
            replay = dd.materialize_panel(reader, output=Path(folder) / "panel2.csv",
                                          universe="all", fields=["close"],
                                          start=date(2026, 9, 23), end=date(2026, 9, 24), seed=7)
            self.assertEqual(record["output_digest"], replay["output_digest"])
            self.assertEqual(record["rows"], 2)
            self.assertTrue(dd.verify_materialization(record, Path(folder) / "panel.csv")["ok"])
            with (Path(folder) / "panel.csv").open("a") as handle:
                handle.write("2026-09-25,SH600001,1.0\n")
            self.assertFalse(dd.verify_materialization(record, Path(folder) / "panel.csv")["ok"])


class AsOfTests(unittest.TestCase):
    """A16: no future revision may leak into a historical query."""

    def revisions(self):
        return [
            {"revision": "r1", "statDate": "2020-03-31", "available_at": "2020-04-28", "value": 1.0},
            {"revision": "r2", "statDate": "2020-03-31", "available_at": "2020-08-30", "value": 1.2},
        ]

    def test_returns_only_knowable_revision(self):
        self.assertEqual(dd.select_as_of(self.revisions(), "2020-05-01")["revision"], "r1")
        self.assertEqual(dd.select_as_of(self.revisions(), "2020-09-01")["revision"], "r2")
        self.assertIsNone(dd.select_as_of(self.revisions(), "2020-01-01"))

    def test_code_reuse_resolves_by_interval(self):
        code_map = [
            {"market_code": "SH600000", "instrument_id": "I1", "start": "1999-11-10", "end": "2005-12-31"},
            {"market_code": "SH600000", "instrument_id": "I2", "start": "2006-01-01", "end": "9999-12-31"},
        ]
        self.assertEqual(dd.resolve_symbol(code_map, "SH600000", "2006-06-01"), "I2")
        self.assertEqual(dd.resolve_symbol(code_map, "SH600000", "2004-06-01"), "I1")
        self.assertIsNone(dd.resolve_symbol(code_map, "SH600000", "1998-01-01"))
        with self.assertRaises(DataDirectoryError):
            dd.resolve_symbol(code_map + [dict(code_map[0])], "SH600000", "2004-06-01")


class CoverageGateTests(unittest.TestCase):
    """T05: interval-vs-data coverage consistency is flagged, with the delisting caveat."""

    def test_declared_interval_beyond_the_series_is_flagged(self):
        import struct

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            features = root / "features/sh600001"
            features.mkdir(parents=True)
            (features / "close.day.bin").write_bytes(
                struct.pack("<f", 0) + struct.pack("<2f", 1.0, 2.0))  # 2 points only
            (root / "calendars").mkdir()
            (root / "calendars/day.txt").write_text("2026-09-23\n2026-09-24\n2026-09-25\n")
            (root / "instruments").mkdir()
            (root / "instruments/all.txt").write_text("SH600001\t2020-01-01\t2026-09-25\n")
            record = dd.build_snapshot_record(
                snapshot_id="cov", source={"source_class": "free_community_unverified"},
                components=[{"kind": "bar", "uri": "features", "content_digest": "sha256:f",
                             "source_class": "free_community_unverified",
                             "coverage_start": "2026-09-23", "coverage_end": "2026-09-25"},
                            {"kind": "calendar", "uri": "calendars/day.txt",
                             "content_digest": "sha256:c", "source_class": "free_community_unverified",
                             "coverage_start": "2026-09-23", "coverage_end": "2026-09-25"},
                            {"kind": "universe", "uri": "instruments/all.txt",
                             "content_digest": "sha256:u", "source_class": "free_community_unverified",
                             "coverage_start": "2026-09-23", "coverage_end": "2026-09-25"}],
                provenance={"completeness": "complete"},
                materializer={"name": "test", "version": "1"})
            reader = dd.FreeSnapshotReader(root, record)
            rows = dd.free_sources.load_instruments((root / "instruments/all.txt").read_text())
            report = dd.coverage_report(reader, rows)
        self.assertFalse(report["ok"])
        self.assertEqual(report["truncated"], 1)
        self.assertEqual(report["truncated_sample"][0]["actual_end"], "2026-09-24")
        self.assertIn("delisting", report["note"])


@unittest.skipUnless(SNAPSHOT_DIR.exists(), "free snapshot is not extracted on this machine")
class RealSnapshotTests(unittest.TestCase):
    def test_reads_calendar_universe_and_features_without_qlib(self):
        reader = dd.FreeSnapshotReader(DATA_ROOT, real_record())
        calendar = reader.calendar()
        self.assertEqual(calendar[-1], date(2026, 9, 24))
        self.assertEqual(len(reader.universe_on(date(2026, 9, 24), "csi500")), 500)
        feature = reader.feature("SH600004", "close")
        self.assertGreater(feature["points"], 1000)

    def test_validate_reports_ok_and_coverage(self):
        reader = dd.FreeSnapshotReader(DATA_ROOT, real_record())
        report = reader.validate()
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["calendar"]["last"], "2026-09-24")

    def test_identity_does_not_depend_on_data_root(self):
        record = real_record()
        other_root = Path("/tmp/does-not-need-to-exist")
        self.assertEqual(dd.FreeSnapshotReader(DATA_ROOT, record).record["content_digest"],
                         dd.FreeSnapshotReader(other_root, record).record["content_digest"])

    def test_unknown_component_and_field_fail_closed(self):
        reader = dd.FreeSnapshotReader(DATA_ROOT, real_record())
        with self.assertRaises(DataDirectoryError):
            reader.feature("SH600004", "turnover")
        with self.assertRaises(DataDirectoryError):
            reader.component("financial")


if __name__ == "__main__":
    unittest.main()
