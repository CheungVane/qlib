"""Risk report orchestration; configuration is injected, not read by the use case."""
from __future__ import annotations
from typing import Any

from ..ports import AnalysisConfigurationPort
from .. import risk as risk_layer, series_view
from .results import ResultService

class RiskService:
    def __init__(self, results: ResultService, configuration: AnalysisConfigurationPort):
        self.results = results
        self.configuration = configuration

    def get_revision(self, run_id, revision_id=None):
        return self.results.get_revision(run_id, revision_id)

    def risk_report(self, run_ids: list[str], periods_per_year: int | None = None, *,
                    analysis_version: int = 1, risk_free_rate: float | None = None,
                    target_return: float | None = None) -> dict[str, Any]:
        from .. import risk_v2
        if type(analysis_version) is not int or analysis_version not in (1, 2):
            raise risk_layer.RiskError("analysis_version must be 1 or 2")
        if analysis_version == 1 and (risk_free_rate is not None or target_return is not None):
            raise risk_layer.RiskError("risk_free_rate and target_return require analysis_version=2")
        risk_v2.scalar(risk_free_rate, "risk_free_rate")
        risk_v2.scalar(target_return, "target_return")
        requested = list(dict.fromkeys(run_ids or []))
        if not requested:
            raise risk_layer.RiskError("run_id is required")
        if periods_per_year is None:
            periods_per_year, annualisation_source = self.configuration.annualisation()
        else:
            annualisation_source = "caller"
        if type(periods_per_year) is not int or not 1 <= periods_per_year <= 1000:
            raise risk_layer.RiskError("periods_per_year must be between 1 and 1000")
        reports = []
        for run_id in requested:
            revision = self.get_revision(run_id)
            if revision is None:
                raise LookupError(f"run not found: {run_id}")
            if analysis_version == 2:
                reports.append(risk_v2.report(revision, periods_per_year=periods_per_year,
                                             annualisation_source=annualisation_source,
                                             risk_free_rate=risk_free_rate, target_return=target_return))
                continue
            view = series_view.return_series(revision)
            if view is None or len(view["values"]) < risk_layer.MIN_OBSERVATIONS:
                raise risk_layer.RiskError(
                    f"run {run_id} has no usable return series (need at least {risk_layer.MIN_OBSERVATIONS} observations)")
            report = risk_layer.performance_report(view["dates"], view["values"],
                                                   periods_per_year=periods_per_year)
            report["run_id"] = run_id
            report["title"] = revision["result"]["run"]["title"]
            report["return_source"] = view["source"]
            report["basis"]["dataset"] = revision["result"]["run"].get("dataset") or {}
            report["basis"]["periods_per_year_source"] = annualisation_source
            reports.append(report)
        return {**({"schema_version": 2} if analysis_version == 2 else {}),
                "items": reports, "count": len(reports),
                "periods_per_year": periods_per_year,
                "periods_per_year_source": annualisation_source,
                "scope": "每个运行独立计算；未接入项见各自的 not_available 列表"}
