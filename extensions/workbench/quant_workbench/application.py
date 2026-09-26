"""Shared application service for CLI and HTTP adapters."""

from __future__ import annotations

from typing import Any

from .ports import AgentObservationPort, ResultRepository
from .provenance import classify, capabilities_audit
from .metrics import summarize, coordinate


class WorkbenchService:
    def __init__(self, repository: ResultRepository, rdagent: AgentObservationPort | None = None, research=None):
        self.repository = repository
        self.rdagent = rdagent
        self.research = research

    def rdagent_status(self) -> dict[str, Any]:
        if self.rdagent is None:
            return {"availability": "not_connected", "reason": "RD-Agent checkout 未配置",
                    "chat": {"configured": False}, "embedding": {"configured": False},
                    "execution": {"available": False, "reasons": ["checkout_not_configured"]}, "traces": []}
        return self.rdagent.status()

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

    def provenance_capabilities(self):
        return capabilities_audit()

    def capabilities(self) -> dict[str, Any]:
        return {"result_importers": ["generic_json_v1", "qlib_mlflow_v2"],
                "executor": "not_implemented", "live_data": "not_connected",
                "storage": "sqlite_local_objects_v1",
                "agent_observers": ["rdagent_checkout_v1"] if self.rdagent else []}

    def health(self) -> dict[str, Any]:
        return self.repository.health()
