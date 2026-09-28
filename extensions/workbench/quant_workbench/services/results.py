"""Result import, immutable revision queries and source projections."""
from __future__ import annotations
from typing import Any

from ..ports import ResultRepository
from ..provenance import classify
from ..metrics import summarize

GENERIC_RUN_TITLES = {"mlflow_recorder", "mlflow", "default", ""}

def display_run_title(run: dict[str, Any] | None) -> str:
    """Reader-facing title; engine/date composition lives on the server, not in the UI."""
    run = run or {}
    title = (run.get("title") or "").strip()
    if title and title not in GENERIC_RUN_TITLES:
        return title
    engine = ((run.get("engine") or {}).get("id") or "结果").strip()
    stamp = (run.get("created_at") or "")[:10]
    return f"{engine} 回测 · {stamp}".strip(" ·")

class ResultService:
    def __init__(self, repository: ResultRepository):
        self.repository = repository

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

    def review(self, run_id, revision_id=None):
        from ..research import review_result
        revision = self.get_revision(run_id, revision_id)
        return review_result(revision['result']) if revision else None

    def health(self) -> dict[str, Any]:
        return self.repository.health()
