"""Runs against the synthetic Qlib workflow produced by scripts/run_cn_demo.sh."""

import math
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TRACKING_DB = ROOT / ".data" / "qlib_mlruns_mlflow3_12.db"


@unittest.skipUnless(TRACKING_DB.exists(), "run scripts/run_cn_demo.sh first")
class QlibIntegrationTests(unittest.TestCase):
    def test_real_qlib_report_mapping_and_unknown_runtime_version(self):
        import pandas as pd
        from mlflow.tracking import MlflowClient
        from quant_workbench.adapters.qlib_mlflow import QlibMlflowImporter
        from quant_workbench.application import WorkbenchService
        from quant_workbench.storage import LocalResultRepository

        tracking_uri = f"sqlite:///{TRACKING_DB}"
        client = MlflowClient(tracking_uri=tracking_uri)
        experiment = client.get_experiment_by_name("workflow")
        source = client.search_runs([experiment.experiment_id], max_results=1)[0]
        source_report = pd.read_pickle(client.download_artifacts(source.info.run_id,
            "portfolio_analysis/report_normal_1day.pkl"))
        importer = QlibMlflowImporter()
        with tempfile.TemporaryDirectory() as folder:
            service = WorkbenchService(LocalResultRepository(folder))
            result = service.import_package("integration", source.info.run_id, importer.adapter_version,
                importer.load(tracking_uri=tracking_uri, external_id=source.info.run_id,
                    dataset_id="cn_demo", dataset_version=None, synthetic=True,
                    trust_local_artifacts=True))
            revision = service.get_revision(result["run_id"])["result"]
            self.assertIsNone(revision["run"]["engine"]["version"])
            self.assertIsNone(revision["run"]["dataset"]["version"])
            self.assertTrue(revision["run"]["synthetic"])
            series = {item["metric_id"]: item for item in revision["series"]}
            for metric, column in (("platform.equity", "account"), ("native.qlib.total_cost", "total_cost"),
                                   ("native.qlib.turnover", "turnover")):
                actual = [p["value"] for p in series[metric]["points"]]
                expected = source_report[column].tolist()
                self.assertEqual(len(actual), len(expected))
                for a, b in zip(actual, expected):
                    self.assertTrue(math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-9))
            equity = [p["value"] for p in series["platform.equity"]["points"]]
            drawdown = [p["value"] for p in series["platform.drawdown"]["points"]]
            self.assertEqual(drawdown[0], 0)
            self.assertTrue(math.isclose(drawdown[-1], equity[-1] / max(equity) - 1))


if __name__ == "__main__":
    unittest.main()
