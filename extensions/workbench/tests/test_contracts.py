"""API03: machine-readable contract checks for the workbench HTTP surface.

These checks freeze route coverage and the key set of core read DTOs. A DTO change must
update this file in the same commit, so drift is visible instead of silent.
"""

import tempfile
import unittest
from pathlib import Path

from quant_workbench.api import create_app
from quant_workbench.application import WorkbenchService
from quant_workbench.execution import ExecutionService, attempt_dto
from quant_workbench.storage import LocalResultRepository

ROOT = Path(__file__).resolve().parents[3]


# Key sets of core read DTOs. Adding or removing a field must be an explicit decision here.
CORE_DTO_KEYS = {
    "/v1/health": ["schema_version", "status"],
    "/v1/capabilities": ["agent_observers", "execution_kinds", "executor", "executors",
                         "live_data", "result_importers", "storage"],
    "/v1/executions": ["items", "next_cursor"],
    # T04: `policy` was added deliberately so the frozen execution policy and its usage are
    # visible through the catalog; the key set changes with the contract test in the same commit.
    "/v1/executions/catalog": ["checked_at", "items", "policy"],
    "/v1/provenance/capabilities": ["items"],
    "/v1/research": ["items", "next_offset", "total"],
    "/v1/runs": ["items", "next_cursor"],
}

HTTP_OBSERVABILITY_KEYS = ["availability", "client_errors", "collection_started_at", "completed_requests",
                           "coverage_seconds", "error_rate", "observed_at", "p95_ms", "scope",
                           "server_errors", "truncated", "window_seconds"]

ATTEMPT_DTO_KEYS = ["attempt_id", "cancel_pending", "cancel_requested_at", "config_fingerprint", "created_at",
                    "ended_at", "error_code", "error_message", "executor_id", "exit_code", "has_log",
                    "heartbeat_at", "idempotency_key_present", "kind", "label", "outcome", "params", "probe",
                    "queued_at", "request_id", "started_at", "status", "workspace_label"]


