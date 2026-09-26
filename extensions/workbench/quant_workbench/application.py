"""Shared application service for CLI and HTTP adapters."""

from __future__ import annotations

from typing import Any

from .ports import AgentObservationPort, ResultRepository
from .provenance import classify, capabilities_audit
from .metrics import (
    COMPARE_ROWS, DIRECTIONS, EXTRA_ROW_LIMIT, coordinate, rank, row_value, summarize,
)


class WorkbenchService:
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
        return result

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.repository.get_run(run_id)
        if row:
            row['run']['provenance'] = self.get_revision(run_id, row['revision_id'])['provenance']['run']
        return row

    def list_revisions(self, run_id: str) -> list[dict[str, Any]]:
        return self.repository.list_revisions(run_id)

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
        mode = ("equity" if metric_id == "platform.equity" else "metric") if mode == "auto" else mode
        if (mode == "equity") != (metric_id == "platform.equity"):
            raise ValueError("comparison mode does not match metric")
        found = []
        revisions = []
        for run_id in run_ids:
            revision = self.get_revision(run_id)
            if revision is None:
                return {"status": "incompatible", "reasons": [f"run_not_found:{run_id}"]}
            metric = next((x for x in revision["result"]["series"] if x["metric_id"] == metric_id), None)
            if metric is None or metric["availability"] != "available":
                return {"status": "incompatible", "reasons": [f"metric_unavailable:{run_id}"]}
            revisions.append(revision)
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
        return {'mode': mode, 'status':'comparable' if not reasons else 'partial',
                'overlay_allowed':not overlay_reasons, 'ranking_allowed':not reasons,
                'reasons':reasons, 'revisions':{rid:rev['revision_id'] for rid,rev in zip(run_ids,revisions)}}

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
            assessment = self.compare(run_ids, descriptor["metric_id"], "auto")
            if assessment.get("status") == "incompatible":
                allowed, reasons = False, list(assessment.get("reasons", []))
            else:
                allowed, reasons = bool(assessment.get("ranking_allowed")), list(assessment.get("reasons", []))
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
                "unit": next((cell["unit"] for cell in cells if cell["unit"]), None),
                "ranking_allowed": allowed, "reasons": sorted(set(extra_reasons)), "cells": cells,
            })
        overall = sorted({reason for row in rows for reason in row["reasons"]})
        return {
            "status": "comparable" if rows and all(row["ranking_allowed"] for row in rows) else "partial",
            "ranking_allowed": bool(rows) and all(row["ranking_allowed"] for row in rows),
            "reasons": overall,
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
