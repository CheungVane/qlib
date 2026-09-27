"""T02-B / A31 / A32: v2 numerics reproduce the frozen §2A.9 reference values."""

import json
import math
import copy
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from quant_workbench import validation_v2 as v2
from quant_workbench.api import create_app
from quant_workbench.application import WorkbenchService
from quant_workbench.storage import LocalResultRepository

FIXTURE = Path(__file__).resolve().parents[1] / "examples/generic-result.json"

FIXTURE_A = {
    "sharpes": [0.0974679434, 0.1949358869, 0.2924038303, 0.3898717738],
    "psr": [0.6645459833, 0.8023651500, 0.8990026123, 0.9556755846],
    "dsr": {4: (0.1323892188, 0.6074815132),
            10: (0.1981326080, 0.4944386687),
            20: (0.2391671724, 0.4235229281)},
}


def fixture_a_series(drift: float) -> list[float]:
    return [drift + (0.01 if index % 2 == 0 else -0.01) for index in range(20)]


def config(run_id: str, values: list[float], start: int = 1) -> dict:
    return {"run_id": run_id, "revision_id": f"{run_id}-r1",
            "dates": [f"2026-{(start + index) // 28 + 1:02d}-{(start + index) % 28 + 1:02d}"
                      for index in range(len(values))],
            "values": values, "resolution": "explicit"}


class PsrReferenceTests(unittest.TestCase):
    def test_matches_fixture_a(self):
        for drift, sharpe, expected in zip((0.001, 0.002, 0.003, 0.004),
                                           FIXTURE_A["sharpes"], FIXTURE_A["psr"]):
            report = v2.probabilistic_sharpe(fixture_a_series(drift))
            self.assertEqual(report["availability"], "available")
            self.assertAlmostEqual(report["inputs"]["sharpe_per_period"], sharpe, places=9)
            self.assertAlmostEqual(report["value"], expected, places=9)
        self.assertAlmostEqual(
            v2.probabilistic_sharpe(fixture_a_series(0.002))["inputs"]["kurtosis"],
            0.9025, places=6)

    def test_fails_closed_on_missing_or_degenerate_inputs(self):
        with_nan = fixture_a_series(0.002)[:-1] + [float("nan")]
        self.assertEqual(v2.probabilistic_sharpe(with_nan)["reason"],
                         "missing_or_nonfinite_observation")
        self.assertEqual(v2.probabilistic_sharpe([0.01] * 20)["reason"], "zero_dispersion")
        self.assertEqual(v2.probabilistic_sharpe([0.01] * 9)["reason"],
                         "insufficient_observations")


class DsrReferenceTests(unittest.TestCase):
    def test_declared_n_enters_the_formula(self):
        candidate = fixture_a_series(0.002)
        trials = [v2.probabilistic_sharpe(fixture_a_series(drift))["inputs"]["sharpe_per_period"]
                  for drift in (0.001, 0.002, 0.003, 0.004)]
        self.assertAlmostEqual(v2.expected_max_sharpe(trials, 4), 0.1323892188, places=9)
        self.assertAlmostEqual(v2.expected_max_sharpe(trials, 10), 0.1981326080, places=9)
        previous = None
        for declared, (expected_max, expected_dsr) in FIXTURE_A["dsr"].items():
            report = v2.deflated_sharpe(candidate, trials, declared)
            self.assertEqual(report["availability"], "available")
            self.assertAlmostEqual(report["inputs"]["expected_max_sharpe"], expected_max, places=9)
            self.assertAlmostEqual(report["value"], expected_dsr, places=9)
            self.assertTrue(0.0 < report["value"] < 1.0)
            if previous is not None:
                self.assertGreater(report["inputs"]["expected_max_sharpe"], previous[0])
                self.assertLess(report["value"], previous[1])
            previous = (report["inputs"]["expected_max_sharpe"], report["value"])

    def test_needs_two_trials(self):
        report = v2.deflated_sharpe(fixture_a_series(0.002), [0.2], 4)
        self.assertEqual(report["reason"], "deflated_sharpe_needs_at_least_two_trials")
        self.assertEqual(v2.deflated_sharpe(fixture_a_series(0.002), [0.1, 0.2], 1)["reason"],
                         "declared_trials_below_two")
        self.assertEqual(v2.deflated_sharpe(fixture_a_series(0.002), [0.2, 0.2], 4)["reason"],
                         "insufficient_trial_dispersion")


