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
        self.assertEqual(summary["reproducibility"]["state"], "limited")
        self.assertNotIn(str(Path(folder)), str(summary), "absolute paths must not leak")

    def test_unknown_snapshot_and_empty_registry_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            adapter, _ = self.build(Path(folder))
            with self.assertRaises(dd.SnapshotError) as caught:
                adapter.summary("absent")
            self.assertEqual(caught.exception.code, "snapshot_not_found")
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


class ServiceAndApiTests(unittest.TestCase):
    """The adapter must reach the service, API and CLI without touching analysis paths."""

    def setUp(self):
        from fastapi.testclient import TestClient

        from quant_workbench.api import create_app
        from quant_workbench.application import WorkbenchService
        from quant_workbench.storage import LocalResultRepository

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        adapter, _ = LocalDataDirectoryTests().build(root)
        self.service = WorkbenchService(LocalResultRepository(root / "db"), data_directory=adapter)
        self.client = TestClient(create_app(self.service))

    def test_service_and_api_expose_snapshots(self):
        payload = self.service.data_snapshots()
        self.assertTrue(payload["available"])
        self.assertEqual([item["snapshot_id"] for item in payload["items"]], ["snap"])
        response = self.client.get("/v1/data-snapshots")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["snapshot_id"], "snap")
        detail = self.client.get("/v1/data-snapshots/snap")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["calendar"]["last"], "2026-09-24")
        self.assertEqual(self.client.get("/v1/data-snapshots/absent").status_code, 404)

    def test_missing_directory_reports_unavailable_instead_of_empty_success(self):
        from fastapi.testclient import TestClient

        from quant_workbench.api import create_app
        from quant_workbench.application import WorkbenchService
        from quant_workbench.storage import LocalResultRepository

        root = Path(self.tmp.name)
        service = WorkbenchService(LocalResultRepository(root / "db2"))
        payload = TestClient(create_app(service)).get("/v1/data-snapshots").json()
        self.assertFalse(payload["available"])
        self.assertEqual(payload["reason"], "data_directory_not_configured")

    def test_cli_lists_and_shows_snapshots(self):
        import io
        import json
        from contextlib import redirect_stdout
        from unittest.mock import patch

        from quant_workbench import cli

        out = io.StringIO()
        with patch.object(cli, "build_service", return_value=self.service), redirect_stdout(out):
            code = cli.main(["data-snapshots"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["items"][0]["snapshot_id"], "snap")
        out2 = io.StringIO()
        with patch.object(cli, "build_service", return_value=self.service), redirect_stdout(out2):
            self.assertEqual(cli.main(["data-snapshot", "snap"]), 0)
        self.assertEqual(json.loads(out2.getvalue())["snapshot_id"], "snap")


class LegacySeparationTests(unittest.TestCase):
    """Legacy registrations must not masquerade as readable snapshots."""

    def test_list_snapshots_excludes_legacy_registrations(self):
        import tempfile
        from pathlib import Path as _Path

        from quant_workbench import data_directory as dd

        with tempfile.TemporaryDirectory() as folder:
            registry = _Path(folder)
            dd.register_legacy(registry, legacy_id="cn_data", path_label="cn_data",
                               reason="pre-existing local data without digest")
            record = dd.build_snapshot_record(
                snapshot_id="snap", source={"source_class": "free_community_unverified"},
                components=[{"kind": "calendar", "uri": "x", "content_digest": "sha256:c",
                             "source_class": "free_community_unverified",
                             "coverage_start": "2026-01-01", "coverage_end": "2026-01-02"}])
            dd.publish_snapshot(registry, record)
            self.assertEqual(dd.list_snapshots(registry), ["snap"])
            self.assertEqual([item["legacy_id"] for item in dd.list_legacy(registry)], ["cn_data"])
