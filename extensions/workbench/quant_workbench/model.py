"""Published result contract for the first read-only workbench slice."""

from __future__ import annotations

import json
import math
import copy
from datetime import date, datetime, timezone
from typing import Any


STATUSES = {"queued", "running", "succeeded", "failed", "cancelled", "interrupted", "unknown"}
AXES = {"time", "trading_date", "step", "scalar"}
AVAILABILITY = {"available", "empty", "not_recorded", "unsupported", "error"}


class ContractError(ValueError):
    """A result violates the workbench's published DTO rules."""


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value


def _instant(value: Any, name: str) -> datetime | None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ContractError(f"{name} must be an ISO timestamp or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{name} must include an offset")
    return parsed.astimezone(timezone.utc)


def validate_package(package: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a JSON-safe, canonical result package.

    Each importer supplies evidence; this validator never fills unknown facts.
    """
    if not isinstance(package, dict) or package.get("schema_version") != 1:
        raise ContractError("schema_version must be 1")
    package = copy.deepcopy(package)
    run = package.get("run")
    if not isinstance(run, dict):
        raise ContractError("run is required")
    _nonempty(run.get("title"), "run.title")
    _nonempty(run.get("kind"), "run.kind")
    if run.get("status") not in STATUSES:
        raise ContractError("invalid run.status")
    _instant(run.get("created_at"), "run.created_at")
    if run.get("created_at") is None:
        raise ContractError("run.created_at is required")
    _instant(run.get("started_at"), "run.started_at")
    _instant(run.get("ended_at"), "run.ended_at")
    if run["status"] == "queued" and (run.get("started_at") or run.get("ended_at")):
        raise ContractError("queued runs cannot have start/end times")
    if run["status"] == "running" and run.get("ended_at"):
        raise ContractError("running runs cannot have ended_at")
    for key in ("created_at", "started_at", "ended_at"):
        if run.get(key) is not None:
            run[key] = _instant(run[key], key).isoformat(timespec="microseconds")
    if run.get("started_at") and run.get("ended_at") and run["started_at"] > run["ended_at"]:
        raise ContractError("end time precedes start time")
    if package.get("evidence", {}).get("fixture") and not run.get("synthetic"):
        raise ContractError("fixture must be synthetic")
    for key in ("engine", "dataset"):
        item = run.get(key)
        if not isinstance(item, dict):
            raise ContractError(f"run.{key} is required")
        _nonempty(item.get("id"), f"run.{key}.id")
        version = item.get("version")
        if version is not None:
            _nonempty(version, f"run.{key}.version")
    if not isinstance(run.get("synthetic"), bool):
        raise ContractError("run.synthetic must be a boolean")
    context = package.get("evidence", {}).get("comparison")
    if context is not None:
        if not isinstance(context, dict):
            raise ContractError("comparison context must be an object")
        for key in ("execution_id", "cashflow_policy", "price_basis", "benchmark_id", "evaluation_id"):
            if context.get(key) is not None:
                _nonempty(context[key], "comparison." + key)
        initial = context.get("initial_equity")
        if initial is not None and (type(initial) not in (int, float) or not math.isfinite(initial) or initial <= 0):
            raise ContractError("initial_equity must be positive finite or null")
    stages = run.get("stages", [])
    if not isinstance(stages, list):
        raise ContractError("run.stages must be a list")
    for stage in stages:
        if not isinstance(stage, dict):
            raise ContractError("stage must be an object")
        _nonempty(stage.get("kind"), "stage.kind")
        if stage.get("status") not in STATUSES:
            raise ContractError("invalid stage.status")

    series = package.get("series", [])
    if not isinstance(series, list):
        raise ContractError("series must be a list")
    seen = set()
    for entry in series:
        if not isinstance(entry, dict):
            raise ContractError("series item must be an object")
        metric_id = _nonempty(entry.get("metric_id"), "series.metric_id")
        if metric_id in seen:
            raise ContractError(f"duplicate metric_id: {metric_id}")
        seen.add(metric_id)
        if entry.get("axis") not in AXES:
            raise ContractError(f"invalid axis for {metric_id}")
        if entry.get("availability") not in AVAILABILITY:
            raise ContractError(f"invalid availability for {metric_id}")
        _nonempty(entry.get("unit"), f"{metric_id}.unit")
        _nonempty(entry.get("definition_id"), f"{metric_id}.definition_id")
        points = entry.get("points")
        if not isinstance(points, list):
            raise ContractError(f"{metric_id}.points must be a list")
        if entry["availability"] == "available" and not points:
            raise ContractError(f"{metric_id} is available but has no points")
        if entry["availability"] != "available" and points:
            raise ContractError(f"{metric_id} is unavailable but has points")
        axis = entry["axis"]
        if axis == "step":
            _nonempty(entry.get("step_kind"), f"{metric_id}.step_kind")
        if axis == "trading_date":
            _nonempty(entry.get("calendar_id"), f"{metric_id}.calendar_id")
        last_x = None
        for point in points:
            if not isinstance(point, dict):
                raise ContractError(f"{metric_id} point must be an object")
            x = point.get("x")
            axis = entry["axis"]
            if axis == "scalar":
                if x is not None:
                    raise ContractError(f"{metric_id} scalar x must be null")
            elif axis == "step":
                if not isinstance(x, int) or isinstance(x, bool) or x < 0:
                    raise ContractError(f"{metric_id} step x must be a nonnegative integer")
                _nonempty(entry.get("step_kind"), f"{metric_id}.step_kind")
            elif axis == "trading_date":
                if not isinstance(x, str):
                    raise ContractError(f"{metric_id} trading date must be a string")
                try:
                    if date.fromisoformat(x).isoformat() != x:
                        raise ValueError(x)
                except ValueError as exc:
                    raise ContractError(f"{metric_id} invalid trading date") from exc
                _nonempty(entry.get("calendar_id"), f"{metric_id}.calendar_id")
            else:
                _instant(x, f"{metric_id} point x")
                if x is None:
                    raise ContractError(f"{metric_id} time x is required")
            if axis == "time":
                x = _instant(x, metric_id).isoformat(timespec="microseconds")
                point["x"] = x
            if last_x is not None and x <= last_x:
                raise ContractError(f"{metric_id} points must be strictly ordered")
            last_x = x
            value = point.get("value")
            if value is None:
                _nonempty(point.get("reason"), f"{metric_id} missing reason")
            elif isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ContractError(f"{metric_id} values must be finite numbers or null")
        if axis == "scalar" and len(points) > 1:
            raise ContractError(f"{metric_id} scalar may have one point")
    try:
        # allow_nan=False catches nested nonfinite values outside `series` too.
        return json.loads(json.dumps(package, allow_nan=False, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError) as exc:
        raise ContractError("package must contain JSON-safe values") from exc