class PboReferenceTests(unittest.TestCase):
    def dominance(self):
        a = [[0.02, 0.04], [0.03, 0.05], [0.01, 0.03], [0.02, 0.06]]
        b = [[-value for value in block] for block in a]
        return [[a[index][step], b[index][step]] for index in range(4) for step in range(2)]

    def mixed(self):
        a = [[0.04, 0.06], [0.05, 0.07], [-0.05, -0.03], [-0.04, -0.02]]
        b = [[-0.04, -0.02], [-0.06, -0.04], [0.02, 0.04], [0.02, 0.04]]
        return [[a[index][step], b[index][step]] for index in range(4) for step in range(2)]

    def test_dominance_fixture_is_zero(self):
        report = v2.cscv_pbo(self.dominance(), blocks=4)
        self.assertEqual(report["availability"], "available")
        self.assertAlmostEqual(report["value"], 0.0, places=9)
        self.assertEqual(report["combinations_total"], 6)

    def test_mixed_fixture_is_one_third(self):
        report = v2.cscv_pbo(self.mixed(), blocks=4)
        self.assertAlmostEqual(report["value"], 1 / 3, places=9)
        self.assertEqual(report["observations_per_block"], 2)
        self.assertEqual(report["dropped_observations"]["count"], 0)

    def test_duplicate_configurations_are_degenerate_not_certain(self):
        report = v2.cscv_pbo(self.dominance(), blocks=4)
        duplicates = [[row[0], row[0]] for row in self.dominance()]
        degenerate = v2.cscv_pbo(duplicates, blocks=4)
        self.assertEqual(degenerate["reason"], "degenerate_configurations")
        self.assertEqual(degenerate["configurations"], 1)
        self.assertEqual(report["collapsed_duplicates"], [])

    def test_remainder_is_dropped_and_disclosed(self):
        matrix = [[0.01 * (index % 5) + column * 0.001, -0.01 * (index % 3) - column * 0.001]
                  for index, column in enumerate([0] * 11)]
        report = v2.cscv_pbo(matrix, blocks=4)
        self.assertEqual(report["availability"], "available")
        self.assertEqual(report["dropped_observations"]["count"], 3)
        self.assertEqual(report["observations_per_block"], 2)

    def test_zero_dispersion_block_fails_closed(self):
        flat = [[0.0, 0.0] for _ in range(8)]
        report = v2.cscv_pbo(flat, blocks=4)
        self.assertEqual(report["reason"], "degenerate_configurations")
        mixed_flat = [[0.01 if index % 2 else -0.01, 0.0] for index in range(8)]
        self.assertEqual(v2.cscv_pbo(mixed_flat, blocks=4)["reason"], "zero_dispersion_block")


class ReportTests(unittest.TestCase):
    def configs(self):
        return [config(f"run{drift}", fixture_a_series(drift))
                for drift in (0.001, 0.002, 0.003, 0.004)]

    def test_single_config_keeps_psr_but_drops_dsr_and_pbo(self):
        report = v2.build_report([config("solo", fixture_a_series(0.002))])
        entry = report["configs"][0]
        self.assertEqual(entry["psr"]["availability"], "available")
        self.assertEqual(entry["dsr"]["reason"], "deflated_sharpe_needs_at_least_two_trials")
        self.assertEqual(report["pbo"]["reason"], "pbo_needs_at_least_two_configurations")

    def test_declared_trials_below_usable_configurations_is_rejected(self):
        report = v2.build_report(self.configs(), trials=2)
        self.assertEqual(report["configs"][0]["dsr"]["reason"],
                         "declared_trials_below_usable_configurations")

    def test_declared_trials_change_dsr_only(self):
        low = v2.build_report(self.configs(), trials=4)
        high = v2.build_report(self.configs(), trials=10)
        self.assertNotEqual(low["configs"][1]["dsr"]["value"], high["configs"][1]["dsr"]["value"])
        self.assertEqual(low["configs"][1]["psr"]["value"], high["configs"][1]["psr"]["value"])
        self.assertEqual(low["pbo"]["value"], high["pbo"]["value"])
        self.assertEqual(low["basis"]["trial_scope"]["declared_n"], 4)
        self.assertEqual(high["basis"]["trial_scope"]["declared_n_source"], "declared_by_caller")

    def test_scope_and_returns_are_reported(self):
        report = v2.build_report(self.configs())
        scope = report["basis"]["trial_scope"]
        self.assertEqual(scope["usable_configurations"], 4)
        self.assertEqual(scope["declared_n_source"], "inferred_from_request_selection")
        self.assertEqual(scope["scope_completeness"], "incomplete")
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual([item["resolution"] for item in report["inputs"]],
                         ["explicit"] * 4)

    def test_horizon_does_not_change_psr_dsr_pbo(self):
        short = v2.build_report(self.configs(), horizon=1, splits=5, embargo=1)
        long = v2.build_report(self.configs(), horizon=5, splits=5, embargo=5)
        self.assertEqual(json.dumps(short["configs"], sort_keys=True),
                         json.dumps(long["configs"], sort_keys=True))
        self.assertEqual(short["pbo"]["value"], long["pbo"]["value"])
        # ...but the leakage summary must react to the label span
        self.assertNotEqual(short["leakage"]["uniqueness"]["weight_sum"],
                            long["leakage"]["uniqueness"]["weight_sum"])

    def test_leakage_reports_weight_sum_not_effective_samples(self):
        report = v2.build_report(self.configs(), horizon=5)
        uniqueness = report["leakage"]["uniqueness"]
        self.assertIn("weight_sum", uniqueness)
        self.assertNotIn("effective_samples", uniqueness)
        self.assertIn("not an independent", uniqueness["note"])
        folds = report["leakage"]["purged_folds"]
        self.assertEqual(folds["n_samples"], 20)
        self.assertTrue(folds["folds"])

    def test_missing_values_exclude_the_configuration(self):
        broken = config("broken", [float("nan")] * 20)
        report = v2.build_report([broken] + self.configs())
        self.assertEqual(report["basis"]["trial_scope"]["excluded"],
                         [{"run_id": "broken", "reason": "missing_or_nonfinite_observation"}])
        self.assertEqual(report["basis"]["trial_scope"]["usable_configurations"], 4)

    def test_short_window_is_reported_not_computed(self):
        report = v2.build_report([config("short", [0.001, -0.001, 0.002])])
        self.assertFalse(report["configs"])
        self.assertEqual(report["pbo"]["reason"], "insufficient_common_observations")


