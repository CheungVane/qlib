"""Shared application service for CLI and HTTP adapters."""

from __future__ import annotations

from typing import Any

from .ports import AgentObservationPort, ResultRepository
from .provenance import classify, capabilities_audit


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
                "total_points": len(points), "offset": offset, "limit": limit,
                "next_offset": offset + limit if offset + limit < len(points) else None,
                "downsampled": False}

    def compare(self, run_ids: list[str], metric_id: str) -> dict[str, Any]:
        if not 2 <= len(run_ids) <= 10 or len(set(run_ids)) != len(run_ids):
            raise ValueError("provide 2 to 10 distinct run IDs")
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
        for key in ("unit", "axis", "definition_id"):
            if len({metric.get(key) for _, metric in found}) != 1:
                reasons.append(f"{key}_differs")
        for key in ("calendar_id", "currency"):
            if len({metric.get(key) for _, metric in found}) != 1:
                reasons.append(f"{key}_differs")
        if len({run["synthetic"] for run, _ in found}) != 1:
            reasons.append("synthetic_and_real_mixed")
        if any(r.get('synthetic') and rev['result'].get('evidence', {}).get('fixture') for (r, _), rev in zip(found, revisions)):
            reasons.append('handwritten_fixture_present')
        dataset_versions = {run["dataset"].get("version") for run, _ in found}
        if None in dataset_versions or len(dataset_versions) > 1:
            reasons.append("dataset_version_unknown_or_differs")
        windows = {(m['points'][0]['x'], m['points'][-1]['x']) for _, m in found if m['points']}
        if len(windows) != 1: reasons.append('date_window_differs')
        if metric_id == 'platform.equity' and len({m['points'][0]['value'] for _, m in found if m['points']}) != 1:
            reasons.append('first_equity_differs')
        scenarios = {r['result'].get('evidence', {}).get('cn_scenario', {}).get('fingerprint') for r in revisions}
        if None in scenarios or len(scenarios) != 1: reasons.append('execution_scenario_unknown_or_differs')
        return {"status": "comparable" if not reasons else "partial",
                "overlay_allowed": not any(r in reasons for r in ("unit_differs", "axis_differs", "calendar_id_differs", "currency_differs")),
                "ranking_allowed": not reasons, "reasons": reasons,
                "revisions": {rid: rev["revision_id"] for rid, rev in zip(run_ids, revisions)}}

    def provenance_capabilities(self):
        return capabilities_audit()

    def capabilities(self) -> dict[str, Any]:
        return {"result_importers": ["generic_json_v1", "qlib_mlflow_v1"],
                "executor": "not_implemented", "live_data": "not_connected",
                "storage": "sqlite_local_objects_v1",
                "agent_observers": ["rdagent_checkout_v1"] if self.rdagent else []}

    def health(self) -> dict[str, Any]:
        return self.repository.health()
