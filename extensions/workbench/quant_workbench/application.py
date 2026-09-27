"""Shared application service for CLI and HTTP adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .ports import AgentObservationPort, ResultRepository
from .provenance import classify, capabilities_audit
from .metrics import (
    COMPARE_ROWS, DIRECTIONS, EXTRA_ROW_LIMIT, GROUP_LABELS, RANKABLE_GROUPS, coordinate,
    metric_group, rank, row_value, summarize,
)
from . import factors as factor_layer
from . import validation as validation_layer
from . import risk as risk_layer
from . import series_view


def display_run_title(run: dict[str, Any] | None) -> str:
    """Reader-facing title; engine/date composition lives on the server, not in the UI."""
    run = run or {}
    title = (run.get("title") or "").strip()
    if title and title not in WorkbenchService.GENERIC_RUN_TITLES:
        return title
    engine = ((run.get("engine") or {}).get("id") or "结果").strip()
    stamp = (run.get("created_at") or "")[:10]
    return f"{engine} 回测 · {stamp}".strip(" ·")


class WorkbenchService:
    # Engine defaults that carry no information for a reader; the display title is composed
    # here (server side) so the UI never has to branch on engine names (ARC03).
    GENERIC_RUN_TITLES = {"mlflow_recorder", "mlflow", "default", ""}

    def __init__(self, repository: ResultRepository, rdagent: AgentObservationPort | None = None,
                 research=None, execution=None):
        self.repository = repository
        self.rdagent = rdagent
        self.research = research
        # named *_service so the attribute cannot shadow the read methods below
        self.execution_service = execution

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

    def review(self, run_id, revision_id=None):
        from .research import review_result
        revision = self.get_revision(run_id, revision_id)
        return review_result(revision['result']) if revision else None

    def import_package(self, source_instance_id: str, external_id: str, adapter_version: str,
                       package: dict[str, Any]) -> dict[str, Any]:
        return self.repository.publish(source_instance_id, external_id, adapter_version, package)

    def list_runs(self, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        result = self.repository.list_runs(limit, cursor)
        for row in result['items']:
            revision = self.get_revision(row['run_id'], row['revision_id'])
            row['run']['provenance'] = revision['provenance']['run']
            row['display_title'] = display_run_title(row['run'])
        return result

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.repository.get_run(run_id)
        if row:
            row['run']['provenance'] = self.get_revision(run_id, row['revision_id'])['provenance']['run']
            row['display_title'] = display_run_title(row['run'])
        return row

    def list_revisions(self, run_id: str) -> list[dict[str, Any]]:
        return self.repository.list_revisions(run_id)

    def list_revisions_page(self, run_id: str, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        return self.repository.list_revisions_page(run_id, limit, cursor)

    # -- factor layer (FACTOR_ANALYSIS U18/U19) ---------------------------
    def import_factor_panel(self, identity: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        panel = factor_layer.canonical_panel(payload)
        return self.repository.publish_factor(identity, panel)

    def list_factors(self) -> dict[str, Any]:
        return {"items": [self._factor_dto(row) for row in self.repository.list_factors()]}

    def factor_detail(self, factor_id: str, panel_id: str | None = None) -> dict[str, Any] | None:
        row = self.repository.get_factor(factor_id)
        if row is None:
            return None
        stored = self.repository.get_factor_panel(factor_id, panel_id)
        if stored is None:
            return {**self._factor_dto(row), "panels": [], "panel": None}
        panel = stored.pop("panel")
        preview_rows = min(panel["date_count"], 3)
        preview_columns = min(panel["instrument_count"], 8)
        width = panel["instrument_count"]
        preview = {
            "dates": panel["dates"][:preview_rows],
            "instruments": panel["instruments"][:preview_columns],
            "values": [panel["values"][row_index * width:row_index * width + preview_columns]
                       for row_index in range(preview_rows)],
            "truncated": panel["date_count"] > preview_rows or panel["instrument_count"] > preview_columns,
        }
        return {**self._factor_dto(row), "panels": self.repository.list_factor_panels(factor_id),
                "panel": {**stored, "coverage": panel["coverage"], "value_stats": panel["value_stats"],
                          "preview": preview}}

    def _factor_dto(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in
                ("factor_id", "name", "source_instance_id", "external_id", "definition", "dataset",
                 "calendar_id", "provenance", "created_at", "panel_count")}

    def factor_analysis(self, factor_ids: list[str], horizons: list[int] | None = None, *,
                        analysis_version: int = 1) -> dict[str, Any]:
        if type(analysis_version) is not int or analysis_version not in (1, 2):
            raise factor_layer.FactorError("analysis_version must be 1 or 2")
        if not factor_ids:
            raise factor_layer.FactorError("factor_id is required")
        requested = list(dict.fromkeys(factor_ids))
        if len(requested) > factor_layer.MAX_FACTORS_PER_ANALYSIS:
            raise factor_layer.FactorError(
                f"at most {factor_layer.MAX_FACTORS_PER_ANALYSIS} factors per analysis")
        entries, datasets, calendars = [], [], set()
        for factor_id in requested:
            row = self.repository.get_factor(factor_id)
            if row is None:
                raise LookupError(f"factor not found: {factor_id}")
            stored = self.repository.get_factor_panel(factor_id)
            if stored is None:
                raise factor_layer.FactorError(f"factor has no panel: {factor_id}")
            entries.append({"factor_id": factor_id, "name": row["name"], "panel": stored["panel"],
                            "panel_id": stored["panel_id"], "content_hash": stored["content_hash"],
                            "provenance": row.get("provenance")})
            datasets.append(row.get("dataset") or {})
            if row.get("calendar_id"):
                calendars.add(row["calendar_id"])
            elif analysis_version == 2:
                raise factor_layer.FactorError("v2 requires a recorded calendar identity")
        versions = {(item.get("id"), item.get("version")) for item in datasets}
        if len(versions) != 1:
            raise factor_layer.FactorError("factors must share one dataset id and content version")
        dataset = datasets[0]
        if len(calendars) > 1:
            raise factor_layer.FactorError("factors must share one calendar")
        snapshot = self.factor_snapshot_dir(dataset)
        digest = factor_layer.verify_snapshot(snapshot, dataset)
        if analysis_version == 2:
            from .factors_v2 import align
            if len({entry["name"] for entry in entries}) != len(entries):
                raise factor_layer.FactorError("v2 requires distinct factor names for name-keyed diagnostics")
            entries = align(entries, snapshot)
        panels = [entry["panel"] for entry in entries]
        dates, instruments = factor_layer.aligned_rows(panels)
        prices = factor_layer.load_close_series(snapshot, dates, instruments)
        window = tuple(sorted(set(horizons or factor_layer.DEFAULT_HORIZONS)))
        if any(isinstance(h, bool) or not isinstance(h, int) or not 1 <= h <= 60 for h in window):
            raise factor_layer.FactorError("horizons must be integers between 1 and 60")
        returns = {h: factor_layer.forward_returns(prices["values"], h) for h in window}
        limitations = []
        if prices["missing_instruments"]:
            limitations.append(f"{len(prices['missing_instruments'])} 个标的在快照中缺价格，未参与计算")
        report = factor_layer.analyze(entries, returns, horizons=window, dataset=dataset,
                                      calendar_id=next(iter(calendars), None), limitations=tuple(limitations),
                                      analysis_version=analysis_version)
        report["basis"]["snapshot"] = {"label": snapshot.name, "content_digest": digest["digest"],
                                       "files": digest["file_count"], "price_fields": prices["fields"]}
        return report

    def factor_snapshot_dir(self, dataset: dict[str, Any]):
        """Resolve the recorded snapshot for a dataset identity through the single config source."""
        from .cn_market import default_profile_path, discover_project_root, load_profile
        label = (dataset or {}).get("snapshot_label")
        if not label:
            raise factor_layer.FactorError("factor dataset has no snapshot label recorded")
        root = discover_project_root()
        data_path = Path(load_profile(default_profile_path())["research"]["data_path"])
        base = data_path if data_path.is_absolute() else (root / data_path)
        return (base / label).resolve()

    # -- validation (VALIDATION.md U20) ------------------------------------
    def strategy_validation(self, run_ids: list[str], horizon: int = 1, splits: int = 5,
                            embargo: int | None = None, trials: int | None = None,
                            blocks: int = 8, *, analysis_version: int = 1,
                            revision_ids: list[str] | None = None) -> dict[str, Any]:
        if type(analysis_version) is not int or analysis_version not in (1, 2):
            raise validation_layer.ValidationError("analysis_version must be 1 or 2")
        requested = list(dict.fromkeys(run_ids or []))
        if not requested:
            raise validation_layer.ValidationError("run_id is required")
        if len(requested) > 20:
            raise validation_layer.ValidationError("at most 20 configurations per validation")
        if revision_ids and len(revision_ids) != len(requested):
            raise validation_layer.ValidationError(
                "revision_id must be paired one-to-one with run_id")
        configs = []
        for index, run_id in enumerate(requested):
            revision = self.get_revision(run_id, revision_ids[index] if revision_ids else None)
            if revision is None:
                raise LookupError(f"run not found: {run_id}")
            if analysis_version == 2:
                from . import risk_v2
                view = risk_v2.input_view(revision)
                reason = view["reason"]
                if reason == "insufficient_observations":
                    reason = None  # validation v2 applies its own >=10 threshold
                configs.append({"run_id": run_id, "revision_id": revision["revision_id"],
                                "dates": view["dates"], "values": view["values"],
                                "reason": reason, "input_basis": view.get("input_basis"),
                                "resolution": "explicit" if revision_ids else "latest_at_request",
                                "dataset": revision["result"]["run"].get("dataset") or {}})
                continue
            view = series_view.return_series(revision)
            if view is None or len(view["values"]) < 20:
                raise validation_layer.ValidationError(
                    f"run {run_id} has no usable return series (need at least 20 observations)")
            configs.append({"run_id": run_id, "title": revision["result"]["run"]["title"],
                            "dates": view["dates"], "returns": view["values"],
                            "return_source": view["source"],
                            "dataset": revision["result"]["run"].get("dataset") or {}})
        if analysis_version == 2:
            from . import validation_v2
            return validation_v2.build_report(configs, horizon=horizon, splits=splits,
                                              embargo=embargo, blocks=blocks, trials=trials)
        return validation_layer.validation_report(configs, horizon=horizon, splits=splits,
                                                  embargo=embargo, trials=trials, blocks=blocks)

    # -- performance and risk (U22) ----------------------------------------
    def risk_report(self, run_ids: list[str], periods_per_year: int | None = None, *,
                    analysis_version: int = 1, risk_free_rate: float | None = None,
                    target_return: float | None = None) -> dict[str, Any]:
        from . import risk_v2
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
            from .cn_market import default_profile_path, load_profile
            try:
                periods_per_year = int(load_profile(default_profile_path())["research"]["annualization"]
                                       ["native_portfolio_days"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                # RESULT_CONTRACT: annualisation must come from the configuration, never a default.
                raise risk_layer.RiskError(
                    f"无法从配置读取年化交易日（{type(exc).__name__}）；按结果合同不得使用默认值") from exc
            annualisation_source = "config: configs/cn/profile.json"
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

    # -- attention centre (UI07 / U21) -------------------------------------
    def attention(self, limit: int = 20) -> dict[str, Any]:
        """What the operator should look at next, from state we actually have."""
        items: list[dict[str, Any]] = []
        if self.execution_service is not None:
            for row in self.repository.list_attempts(limit=100)["items"]:
                outcome = row.get("outcome") or {}
                imported = outcome.get("result_import") if isinstance(outcome, dict) else None
                attempt = row["attempt_id"][:8]
                if row["status"] in ("failed", "interrupted"):
                    items.append({"kind": "execution_failed", "severity": "high",
                                  "title": f"执行{ '失败' if row['status']=='failed' else '中断'}：{row['label']}",
                                  "detail": row.get("error_message") or row.get("error_code") or "原因未记录",
                                  "target": {"view": "agent", "history": "attempts"}, "ref": attempt})
                elif row["status"] == "running" and row.get("cancel_requested_at"):
                    items.append({"kind": "cancel_pending", "severity": "medium",
                                  "title": f"取消请求中：{row['label']}",
                                  "detail": "等待执行器确认进程结束；未确认前状态仍是运行中",
                                  "target": {"view": "agent", "history": "attempts"}, "ref": attempt})
                elif row["status"] == "succeeded" and isinstance(imported, dict) and \
                        imported.get("status") in ("failed", "manual_import_required"):
                    items.append({"kind": "result_not_imported", "severity": "medium",
                                  "title": f"结果未入库：{row['label']}",
                                  "detail": imported.get("reason") or "需要显式导入或可信离线导出",
                                  "target": {"view": "agent", "history": "attempts"}, "ref": attempt})
                elif row["status"] == "succeeded" and row.get("probe"):
                    items.append({"kind": "probe_result", "severity": "low",
                                  "title": f"探针结果：{row['label']}",
                                  "detail": "集成探针只验证链路，不代表研究成果",
                                  "target": {"view": "agent", "history": "attempts"}, "ref": attempt})
        counts = {"high": 0, "medium": 0, "low": 0}
        for item in items:
            counts[item["severity"]] = counts.get(item["severity"], 0) + 1
        return {"items": items[:limit], "total": len(items), "counts": counts,
                "scope": "来自已记录的执行与结果状态；未接入项（数据新鲜度、实时行情）不在此列",
                "generated_at": factor_layer.utc_now()}

    def get_revision(self, run_id: str, revision_id: str | None = None) -> dict[str, Any] | None:
        revision = self.repository.get_revision(run_id, revision_id)
        if revision:
            revision['provenance'] = classify(revision['result'], revision['adapter_version'])
        return revision

    def get_series(self, run_id: str, metric_id: str, revision_id: str | None = None,
                   limit: int = 2000, offset: int = 0) -> dict[str, Any] | None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2000:
            raise ValueError("limit must be between 1 and 2000")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be nonnegative")
        revision = self.get_revision(run_id, revision_id)
        if revision is None:
            return None
        entry = next((x for x in revision["result"]["series"] if x["metric_id"] == metric_id), None)
        if entry is None:
            return None
        points = entry["points"]
        return {"run_id": run_id, "revision_id": revision["revision_id"],
                "series": {**entry, "points": points[offset:offset + limit]},
                "summary": summarize(entry),
                "total_points": len(points), "offset": offset, "limit": limit,
                "next_offset": offset + limit if offset + limit < len(points) else None,
                "downsampled": False}

    def compare(self, run_ids: list[str], metric_id: str, mode: str = "auto") -> dict[str, Any]:
        if not 2 <= len(run_ids) <= 10 or len(set(run_ids)) != len(run_ids):
            raise ValueError("provide 2 to 10 distinct run IDs")
        if mode not in {"auto", "equity", "metric"}:
            raise ValueError("unknown comparison mode")
        revisions = []
        for run_id in run_ids:
            revision = self.get_revision(run_id)
            if revision is None:
                return {"status": "incompatible", "reasons": [f"run_not_found:{run_id}"]}
            revisions.append(revision)
        return self.assess(run_ids, revisions, metric_id, mode)

    def assess(self, run_ids: list[str], revisions: list[dict[str, Any]], metric_id: str,
               mode: str = "auto") -> dict[str, Any]:
        """One口径 implementation reused by compare() and compare_table() (no re-reads)."""
        mode = ("equity" if metric_id == "platform.equity" else "metric") if mode == "auto" else mode
        if (mode == "equity") != (metric_id == "platform.equity"):
            raise ValueError("comparison mode does not match metric")
        found = []
        for run_id, revision in zip(run_ids, revisions):
            metric = next((x for x in revision["result"]["series"] if x["metric_id"] == metric_id), None)
            if metric is None or metric["availability"] != "available":
                return {"status": "incompatible", "reasons": [f"metric_unavailable:{run_id}"]}
            found.append((revision["result"]["run"], metric))

        reasons = []
        overlay_reasons = []
        def known(value):
            return value is not None and value != '' and value != 'unknown' and not (
                isinstance(value, str) and ('unspecified' in value or '.unknown' in value))
        def check(values, reason, overlay=False):
            if not all(known(v) for v in values) or any(v != values[0] for v in values):
                reasons.append(reason)
                if overlay: overlay_reasons.append(reason)
        for key in ('unit', 'axis', 'definition_id'):
            check([m.get(key) for _,m in found], key+'_differs', key != 'definition_id')
        axes = {m['axis'] for _,m in found}
        for axis,key in (('trading_date','calendar_id'), ('step','step_kind')):
            if axis in axes:
                check([m.get(key) for _,m in found], key+'_differs', True)
        if mode == 'equity' or any(m.get('currency') is not None or m['unit'] in ('CNY','USD','EUR','HKD','JPY') for _,m in found):
            check([m.get('currency') for _,m in found], 'currency_differs', True)
        if len({r['synthetic'] for r,_ in found}) != 1:
            reasons.append('synthetic_and_real_mixed')
        if any(rev['result'].get('evidence', {}).get('fixture') for rev in revisions):
            reasons.append('handwritten_fixture_present')
        if any(rev['adapter_version'] == 'rdagent_history_v1' for rev in revisions):
            reasons.append('legacy_experiment_attribution_unverified')
        check([r['dataset']['id'] for r,_ in found], 'dataset_id_differs')
        check([r['dataset'].get('version') for r,_ in found], 'dataset_version_unknown_or_differs')
        coords = [[coordinate(m,p) for p in m['points']] for _,m in found]
        if any(c != coords[0] for c in coords): reasons.append('coverage_axis_differs')
        windows = {(c[0],c[-1]) for c in coords if c}
        if len(windows) != 1: reasons.append('date_window_differs')
        if any(not summarize(m)['complete'] for _,m in found): reasons.append('missing_observations')
        contexts = [rev['result'].get('evidence', {}).get('comparison', {}) for rev in revisions]
        if mode == 'equity':
            check([c.get('execution_id') for c in contexts], 'execution_scenario_unknown_or_differs')
            for key in ('initial_equity','cashflow_policy','price_basis','benchmark_id'):
                check([c.get(key) for c in contexts], key+'_unknown_or_differs')
            if any(c.get('cashflow_policy') != 'none' for c in contexts): reasons.append('cashflow_not_supported')
            if any(type(c.get('initial_equity')) not in (int,float) or c['initial_equity'] <= 0 for c in contexts):
                reasons.append('initial_equity_invalid')
        else:
            check([c.get('evaluation_id') for c in contexts], 'evaluation_unknown_or_differs')
        # Research experiment identity may differ: listed as an experimental variable (U17/B-1).
        experiments = [c.get('experiment_id') for c in contexts]
        variables = []
        if any(not known(value) for value in experiments):
            variables.append('experiment_id_unknown')
        elif len(set(experiments)) != 1:
            variables.append('experiment_id_differs')
        group = metric_group(metric_id)
        if group not in RANKABLE_GROUPS:
            reasons.append(f'group_only_side_by_side:{group}')
        return {'mode': mode, 'status':'comparable' if not reasons else 'partial',
                'overlay_allowed':not overlay_reasons, 'ranking_allowed':not reasons,
                'reasons':reasons, 'experiment_variables':variables, 'group': group,
                'group_label': GROUP_LABELS.get(group, group),
                'revisions':{rid:rev['revision_id'] for rid,rev in zip(run_ids,revisions)}}

    def compare_table(self, run_ids: list[str], metric_ids: list[str] | None = None) -> dict[str, Any]:
        """UI06: one row per metric, one column per run; best/worst are decided here, not in the UI."""
        if not 2 <= len(run_ids) <= 10 or len(set(run_ids)) != len(run_ids):
            raise ValueError("provide 2 to 10 distinct run IDs")
        revisions = []
        for run_id in run_ids:
            revision = self.get_revision(run_id)
            if revision is None:
                return {"status": "incompatible", "reasons": [f"run_not_found:{run_id}"],
                        "run_ids": list(run_ids), "runs": [], "rows": []}
            revisions.append(revision)
        rows = []
        for descriptor in self._table_descriptors(revisions, metric_ids):
            assessment = self.assess(run_ids, revisions, descriptor["metric_id"], "auto")
            if assessment.get("status") == "incompatible":
                allowed, reasons = False, list(assessment.get("reasons", []))
                variables = list(assessment.get("experiment_variables", []))
            else:
                allowed, reasons = bool(assessment.get("ranking_allowed")), list(assessment.get("reasons", []))
                variables = list(assessment.get("experiment_variables", []))
            direction = descriptor.get("direction", "unknown")
            if direction not in ("higher_better", "lower_better"):
                if allowed:
                    reasons = [*reasons, "direction_not_registered"]
                allowed = False
            cells, values = [], []
            for run_id, revision in zip(run_ids, revisions):
                series = next((x for x in revision["result"]["series"]
                               if x["metric_id"] == descriptor["metric_id"]), None)
                unit = descriptor.get("unit") or (series or {}).get("unit")
                if series is None:
                    availability, reason, value = "not_recorded", "metric_not_in_revision", None
                elif series["availability"] != "available":
                    availability, reason, value = series["availability"], series.get("reason"), None
                else:
                    summary = summarize(series)
                    value = row_value(series, descriptor["aggregation"], summary)
                    availability = "available" if value is not None else "empty"
                    reason = None if value is not None else (summary.get("last_reason") or "no_valid_point")
                values.append(value)
                cells.append({"run_id": run_id, "value": value, "availability": availability,
                              "unit": unit, "reason": reason})
            if not allowed:
                marks = [None] * len(cells)
                ties = {"tied_best": False, "tied_worst": False}
            else:
                ranking = rank(values, direction)
                marks = ranking["marks"]
                ties = {"tied_best": ranking["tied_best"], "tied_worst": ranking["tied_worst"]}
            extra_reasons = list(reasons)
            if allowed and not any(marks):
                allowed = False
                extra_reasons = [*extra_reasons,
                                 "values_within_tolerance" if ranking["within_tolerance"]
                                 else "values_equal_or_incomplete"]
            for cell, mark in zip(cells, marks):
                cell["mark"] = mark
                cell["tied"] = bool(mark == "best" and ties["tied_best"]
                                    or mark == "worst" and ties["tied_worst"])
            rows.append({
                "metric_id": descriptor["metric_id"], "label": descriptor["label"],
                "aggregation": descriptor["aggregation"], "direction": direction,
                "direction_label": DIRECTIONS.get(direction, DIRECTIONS["unknown"]),
                "group": metric_group(descriptor["metric_id"]),
                "group_label": GROUP_LABELS.get(metric_group(descriptor["metric_id"]),
                                                metric_group(descriptor["metric_id"])),
                "unit": next((cell["unit"] for cell in cells if cell["unit"]), None),
                "ranking_allowed": allowed, "reasons": sorted(set(extra_reasons)),
                "experiment_variables": sorted(set(variables)), "cells": cells,
            })
        overall = sorted({reason for row in rows for reason in row["reasons"]})
        experiment_variables = sorted({variable for row in rows for variable in row["experiment_variables"]})
        return {
            "status": "comparable" if rows and all(row["ranking_allowed"] for row in rows) else "partial",
            "ranking_allowed": bool(rows) and all(row["ranking_allowed"] for row in rows),
            "reasons": overall,
            "experiment_variables": experiment_variables,
            "run_ids": list(run_ids),
            "runs": [{"run_id": run_id, "title": revision["result"]["run"]["title"],
                      "engine_id": revision["result"]["run"]["engine"]["id"],
                      "dataset_id": revision["result"]["run"]["dataset"]["id"],
                      "dataset_version": revision["result"]["run"]["dataset"].get("version"),
                      "synthetic": revision["result"]["run"]["synthetic"]}
                     for run_id, revision in zip(run_ids, revisions)],
            "revisions": {run_id: revision["revision_id"] for run_id, revision in zip(run_ids, revisions)},
            "rows": rows,
        }

    def _table_descriptors(self, revisions, metric_ids):
        descriptors = [dict(row) for row in COMPARE_ROWS]
        if metric_ids:
            wanted, known = list(dict.fromkeys(metric_ids)), {d["metric_id"] for d in descriptors}
            descriptors = [d for d in descriptors if d["metric_id"] in wanted]
            for metric_id in wanted:
                if metric_id not in known:
                    descriptors.append({"metric_id": metric_id, "label": metric_id,
                                        "aggregation": "last", "direction": "unknown"})
            return descriptors
        covered = {d["metric_id"] for d in descriptors}
        shared = None
        for revision in revisions:
            present = {x["metric_id"] for x in revision["result"]["series"]
                       if x["availability"] == "available"}
            shared = present if shared is None else (shared & present)
        extras = sorted((shared or set()) - covered)[:EXTRA_ROW_LIMIT]
        descriptors.extend({"metric_id": metric_id, "label": metric_id, "aggregation": "last",
                            "direction": "unknown"} for metric_id in extras)
        return descriptors

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

    def health(self) -> dict[str, Any]:
        return self.repository.health()
