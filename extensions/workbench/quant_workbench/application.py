"""Compatibility facade shared by HTTP and CLI; business use cases live in services."""
from __future__ import annotations
from typing import Any
from .ports import (WorkbenchRepository, AgentObservationPort, ResearchObservationPort,
                    DataDirectoryPort, AnalysisConfigurationPort)
from .provenance import capabilities_audit
from .services.results import ResultService, display_run_title, GENERIC_RUN_TITLES
from .services.comparison import ComparisonService
from .services.factors import FactorService
from .services.risk import RiskService
from .services.validation import ValidationService
from .services.catalog import CatalogService
from .services.attention import AttentionService
from .services.execution import ExecutionService

class WorkbenchService:
    GENERIC_RUN_TITLES = GENERIC_RUN_TITLES

    def __init__(self, repository: WorkbenchRepository, rdagent: AgentObservationPort | None = None,
                 research: ResearchObservationPort | None = None,
                 execution: ExecutionService | None = None,
                 data_directory: DataDirectoryPort | None = None, *,
                 analysis_configuration: AnalysisConfigurationPort | None = None):
        self.repository = repository
        self.rdagent = rdagent
        self.research = research
        self.execution_service = execution
        self.data_directory = data_directory
        if analysis_configuration is None:
            # Legacy direct constructors keep working; only bootstrap selects the adapter.
            from .bootstrap import default_analysis_configuration
            analysis_configuration = default_analysis_configuration()
        self.analysis_configuration = analysis_configuration
        self.results = ResultService(repository)
        self.comparison = ComparisonService(self.results)
        self.factors = FactorService(repository, lambda dataset: self.factor_snapshot_dir(dataset))
        self.risk = RiskService(self.results, analysis_configuration)
        self.validation = ValidationService(self.results)
        self.catalog = CatalogService(data_directory)
        self.attention_service = AttentionService(repository, execution is not None)

    def factor_snapshot_dir(self, dataset: dict[str, Any]):
        return self.analysis_configuration.factor_snapshot_dir(dataset)

    def import_package(self, source_instance_id: str, external_id: str, adapter_version: str,
                       package: dict[str, Any]) -> dict[str, Any]:
        return self.results.import_package(source_instance_id, external_id, adapter_version, package)

    def list_runs(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        return self.results.list_runs(limit, cursor)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.results.get_run(run_id)

    def list_revisions(self, run_id: str) -> list[dict[str, Any]]:
        return self.results.list_revisions(run_id)

    def list_revisions_page(self, run_id: str, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        return self.results.list_revisions_page(run_id, limit, cursor)

    def get_revision(self, run_id: str, revision_id: str | None = None) -> dict[str, Any] | None:
        return self.results.get_revision(run_id, revision_id)

    def get_series(self, run_id: str, metric_id: str, revision_id: str | None = None,
                   limit: int = 2000, offset: int = 0) -> dict[str, Any] | None:
        return self.results.get_series(run_id, metric_id, revision_id, limit, offset)

    def review(self, run_id, revision_id=None):
        return self.results.review(run_id, revision_id)

    def health(self) -> dict[str, Any]:
        return self.results.health()

    def compare(self, run_ids: list[str], metric_id: str, mode: str = "auto") -> dict[str, Any]:
        return self.comparison.compare(run_ids, metric_id, mode)

    def assess(self, run_ids: list[str], revisions: list[dict[str, Any]], metric_id: str,
               mode: str = "auto") -> dict[str, Any]:
        return self.comparison.assess(run_ids, revisions, metric_id, mode)

    def compare_table(self, run_ids: list[str], metric_ids: list[str] | None = None) -> dict[str, Any]:
        return self.comparison.compare_table(run_ids, metric_ids)

    def _table_descriptors(self, revisions, metric_ids):
        return self.comparison._table_descriptors(revisions, metric_ids)

    def import_factor_panel(self, identity: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        return self.factors.import_factor_panel(identity, payload)

    def list_factors(self) -> dict[str, Any]:
        return self.factors.list_factors()

    def factor_detail(self, factor_id: str, panel_id: str | None = None) -> dict[str, Any] | None:
        return self.factors.factor_detail(factor_id, panel_id)

    def _factor_dto(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.factors._factor_dto(row)

    def factor_analysis(self, factor_ids: list[str], horizons: list[int] | None = None, *,
                        analysis_version: int = 1) -> dict[str, Any]:
        return self.factors.factor_analysis(factor_ids, horizons, analysis_version=analysis_version)

    def risk_report(self, run_ids: list[str], periods_per_year: int | None = None, *,
                    analysis_version: int = 1, risk_free_rate: float | None = None,
                    target_return: float | None = None) -> dict[str, Any]:
        return self.risk.risk_report(run_ids, periods_per_year, analysis_version=analysis_version, risk_free_rate=risk_free_rate, target_return=target_return)

    def strategy_validation(self, run_ids: list[str], horizon: int = 1, splits: int = 5,
                            embargo: int | None = None, trials: int | None = None,
                            blocks: int = 8, *, analysis_version: int = 1,
                            revision_ids: list[str] | None = None) -> dict[str, Any]:
        return self.validation.strategy_validation(run_ids, horizon, splits, embargo, trials, blocks, analysis_version=analysis_version, revision_ids=revision_ids)

    def data_snapshots(self) -> dict[str, Any]:
        return self.catalog.data_snapshots()

    def data_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        return self.catalog.data_snapshot(snapshot_id)

    def attention(self, limit: int = 20) -> dict[str, Any]:
        return self.attention_service.attention(limit)

    def rdagent_status(self) -> dict[str, Any]:
        if self.rdagent is None:
            return {"availability": "not_connected", "reason": "RD-Agent checkout 未配置",
                    "chat": {"configured": False}, "embedding": {"configured": False},
                    "execution": {"available": False, "reasons": ["checkout_not_configured"]}, "traces": []}
        status = self.rdagent.status()
        if self.execution_service is None:
            return status
        items = [item for item in self.execution_service.catalog()["items"]
                 if item["executor_id"] == "rdagent_subprocess"]
        if not items:
            return status
        return {**status, "execution": {
            "available": any(item["available"] for item in items),
            "reasons": sorted({reason for item in items for reason in item["reasons"]}),
            "kinds": [{"kind": item["kind"], "label": item["label"], "available": item["available"],
                       "probe": item["probe"], "reasons": item["reasons"]} for item in items],
        }}

    def execution_catalog(self, refresh: bool = False) -> dict[str, Any]:
        if self.execution_service is None:
            return {"items": [], "checked_at": None,
                    "reason": "execution_not_configured"}
        return self.execution_service.catalog(refresh)

    def submit_execution(self, kind: str, params: dict[str, Any], idempotency_key: str | None,
                         request_id: str | None) -> dict[str, Any]:
        if self.execution_service is None:
            raise LookupError("execution service is not configured")
        return self.execution_service.submit(kind, params, idempotency_key, request_id)

    def executions(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        if self.execution_service is None:
            return {"items": [], "next_cursor": None, "reason": "execution_not_configured"}
        return self.execution_service.list(limit, cursor)

    def execution(self, attempt_id: str) -> dict[str, Any] | None:
        return None if self.execution_service is None else self.execution_service.get(attempt_id)

    def cancel_execution(self, attempt_id: str) -> dict[str, Any]:
        if self.execution_service is None:
            raise LookupError("execution service is not configured")
        return self.execution_service.cancel(attempt_id)

    def execution_log(self, attempt_id: str, tail: int = 200) -> dict[str, Any]:
        if self.execution_service is None:
            raise LookupError("execution service is not configured")
        return self.execution_service.log(attempt_id, tail)

    def import_execution(self, attempt_id: str) -> dict[str, Any]:
        if self.execution_service is None:
            raise LookupError("execution service is not configured")
        return self.execution_service.import_result(attempt_id)

    def execution_stats(self, window_seconds: int | None = None) -> dict[str, Any]:
        if self.execution_service is None:
            return {"availability": "empty", "reason": "execution_not_configured", "total": 0,
                    "window_seconds": window_seconds or 86400, "statuses": {}, "failure_rate": None,
                    "failure_denominator": 0, "by_kind": []}
        return self.execution_service.stats(window_seconds)

    def research_list(self, limit=20, offset=0, query=''):
        return self.research.listing(limit, offset, query) if self.research else {'items': [], 'total': 0, 'next_offset': None}

    def research_detail(self, identity):
        return self.research.detail(identity) if self.research else None

    def provenance_capabilities(self):
        return capabilities_audit()

    def capabilities(self) -> dict[str, Any]:
        execution = (self.execution_service.capabilities() if self.execution_service is not None
                     else {"executor": "not_implemented", "kinds": [], "executors": []})
        return {"result_importers": ["generic_json_v1", "qlib_mlflow_v2"],
                "executor": execution["executor"], "execution_kinds": execution["kinds"],
                "executors": execution["executors"],
                "live_data": "not_connected",
                "storage": "sqlite_local_objects_v1",
                "agent_observers": ["rdagent_checkout_v1"] if self.rdagent else []}
