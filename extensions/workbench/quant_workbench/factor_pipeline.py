"""Feature and label pipeline over a registered free-source snapshot.

Contract: docs/spec/FACTOR_ANALYSIS.md §3.3 (labels from the snapshot calendar) and the
tradability rules in DATA_SOURCES.md §1A. Everything is derived from
`free_community_unverified` inputs: keep that label and never treat the output as certified.

Key rules implemented here:

* labels use trading-day steps on the snapshot calendar, never row offsets after gaps;
* suspended names and one-word limit boards are excluded from the tradable sample;
* missing values stay missing (NaN) instead of being filled;
* cross-sectional ranks and Rank IC are computed per trading day.
"""

from __future__ import annotations

import math
import statistics
from datetime import date
from typing import Sequence

from . import free_sources
from .data_directory import DataDirectoryError, FreeSnapshotReader

DEFAULT_HORIZON = 5
NORMAL_LIMIT = 0.098
ST_LIMIT = 0.048


def aligned_series(reader: FreeSnapshotReader, symbol: str, field: str,
                   dates: Sequence[date]) -> list[float]:
    """Values aligned to `dates`; NaN outside the instrument's recorded coverage."""
    if field not in free_sources.ARCHIVE_FIELDS:
        raise DataDirectoryError(f"unknown feature field: {field}")
    path = reader.path("bar") / symbol.lower() / f"{field}.day.bin"
    try:
        head = free_sources.read_bin_head_tail(path)
        values = free_sources.read_bin_values(path)
    except (free_sources.FreeSourceError, OSError):
        return [float("nan")] * len(dates)
    positions = {day: index for index, day in enumerate(reader.calendar())}
    result = []
    for day in dates:
        position = positions.get(day)
        offset = None if position is None else position - head["start_index"]
        result.append(values[offset] if offset is not None and 0 <= offset < len(values)
                      else float("nan"))
    return result


def forward_return(closes: Sequence[float], horizon: int = DEFAULT_HORIZON) -> list[float]:
    """Label r[t->t+h] on calendar steps; the last h rows stay NaN (no future data)."""
    if horizon < 1:
        raise DataDirectoryError("horizon must be >= 1")
    labels = [float("nan")] * len(closes)
    for index in range(len(closes) - horizon):
        start, end = closes[index], closes[index + horizon]
        if math.isfinite(start) and math.isfinite(end) and start > 0:
            labels[index] = end / start - 1.0
    return labels


def tradable(values: dict[str, Sequence[float]], dates: Sequence[date],
             enrichment: dict[str, dict], *, exclude_st: bool = True) -> list[bool]:
    """Suspended days and one-word limit boards are not tradable (T+1 approximation)."""
    flags = []
    for index, day in enumerate(dates):
        status = enrichment.get(day.isoformat())
        if status is None or status.get("tradestatus") != 1:
            flags.append(False)
            continue
        if exclude_st and status.get("isST") == 1:
            flags.append(False)
            continue
        high, low = values["high"][index], values["low"][index]
        change = values["change"][index]
        if not all(math.isfinite(item) for item in (high, low, change)):
            flags.append(False)
            continue
        limit = ST_LIMIT if status.get("isST") == 1 else NORMAL_LIMIT
        flat = abs(high - low) <= 1e-5 * max(abs(high), 1.0)
        if flat and abs(change) >= limit:  # `change` is a decimal fraction in the archive
            flags.append(False)  # one-word board: cannot get filled
            continue
        flags.append(True)
    return flags


def momentum(closes: Sequence[float], window: int) -> list[float]:
    return [closes[index] / closes[index - window] - 1.0
            if index >= window and math.isfinite(closes[index]) and math.isfinite(closes[index - window])
            and closes[index - window] > 0 else float("nan")
            for index in range(len(closes))]


def volatility(closes: Sequence[float], window: int) -> list[float]:
    result = [float("nan")] * len(closes)
    for index in range(window, len(closes)):
        window_closes = closes[index - window:index + 1]
        if any(not math.isfinite(value) or value <= 0 for value in window_closes):
            continue
        returns = [window_closes[step] / window_closes[step - 1] - 1.0
                   for step in range(1, len(window_closes))]
        if len(returns) >= 2:
            result[index] = statistics.stdev(returns)
    return result


def mean_of(values: Sequence[float], window: int) -> list[float]:
    result = [float("nan")] * len(values)
    for index in range(window - 1, len(values)):
        chunk = [value for value in values[index - window + 1:index + 1] if math.isfinite(value)]
        if len(chunk) == window:
            result[index] = sum(chunk) / window
    return result


def cross_sectional_rank(values: dict[str, float]) -> dict[str, float]:
    """Average-tie percentile rank in [0, 1] over the symbols present that day."""
    usable = {key: value for key, value in values.items() if math.isfinite(value)}
    if not usable:
        return {}
    ordered = sorted(usable.items(), key=lambda item: item[1])
    ranks: dict[str, float] = {}
    position = 0
    while position < len(ordered):
        end = position
        while end + 1 < len(ordered) and ordered[end + 1][1] == ordered[position][1]:
            end += 1
        average = (position + end) / 2.0 / max(len(ordered) - 1, 1)
        for offset in range(position, end + 1):
            ranks[ordered[offset][0]] = average
        position = end + 1
    return ranks


def rank_ic(factors: dict[str, float], labels: dict[str, float]) -> float | None:
    """Spearman IC for one day; needs at least 3 overlapping symbols."""
    shared = {key: (factors[key], labels[key]) for key in factors.keys() & labels.keys()
              if math.isfinite(factors[key]) and math.isfinite(labels[key])}
    if len(shared) < 3:
        return None
    factor_rank = cross_sectional_rank({key: value[0] for key, value in shared.items()})
    label_rank = cross_sectional_rank({key: value[1] for key, value in shared.items()})
    keys = sorted(factor_rank)
    left = [factor_rank[key] for key in keys]
    right = [label_rank[key] for key in keys]
    left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - left_mean) ** 2 for a in left)
                            * sum((b - right_mean) ** 2 for b in right))
    if denominator == 0:
        return None
    return numerator / denominator
