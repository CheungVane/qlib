"""T05 / A16 / A17: snapshot identity, immutability, as-of semantics, free-source reader."""

import json
import os
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
        self.assertEqual(dd.reproducibility(record)["state"], "reproducible")
        partial = dict(record, provenance={"completeness": "partial"})
        self.assertEqual(dd.reproducibility(partial)["state"], "limited")
        no_version = dict(record, materializer={"name": "x"})
        self.assertEqual(dd.reproducibility(no_version)["state"], "limited")


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
