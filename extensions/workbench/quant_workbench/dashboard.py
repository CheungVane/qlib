"""Typed dashboard manifest validation; arbitrary query expressions are forbidden."""

from __future__ import annotations

from typing import Any

from .model import ContractError


QUERY_IDS = {"runs.latest", "runs.success_rate.24h", "data.freshness", "api.error_rate.5m",
             "events.active", "backtest.equity", "training.metrics", "live.connection"}
WIDGETS = {"metric", "line", "table", "status", "log"}


def validate_dashboard(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ContractError("dashboard schema_version must be 1")
    if not isinstance(manifest.get("dashboard_id"), str) or not manifest["dashboard_id"]:
        raise ContractError("dashboard_id is required")
    widgets = manifest.get("widgets")
    if not isinstance(widgets, list) or len(widgets) > 50:
        raise ContractError("widgets must be a list of at most 50")
    seen = set()
    for widget in widgets:
        if not isinstance(widget, dict) or not isinstance(widget.get("id"), str) or not widget["id"]:
            raise ContractError("widget id is required")
        if widget["id"] in seen:
            raise ContractError(f"duplicate widget id: {widget['id']}")
        seen.add(widget["id"])
        if widget.get("kind") not in WIDGETS:
            raise ContractError("invalid widget kind")
        query = widget.get("query")
        if not isinstance(query, dict) or query.get("id") not in QUERY_IDS:
            raise ContractError("widget query must use a registered ID")
        if query.get("params", {}) != {}:
            raise ContractError("this manifest version does not accept query params")
        layout = widget.get("layout")
        if not isinstance(layout, dict):
            raise ContractError("widget layout is required")
        if any(isinstance(layout.get(k), bool) or not isinstance(layout.get(k), int) for k in ("x", "y", "w", "h")):
            raise ContractError("layout coordinates must be integers")
        if layout["x"] < 0 or layout["y"] < 0 or layout["w"] < 1 or layout["h"] < 1 or layout["x"] + layout["w"] > 12:
            raise ContractError("widget layout exceeds 12-column grid")
        refresh = widget.get("refresh_seconds", 0)
        if isinstance(refresh, bool) or not isinstance(refresh, int) or not 0 <= refresh <= 3600:
            raise ContractError("refresh_seconds must be 0 to 3600")
    return manifest