def _snapshot(root, dates, instruments, prices):
    import numpy as np
    (root / "calendars").mkdir(parents=True, exist_ok=True)
    (root / "calendars/day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")
    (root / "instruments").mkdir(exist_ok=True)
    (root / "instruments/all.txt").write_text(
        "".join(f"{code}\t{dates[0]}\t{dates[-1]}\n" for code in instruments), encoding="utf-8")
    for code, series in zip(instruments, prices):
        folder = root / "features" / code.lower()
        folder.mkdir(parents=True, exist_ok=True)
        np.asarray([0.0] + list(series), dtype="<f4").tofile(folder / "close.day.bin")
    (root / "price_semantics.json").write_text('{"price_basis":"adjusted_v1"}')
    return root


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "configs/cn").mkdir(parents=True)
        (root / "configs/cn/profile.json").write_text("{}", encoding="utf-8")
        (root / "scripts").mkdir()
        self.repository = LocalResultRepository(root / "store")
        self.execution = ExecutionService(self.repository, [])
        self.service = WorkbenchService(self.repository, None, None, self.execution)
        self.app = create_app(self.service)
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.temp.cleanup()

    def test_openapi_documents_every_v1_route(self):
        documented = self.client.get("/openapi.json").json()["paths"]
        routes = {route.path for route in self.app.routes if getattr(route, "path", "").startswith("/v1")}
        self.assertTrue(routes, "the workbench must expose /v1 routes")
        self.assertEqual(routes - set(documented), set(), "every /v1 route must appear in the OpenAPI document")
        self.assertEqual(set(documented) - routes, set(), "the OpenAPI document must not invent routes")
        for path, methods in documented.items():
            self.assertTrue(methods, f"{path} documents no method")
            for method, operation in methods.items():
                responses = operation.get("responses") or {}
                self.assertTrue(responses, f"{method.upper()} {path} documents no response")


    def test_new_domain_endpoints_freeze_their_top_level_keys(self):
        """C6: the contract test must cover the endpoints added after API03."""
        import json as _json
        import numpy as np
        from quant_workbench.cn_market import snapshot_content_digest

        fixture = _json.loads((ROOT / "extensions/workbench/examples/generic-result.json").read_text())
        dates = [f"2021-{month:02d}-{day:02d}" for month in range(1, 4) for day in range(1, 11)]
        rng = np.random.default_rng(11)
        equity = 1_000_000 * np.cumprod(1 + rng.normal(0.001, 0.009, len(dates)))
        fixture["run"]["dataset"] = {"id": "dataset1", "version": "content-v1"}
        fixture["series"] = [{"metric_id": "platform.equity", "definition_id": "platform.equity.account.v1",
                              "axis": "trading_date", "calendar_id": "qlib.day:dataset1", "unit": "CNY",
                              "currency": "CNY", "availability": "available",
                              "points": [{"x": day, "value": value} for day, value in zip(dates, equity)]}]
        first = self.service.import_package("test", "contract-a", "generic_v1", fixture)["run_id"]
        second = self.service.import_package("test", "contract-b", "generic_v1", fixture)["run_id"]

        instruments = [f"SH60000{index}" for index in range(6)]
        snapshot = _snapshot(Path(self.temp.name) / "snap", dates, instruments,
                             [equity.tolist()] * len(instruments))
        digest = snapshot_content_digest(snapshot)
        self.service.factor_snapshot_dir = lambda dataset: snapshot
        factor = self.service.import_factor_panel(
            {"source_instance_id": "test", "external_id": "contract-factor", "name": "mom",
             "dataset": {"id": "dataset1", "version": digest["digest"], "snapshot_label": "snap"},
             "calendar_id": "qlib.day:dataset1"},
            {"schema_version": 1, "name": "mom", "dates": dates, "instruments": instruments,
             "values": [float(value) for value in rng.normal(size=len(dates) * len(instruments))]})

        expectations = {
            "/v1/attention": ["counts", "generated_at", "items", "scope", "total"],
            "/v1/factors": ["items"],
            f"/v1/factors/{factor['factor_id']}": ["calendar_id", "created_at", "dataset", "definition",
                                                   "external_id", "factor_id", "name", "panel", "panel_count",
                                                   "panels", "provenance", "source_instance_id"],
            f"/v1/factor-analysis?factor_id={factor['factor_id']}&horizon=1": ["basis", "factors", "limitations",
                                                                              "overlap"],
            f"/v1/risk?run_id={first}": ["count", "items", "periods_per_year",
                                         "periods_per_year_source", "scope"],
            f"/v1/validation?run_id={first}&run_id={second}&blocks=4": ["basis", "configs",
                                                                        "leakage", "limitations",
                                                                        "not_available", "pbo"],
            f"/v1/runs/{first}/revisions": ["items", "next_cursor"],
        }
        for path, expected in expectations.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(sorted(response.json()), expected)

    def test_core_read_dto_keys_are_frozen(self):
        for path, expected in CORE_DTO_KEYS.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(sorted(response.json()), expected)

    def test_observability_keeps_http_and_attempt_blocks(self):
        body = self.client.get("/v1/observability").json()
        self.assertEqual(sorted(key for key in body if key != "attempts"), HTTP_OBSERVABILITY_KEYS)
        attempts = body["attempts"]
        self.assertIn("failure_rate", attempts)
        self.assertIn("statuses", attempts)
        self.assertIn("by_kind", attempts)
        self.assertIsNone(attempts["failure_rate"])
        self.assertEqual(attempts["failure_denominator"], 0)

    def test_attempt_dto_keys_are_frozen_and_hide_server_fields(self):
        dto = attempt_dto({"attempt_id": "a", "kind": "k", "executor_id": "e", "label": "l", "status": "running",
                           "created_at": "2026-01-01T00:00:00Z", "params": {}, "workspace": "/private/ws",
                           "log_path": "/private/ws/attempt.log", "outcome": None})
        self.assertEqual(sorted(dto), ATTEMPT_DTO_KEYS)
        self.assertNotIn("workspace", dto)
        self.assertNotIn("log_path", dto)
        self.assertEqual(dto["workspace_label"], "ws")


if __name__ == "__main__":
    unittest.main()
