"""A34 / T01-R: hand-calculated answers, immutable inputs and API/CLI compatibility."""
import copy
import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from quant_workbench import cli, risk
from quant_workbench.api import create_app
from quant_workbench.application import WorkbenchService
from quant_workbench.storage import LocalResultRepository

FIXTURE = Path(__file__).resolve().parents[1] / "examples/generic-result.json"


class RiskV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = WorkbenchService(LocalResultRepository(Path(self.tmp.name)))
        self.client = TestClient(create_app(self.service))
        self.payload = json.loads(FIXTURE.read_text())
        self.payload["evidence"]["comparison"] = {"cashflow_policy": "none"}
        self.payload["series"] = [{
            "metric_id": "native.qlib.return", "definition_id": "native.qlib.report.return.v1",
            "axis": "trading_date", "calendar_id": "fixture.day", "unit": "ratio",
            "availability": "available", "points": [],
        }]

    def publish(self, values, payload=None):
        payload = copy.deepcopy(payload or self.payload)
        payload["series"][0]["points"] = [
            {"x": f"2021-01-{index+1:02d}", "value": value,
             **({"reason": "missing_in_source"} if value is None else {})}
            for index, value in enumerate(values)]
        return self.service.import_package("fixture", "risk-v2", "generic_v1", payload)

    def report(self, run_id, **kwargs):
        return self.service.risk_report([run_id], periods_per_year=1, analysis_version=2, **kwargs)["items"][0]

    def test_four_spec_hand_examples_and_annualisation(self):
        for values, target, expected in [([-0.01]*20, 0, -1), ([-0.01]*5+[0]*15, 0, -0.5),
                                         ([0]*20, 0.01, -1), ([0.01]*20, 0, None)]:
            with self.subTest(target=target, expected=expected):
                published = self.publish(values)
                item = self.report(published["run_id"], target_return=target)
                actual = item["metrics"]["sortino_target_downside"]
                if expected is None:
                    self.assertIsNone(actual)
                    self.assertEqual(item["definitions"]["sortino_target_downside"]["reason"], "no_downside_deviation")
                else:
                    self.assertAlmostEqual(actual, expected)
                    annual = self.service.risk_report([published["run_id"]], 100, analysis_version=2,
                                                      target_return=target)["items"][0]
                    self.assertAlmostEqual(annual["metrics"]["sortino_target_downside"], 10*expected)
                self.assertNotIn("sortino", item["metrics"])
                self.assertEqual(item["definitions"]["sortino_target_downside"]["definition_id"],
                                 "platform.sortino.target_downside.v2")
                if values == [-0.01]*20:
                    self.assertIsNone(item["metrics"]["sharpe"])
                json.dumps(item, allow_nan=False)

    def test_sharpe_rf_and_parameter_sources(self):
        run_id = self.publish([0, 0.02]*10)["run_id"]
        default = self.report(run_id)
        # Sample standard deviation = sqrt(20*0.01^2/19).
        self.assertAlmostEqual(default["metrics"]["sharpe"], math.sqrt(19/20))
        explicit = self.report(run_id, risk_free_rate=0.01)
        self.assertAlmostEqual(explicit["metrics"]["sharpe"], 0)
        self.assertEqual(default["basis"]["parameters"]["risk_free_rate"]["source"], "default")
        self.assertEqual(explicit["basis"]["parameters"]["risk_free_rate"]["source"], "caller")
        self.assertEqual(explicit["definitions"]["sharpe"]["input_basis"]["cost_basis"], "before_cost")

    def test_default_v1_unchanged_and_v2_new_shape(self):
        values = [-0.01, -0.02]*10
        run_id = self.publish(values)["run_id"]
        default = self.service.risk_report([run_id], 1)
        self.assertEqual(default, self.service.risk_report([run_id], 1, analysis_version=1))
        self.assertNotIn("schema_version", default)
        self.assertNotIn("definitions", default["items"][0])
        self.assertAlmostEqual(default["items"][0]["metrics"]["sortino"], -3*math.sqrt(19/20))
        response = self.client.get("/v1/risk", params={"run_id": run_id, "periods_per_year": 1, "analysis_version": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["schema_version"], 2)
        self.assertEqual(response.json()["items"][0], self.report(run_id))

    def test_missing_observation_not_dropped_or_fallback(self):
        payload = copy.deepcopy(self.payload)
        payload["series"].append({"metric_id": "platform.equity", "definition_id": "platform.equity.account.v1",
                                  "axis": "trading_date", "calendar_id": "fixture.day", "unit": "CNY",
                                  "availability": "available", "points": [
                                      {"x": f"2021-01-{i+1:02d}", "value": 100+i} for i in range(25)]})
        run_id = self.publish([0.01]*10+[None]+[-0.01]*10, payload)["run_id"]
        report = self.report(run_id)
        self.assertTrue(all(value is None for value in report["metrics"].values()))
        self.assertEqual(report["definitions"]["sharpe"]["reason"], "missing_or_nonfinite_observation")
        self.assertIn("native.qlib.return", report["return_source"])

    def test_unrecorded_cashflows_or_return_basis_unavailable(self):
        for change, expected in [("cashflow", "cashflow_policy_unknown_or_unsupported"),
                                  ("definition", "return_basis_unknown"), ("unit", "return_unit_unsupported")]:
            payload = copy.deepcopy(self.payload)
            if change == "cashflow":
                payload["evidence"].pop("comparison")
            elif change == "definition":
                payload["series"][0]["definition_id"] = "already_rf_excess.v1"
            else:
                payload["series"][0]["unit"] = "percent"
            report = self.report(self.publish([-0.01]*20, payload)["run_id"], risk_free_rate=0.01)
            self.assertEqual(report["definitions"]["sharpe"]["reason"], expected)
            self.assertIsNone(report["metrics"]["sharpe"])

    def test_equity_basis_and_missing_returns(self):
        payload = copy.deepcopy(self.payload)
        payload["series"][0].update(metric_id="platform.equity", definition_id="platform.equity.account.v1", unit="CNY")
        report = self.report(self.publish([100*(0.99**i) for i in range(21)], payload)["run_id"])
        self.assertAlmostEqual(report["metrics"]["sortino_target_downside"], -1)
        self.assertEqual(report["basis"]["sample"]["observations"], 20)
        self.assertEqual(report["basis"]["sample"]["start"], "2021-01-02")
        self.assertEqual(report["definitions"]["sharpe"]["input_basis"]["cost_basis"], "after_cost")
        payload["series"][0]["metric_id"] = "other"
        absent = self.report(self.publish([0]*20, payload)["run_id"])
        self.assertEqual(absent["definitions"]["sharpe"]["reason"], "no_return_series")

    def test_revision_refs_provenance_and_no_mutation(self):
        first = self.publish([-0.01]*20)
        stored = self.service.repository.get_revision(first["run_id"], first["revision_id"])
        report = self.report(first["run_id"])
        second = self.publish([-0.02]*20)
        self.assertNotEqual(first["revision_id"], second["revision_id"])
        self.assertEqual(report["revision_id"], first["revision_id"])
        self.assertEqual(self.service.repository.get_revision(first["run_id"], first["revision_id"]), stored)
        self.assertEqual(report["provenance"]["data_nature"], "handwritten_fixture")
        for definition in report["definitions"].values():
            self.assertEqual(definition["input_refs"]["revision_id"], first["revision_id"])
            self.assertEqual(set(definition), {"definition_id", "formula", "input_refs", "input_basis",
                                              "parameters", "availability", "reason"})

    def test_cvar_small_tail_null_with_reason(self):
        report = self.report(self.publish([-0.1]+[0.01]*19)["run_id"])
        self.assertIsNone(report["metrics"]["cvar"])
        self.assertEqual(report["definitions"]["cvar"]["reason"], "insufficient_tail_observations")
        self.assertEqual(report["definitions"]["cvar"]["parameters"]["tail_observations"], 1)

    def test_short_and_impossible_return_unavailable(self):
        for values, reason in [([0]*10, "insufficient_observations"),
                               ([-2]+[0]*19, "nonpositive_wealth_unsupported"),
                               ([-1]+[0]*19, "nonpositive_wealth_unsupported")]:
            report = self.report(self.publish(values)["run_id"])
            self.assertEqual(report["definitions"]["sharpe"]["reason"], reason)

    def test_invalid_version_and_scalar_parameters_rejected(self):
        run_id = self.publish([0]*20)["run_id"]
        for value in ([0], True, float("inf"), float("nan")):
            for key in ("target_return", "risk_free_rate"):
                with self.assertRaises(risk.RiskError):
                    self.report(run_id, **{key: value})
        for version in (0, 3, True, "2"):
            with self.assertRaises(risk.RiskError):
                self.service.risk_report([run_id], 1, analysis_version=version)
        for params in ({"analysis_version": 3}, {"analysis_version": 2, "target_return": "NaN"},
                       {"risk_free_rate": 0}):
            response = self.client.get("/v1/risk", params={"run_id": run_id, **params})
            self.assertIn(response.status_code, (400, 422))
        self.assertEqual(self.client.get("/v1/risk", params={"run_id": "missing", "analysis_version": 2}).status_code, 404)

    def test_cli_json_matches_service_and_legacy_warning_is_stderr(self):
        run_id = self.publish([-0.01]*20)["run_id"]
        for extra in ([], ["--analysis-version", "2", "--target-return", "0.01"]):
            out, err = io.StringIO(), io.StringIO()
            with patch.object(cli, "build_service", return_value=self.service), redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["risk", run_id, "--periods-per-year", "1", *extra])
            self.assertEqual(code, 0)
            body = json.loads(out.getvalue())
            if extra:
                self.assertEqual(body["items"][0], self.report(run_id, target_return=0.01))
                self.assertEqual(err.getvalue(), "")
            else:
                self.assertIn("旧定义，未满足当前纠正合同", err.getvalue())
                self.assertNotIn("schema_version", body)


if __name__ == "__main__":
    unittest.main()
