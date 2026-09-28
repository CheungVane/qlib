"""Post-hoc validation only; does not claim real fold training."""
from __future__ import annotations
from typing import Any

from .. import validation as validation_layer, series_view
from .results import ResultService

class ValidationService:
    def __init__(self, results: ResultService):
        self.results = results

    def get_revision(self, run_id, revision_id=None):
        return self.results.get_revision(run_id, revision_id)

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
                from .. import risk_v2
                view = risk_v2.input_view(revision)
                reason = view["reason"]
                if reason == "insufficient_observations":
                    reason = None  # validation v2 applies its own >=10 threshold
                configs.append({"run_id": run_id, "revision_id": revision["revision_id"],
                                "title": revision["result"]["run"]["title"],
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
            from .. import validation_v2
            return validation_v2.build_report(configs, horizon=horizon, splits=splits,
                                              embargo=embargo, blocks=blocks, trials=trials)
        return validation_layer.validation_report(configs, horizon=horizon, splits=splits,
                                                  embargo=embargo, trials=trials, blocks=blocks)