class PublishedRevisionTests(unittest.TestCase):
    """End-to-end: published revision -> registered return mapping -> v2 DTO/API/CLI."""

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

    def publish(self, values, external_id):
        payload = copy.deepcopy(self.payload)
        payload["series"][0]["points"] = [
            {"x": f"2021-01-{index + 1:02d}", "value": value} for index, value in enumerate(values)]
        return self.service.import_package("fixture", external_id, "generic_v1", payload)

    def publish_four(self):
        return [self.publish(fixture_a_series(drift), f"v2-{drift}")
                for drift in (0.001, 0.002, 0.003, 0.004)]

    def test_api_v2_reproduces_reference_values_and_reports_scope(self):
        published = self.publish_four()
        params = [("run_id", item["run_id"]) for item in published] + [("analysis_version", "2")]
        response = self.client.get("/v1/validation", params=params)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["schema_version"], 2)
        self.assertEqual(body["basis"]["trial_scope"]["usable_configurations"], 4)
        self.assertAlmostEqual(body["configs"][1]["psr"]["value"], FIXTURE_A["psr"][1], places=9)
        self.assertEqual(body["configs"][1]["revision_id"], published[1]["revision_id"])
        self.assertEqual(body["inputs"][0]["resolution"], "latest_at_request")
        self.assertEqual(body["pbo"]["availability"], "available")

    def test_explicit_revision_is_paired_and_recorded(self):
        published = self.publish_four()
        first = published[0]
        response = self.client.get("/v1/validation", params=[
            ("run_id", first["run_id"]), ("revision_id", first["revision_id"]),
            ("analysis_version", "2"), ("trials", "2")])
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["inputs"][0]["resolution"], "explicit")
        self.assertEqual(body["inputs"][0]["revision_id"], first["revision_id"])
        self.assertEqual(body["configs"][0]["dsr"]["reason"],
                         "deflated_sharpe_needs_at_least_two_trials")
        self.assertEqual(body["pbo"]["reason"], "pbo_needs_at_least_two_configurations")

    def test_mismatched_revision_count_is_rejected(self):
        published = self.publish_four()
        response = self.client.get("/v1/validation", params=[
            ("run_id", published[0]["run_id"]), ("run_id", published[1]["run_id"]),
            ("revision_id", published[0]["revision_id"]), ("analysis_version", "2")])
        self.assertEqual(response.status_code, 400)

    def test_default_version_still_returns_v1_shape(self):
        published = self.publish_four()
        params = [("run_id", item["run_id"]) for item in published]
        body = self.client.get("/v1/validation", params=params).json()
        self.assertNotIn("schema_version", body)
        self.assertIn("basis", body)
        self.assertIn("leakage", body)

    def test_cli_v2_emits_the_same_dto(self):
        import io
        from contextlib import redirect_stdout
        from unittest.mock import patch

        from quant_workbench import cli

        published = self.publish_four()
        out = io.StringIO()
        with patch.object(cli, "build_service", return_value=self.service), redirect_stdout(out):
            code = cli.main(["validate", *[item["run_id"] for item in published],
                             "--analysis-version", "2"])
        self.assertEqual(code, 0)
        body = json.loads(out.getvalue())
        self.assertEqual(body["schema_version"], 2)
        self.assertAlmostEqual(body["configs"][1]["psr"]["value"], FIXTURE_A["psr"][1], places=9)


if __name__ == "__main__":
    unittest.main()
