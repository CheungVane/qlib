"""Read a trusted Qlib/MLflow run and map it into the neutral result package."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..model import validate_package
from ..source_safety import data_nature, comparison_context, Sanitizer
from .mlflow_readonly import isolated_mlflow_client


def _utc_ms(value: int | None) -> str | None:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat() if value else None


def _number(value: Any) -> float | None:
    result = float(value)
    return result if math.isfinite(result) else None


def _day_series(metric_id: str, definition_id: str, unit: str, calendar_id: str,
                dates: list[str], values: list[Any], **extra: Any) -> dict[str, Any]:
    return {
        "metric_id": metric_id, "definition_id": definition_id, "axis": "trading_date",
        "calendar_id": calendar_id, "unit": unit, "availability": "available" if values else "empty",
        "points": [{"x": day, "value": _number(value), **({"reason": "missing_in_source"} if _number(value) is None else {})}
                   for day, value in zip(dates, values)],
        **extra,
    }


class QlibMlflowImporter:
    adapter_version = "qlib_mlflow_v2"

    def load(self, *, tracking_uri: str, external_id: str, dataset_id: str,
             dataset_version: str | None, synthetic: bool, trust_local_artifacts: bool,
             config_path: str | None = None) -> dict[str, Any]:
        if not trust_local_artifacts:
            raise ValueError("Qlib reports use pickle; pass --trust-local-artifacts for a trusted local run")
        with isolated_mlflow_client(tracking_uri) as client:
            return self._load(client, external_id, dataset_id, dataset_version, synthetic, config_path)

    def _load(self, client, external_id, dataset_id, dataset_version, synthetic, config_path):
        import pandas as pd
        effective = None
        external = client.get_run(external_id)
        artifact_uri = urlparse(external.info.artifact_uri)
        if artifact_uri.scheme not in ("", "file"):
            raise ValueError("Qlib pickle artifact must be local and explicitly trusted")
        report_path = client.download_artifacts(external_id, "portfolio_analysis/report_normal_1day.pkl")
        report = pd.read_pickle(report_path)
        expected = {"account", "return", "bench", "total_cost", "cost", "total_turnover", "turnover"}
        if not expected.issubset(report.columns) or report.empty:
            raise ValueError(f"Qlib report lacks expected columns: {sorted(expected-set(report.columns))}")
        if not report.index.is_unique or not report.index.is_monotonic_increasing:
            raise ValueError("Qlib report index must be unique and ordered")
        dates = [x.date().isoformat() for x in pd.to_datetime(report.index)]
        calendar_id = f"qlib.day:{dataset_id}"
        equity = [_number(x) for x in report["account"]]
        if any(x is None or x <= 0 for x in equity):
            raise ValueError("Qlib account values must be finite and positive")
        high_water = equity[0]
        drawdown = []
        for value in equity:
            high_water = max(high_water, value)
            drawdown.append(value / high_water - 1)
        series = [
            _day_series("platform.equity", "platform.equity.account.v1", "CNY", calendar_id, dates, equity,
                        currency="CNY", source_ref="portfolio_analysis/report_normal_1day.pkl:account"),
            _day_series("platform.drawdown", "platform.drawdown.observed_equity.v1", "ratio", calendar_id,
                        dates, drawdown, source_ref="derived:account"),
        ]
        for field, unit in (("return", "ratio"), ("bench", "ratio"), ("total_cost", "CNY"),
                            ("cost", "ratio"), ("total_turnover", "CNY"), ("turnover", "ratio")):
            series.append(_day_series(f"native.qlib.{field}", f"native.qlib.report.{field}.v1", unit,
                                      calendar_id, dates, report[field].tolist(),
                                      source_ref=f"portfolio_analysis/report_normal_1day.pkl:{field}"))
        # MLflow metrics may have step histories for training and scalar values for analysis.
        for name in sorted(external.data.metrics):
            history = client.get_metric_history(external_id, name)
            if not history:
                continue
            values = [h.value for h in history if math.isfinite(h.value)]
            if not values:
                continue
            if ".train" in name or ".valid" in name:
                ordered = sorted({h.step: h.value for h in history if math.isfinite(h.value)}.items())
                axis = "step"
                points = [{"x": step, "value": value} for step, value in ordered]
                more = {"step_kind": "iteration"}
            else:
                axis = "scalar"
                points = [{"x": None, "value": values[-1]}]
                more = {}
            series.append({"metric_id": f"native.qlib.mlflow.{name}",
                           "definition_id": f"native.qlib.mlflow.{name}.unspecified",
                           "axis": axis, "unit": "unknown", "availability": "available",
                           "points": points, "source_ref": f"mlflow.metric:{name}", **more})
        status_map = {"FINISHED": "succeeded", "FAILED": "failed", "KILLED": "cancelled",
                      "RUNNING": "running", "SCHEDULED": "queued"}
        status = status_map.get(external.info.status, "unknown")
        evidence: dict[str, Any] = {"mlflow_run_id": external_id,
                                    "runtime_qlib_version": None, "provenance": "partial"}
        if config_path:
            evidence["config_observed_at_import_sha256"] = hashlib.sha256(Path(config_path).read_bytes()).hexdigest()
        if external.data.tags.get('cn_scenario'):
            # These JSON artifacts were saved during the run; unlike a config
            # supplied at import time, they are evidence of the execution scenario.
            import json
            effective_path = client.download_artifacts(external_id, 'cn_quality/effective.json')
            effective = json.loads(Path(effective_path).read_text())
            calculated = hashlib.sha256(json.dumps({k: v for k, v in effective.items() if k != 'fingerprint'},
                                                   sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if effective['fingerprint'] != external.data.tags['cn_scenario'] or calculated != effective['fingerprint']:
                raise ValueError('CN scenario fingerprint mismatch')
            evidence['cn_scenario'] = {
                'fingerprint': effective['fingerprint'], 'mode': effective['research']['mode'],
                'rules_as_of': effective['rules']['as_of'], 'calendar_id': effective['calendar']['id'],
                'commission_both': effective['account']['commission_both'],
                'minimum_commission': effective['account']['minimum_commission'],
                'fees': effective['rules']['fees'], 'execution': effective['research']['execution'],
                'account_assumptions': effective['account']['assumptions'],
            }
            for artifact in client.list_artifacts(external_id, 'cn_quality'):
                if artifact.path.endswith(('/quality.json', '/cn_quality.json')):
                    quality_path = client.download_artifacts(external_id, artifact.path)
                    evidence['research_quality'] = json.loads(Path(quality_path).read_text())
                    if evidence['research_quality']['scenario_fingerprint'] != effective['fingerprint']:
                        raise ValueError('CN quality scenario mismatch')
        evidence["data_nature"] = data_nature(synthetic, effective)
        if effective:
            evidence["comparison"] = comparison_context(effective)
        package = {
            "schema_version": 1,
            "run": {"title": external.data.tags.get("mlflow.runName", f"Qlib {external_id[:8]}"),
                    "kind": "workflow", "status": status,
                    "created_at": _utc_ms(external.info.start_time),
                    "started_at": None if status == "queued" else _utc_ms(external.info.start_time),
                    "ended_at": _utc_ms(external.info.end_time),
                    "engine": {"id": "qlib", "version": None},
                    "dataset": {"id": dataset_id, "version": dataset_version},
                    "synthetic": synthetic,
                    "stages": [{"kind": "training", "status": "unknown"},
                               {"kind": "backtest", "status": "unknown"}]},
            "series": series, "evidence": evidence,
        }
        return validate_package(Sanitizer().scrub(package))
