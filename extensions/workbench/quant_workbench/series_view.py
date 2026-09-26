"""Extract the return series a domain needs from one platform revision (third-review C2).

Used by validation and risk so both agree on precedence and on the label they report.
"""

from __future__ import annotations

from typing import Any

NATIVE_RETURN = "native.qlib.return"
NATIVE_LABEL = "native.qlib.return（引擎报告日收益）"
DERIVED_LABEL = "derived: platform.equity 日收益（平台计算）"


def return_series(revision: dict[str, Any]) -> dict[str, Any] | None:
    """Return {dates, values, source} preferring the engine series, else derived equity."""
    series = {item["metric_id"]: item for item in (revision.get("result") or {}).get("series", [])}
    native = series.get(NATIVE_RETURN)
    if native and native.get("availability") == "available":
        points = [(point["x"], point["value"]) for point in native["points"]
                  if point.get("value") is not None]
        if points:
            return {"dates": [point[0] for point in points], "values": [point[1] for point in points],
                    "source": NATIVE_LABEL}
    equity = series.get("platform.equity")
    if equity and equity.get("availability") == "available":
        points = [(point["x"], point["value"]) for point in equity["points"]
                  if point.get("value") is not None]
        values = [(points[index][0], points[index][1] / points[index - 1][1] - 1)
                  for index in range(1, len(points)) if points[index - 1][1]]
        if values:
            return {"dates": [point[0] for point in values], "values": [point[1] for point in values],
                    "source": DERIVED_LABEL}
    return None
