"""Engine-neutral calculations on a complete immutable result revision."""
from .model import _instant
from .numeric import RANK_TOLERANCE


# Declared comparison rows: metric id, label, aggregation over the series and the direction of
# "better". Direction stays `unknown` unless it is an explicit decision here (UI06).
COMPARE_ROWS = (
    {"metric_id": "platform.equity", "label": "期末权益", "aggregation": "last",
     "direction": "higher_better"},
    {"metric_id": "platform.equity", "label": "首末观测权益变化", "aggregation": "change",
     "direction": "higher_better", "unit": "ratio"},
    {"metric_id": "platform.drawdown", "label": "最大观测回撤", "aggregation": "minimum",
     "direction": "higher_better", "unit": "ratio"},
    {"metric_id": "native.qlib.total_cost", "label": "累计成本", "aggregation": "last",
     "direction": "lower_better"},
    {"metric_id": "native.qlib.turnover", "label": "换手率（末值）", "aggregation": "last",
     "direction": "unknown"},
)
EXTRA_ROW_LIMIT = 6
DIRECTIONS = {"higher_better": "越高越好", "lower_better": "越低越好", "unknown": "方向未登记"}

# Comparison groups (FACTOR_ANALYSIS §2): only backtest rows may be ranked; training and
# research rows exist in different groups whose metric sets are not interchangeable.
BACKTEST_METRICS = {
    "platform.equity", "platform.drawdown", "native.qlib.total_cost", "native.qlib.total_turnover",
    "native.qlib.turnover", "native.qlib.return", "native.qlib.bench", "native.qlib.cost",
}
GROUP_LABELS = {"training": "训练", "research": "研究", "backtest": "回测", "other": "其他/未登记"}
RANKABLE_GROUPS = ("backtest",)


def metric_group(metric_id: str) -> str:
    if metric_id in BACKTEST_METRICS:
        return "backtest"
    lowered = str(metric_id).lower()
    if lowered.startswith("native.rdagent.") or lowered.startswith("platform.factor"):
        return "research"
    # Only ever downgrades to a non-rankable group; anything unknown stays "other".
    if (".l2." in lowered or "loss" in lowered or lowered.endswith((".train", ".valid"))
            or ".train." in lowered or ".valid." in lowered):
        return "training"
    return "other"


def row_value(entry, aggregation, summary=None):
    """Scalar used by one comparison-table cell; None means "no number", never 0."""
    summary = summary or summarize(entry)
    points = [p for p in (entry or {}).get("points", []) if p.get("value") is not None]
    if aggregation == "last":
        return summary.get("last")
    if aggregation == "change":
        first, last = summary.get("first"), summary.get("last")
        if isinstance(first, (int, float)) and isinstance(last, (int, float)) and first:
            return (last - first) / first
        return None
    if aggregation == "minimum":
        return min(p["value"] for p in points) if points else None
    raise ValueError(f"unknown comparison aggregation: {aggregation}")


def rank(values, direction, tolerance=RANK_TOLERANCE):
    """Mark best/worst per cell; ties share the mark and unknown direction never marks."""
    result = {"marks": [None] * len(values), "tied_best": False, "tied_worst": False,
              "within_tolerance": False}
    if direction not in ("higher_better", "lower_better") or not values or any(v is None for v in values):
        return result

    def same(left, right):
        return abs(left - right) <= tolerance * max(abs(left), abs(right), 1e-12)

    best = max(values) if direction == "higher_better" else min(values)
    worst = min(values) if direction == "higher_better" else max(values)
    best_idx = [i for i, value in enumerate(values) if same(value, best)]
    if len(best_idx) == len(values):
        result["within_tolerance"] = True
        return result
    worst_idx = [i for i, value in enumerate(values) if same(value, worst)]
    for index in best_idx:
        result["marks"][index] = "best"
    for index in worst_idx:
        result["marks"][index] = "worst"
    result["tied_best"] = len(best_idx) > 1
    result["tied_worst"] = len(worst_idx) > 1
    return result


def coordinate(entry, point):
    return _instant(point['x'], 'point.x').isoformat() if entry['axis'] == 'time' else point['x']


def summarize(entry):
    points = entry.get('points', []) if entry else []
    valid = [p for p in points if p['value'] is not None]
    first, last = (points[0], points[-1]) if points else ({}, {})
    missing = len(points) - len(valid)
    reason = (entry or {}).get('availability', 'not_recorded')
    return {'point_count':len(points), 'valid_points':len(valid), 'missing_points':missing,
            'start':first.get('x'), 'end':last.get('x'),
            'first':first.get('value'), 'last':last.get('value'),
            'first_reason':first.get('reason', reason if not points else None),
            'last_reason':last.get('reason', reason if not points else None),
            'minimum':min(p['value'] for p in valid) if valid and not missing else None,
            'last_valid':valid[-1] if valid else None,
            'complete':bool(points) and not missing}


def equity_drawdown(points, initial=None):
    if not points or any(p['value'] is None or p['value'] <= 0 for p in points):
        return None
    high = initial if initial is not None else points[0]['value']
    if high <= 0:
        return None
    result = []
    for p in points:
        high = max(high, p['value'])
        result.append(p['value'] / high - 1)
    return min(result)
