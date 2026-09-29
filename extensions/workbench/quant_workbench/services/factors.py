"""Factor use cases; algorithms remain versioned, input environment injected."""
from __future__ import annotations
from typing import Any

from collections.abc import Callable
from pathlib import Path
from ..ports import FactorRepository, FactorDataPort
from ..domain.errors import SnapshotError
from .. import factors as factor_layer

class FactorService:
    def __init__(self, repository: FactorRepository,
                 snapshot_resolver: Callable[[dict[str, Any]], Path], market_data: FactorDataPort | None = None):
        self.market_data = market_data
        self.repository = repository
        self.factor_snapshot_dir = snapshot_resolver

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
        window = tuple(sorted(set(horizons or factor_layer.DEFAULT_HORIZONS)))
        if any(isinstance(h, bool) or not isinstance(h, int) or not 1 <= h <= 60 for h in window):
            raise factor_layer.FactorError("horizons must be integers between 1 and 60")
        if str(dataset.get('id', '')).startswith('snapshot:'):
            if self.market_data is None:
                raise SnapshotError('snapshot_unverified', dataset['id'].removeprefix('snapshot:'))
            source = self.market_data.resolve(dataset, next(iter(calendars), None))
            from ..factors_v2 import align
            entries = align(entries, calendar=source.calendar())
            dates, instruments = factor_layer.aligned_rows([entry['panel'] for entry in entries])
            inputs = source.read(dates, instruments, window)
            # Apply the same observed membership/status mask to every factor family.
            entries = [{**entry, 'panel': factor_layer.canonical_panel({**entry['panel'],
                        'values': [v if keep else None for v, keep in zip(entry['panel']['values'], inputs['membership'])]})}
                       for entry in entries]
            returns, snapshot_basis, limitations = inputs['labels'], inputs['basis'], inputs['limitations']
        else:
            snapshot = self.factor_snapshot_dir(dataset)
            digest = factor_layer.verify_snapshot(snapshot, dataset)
            if analysis_version == 2:
                from ..factors_v2 import align
                entries = align(entries, snapshot)
            dates, instruments = factor_layer.aligned_rows([entry['panel'] for entry in entries])
            prices = factor_layer.load_close_series(snapshot, dates, instruments)
            returns = {h: factor_layer.forward_returns(prices['values'], h) for h in window}
            limitations = []
            if prices['missing_instruments']:
                limitations.append(f"{len(prices['missing_instruments'])} 个标的在快照中缺价格，未参与计算")
            snapshot_basis = {'label': snapshot.name, 'content_digest': digest['digest'],
                              'files': digest['file_count'], 'price_fields': prices['fields']}
        if analysis_version == 2 and len({entry['name'] for entry in entries}) != len(entries):
            raise factor_layer.FactorError('v2 requires distinct factor names for name-keyed diagnostics')
        report = factor_layer.analyze(entries, returns, horizons=window, dataset=dataset,
                                      calendar_id=next(iter(calendars), None), limitations=tuple(limitations),
                                      analysis_version=analysis_version)
        report['basis']['snapshot'] = snapshot_basis
        return report
