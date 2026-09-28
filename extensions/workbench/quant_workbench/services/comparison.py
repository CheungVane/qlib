"""Comparison orchestration; one resolved revision set per table."""
from __future__ import annotations
from typing import Any

from .results import ResultService
from ..metrics import (COMPARE_ROWS, DIRECTIONS, EXTRA_ROW_LIMIT, GROUP_LABELS,
                       RANKABLE_GROUPS, coordinate, metric_group, rank, row_value, summarize)
from .. import metrics as metrics_layer

class ComparisonService:
    def __init__(self, results: ResultService):
        self.results = results

    def get_revision(self, run_id, revision_id=None):
        return self.results.get_revision(run_id, revision_id)

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
        # Identity layering (RESULT_CONTRACT): dataset + execution_id + evaluation_id must all be
        # known and equal. Money/return/risk rows additionally need the资金口径 fields whichever
        # mode the caller picked — `mode=metric` must not bypass the equity requirements (T03).
        applicability = metrics_layer.field_applicability(metric_id)
        check([c.get('evaluation_id') for c in contexts], 'evaluation_unknown_or_differs')
        if mode == 'equity' or applicability['requires_execution_id']:
            check([c.get('execution_id') for c in contexts], 'execution_scenario_unknown_or_differs')
        if mode == 'equity' or applicability['requires_money_basis']:
            for key in metrics_layer.MONEY_BASIS_FIELDS:
                check([c.get(key) for c in contexts], key+'_unknown_or_differs')
            if any(c.get('cashflow_policy') != 'none' for c in contexts): reasons.append('cashflow_not_supported')
            if any(type(c.get('initial_equity')) not in (int,float) or c['initial_equity'] <= 0 for c in contexts):
                reasons.append('initial_equity_invalid')
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
