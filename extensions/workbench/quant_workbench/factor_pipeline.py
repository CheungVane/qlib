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


def load_symbol_series(reader: FreeSnapshotReader, symbol: str, dates: Sequence[date],
                       enrichment: dict[str, dict]) -> dict[str, list[float]]:
    """All archive fields a factor slice needs, aligned to `dates` (+ turnover from cache)."""
    fields = ("close", "high", "low", "change", "volume", "factor")
    series = {field: aligned_series(reader, symbol, field, dates) for field in fields}
    series["turn"] = [enrichment.get(day.isoformat(), {}).get("turn") or float("nan")
                      for day in dates]
    return series


def walk_forward_windows(length: int, *, folds: int = 4,
                         min_train: int = 120) -> list[tuple[slice, slice]]:
    """Expanding-window walk-forward splits: (train, test) index slices.

    The test slice always follows its train slice, so a fold can only use information
    available before the period it is evaluated on.
    """
    if folds < 1:
        raise DataDirectoryError("folds must be >= 1")
    if length <= min_train:
        return []
    block = (length - min_train) // folds
    if block < 5:
        return []
    windows = []
    for index in range(folds):
        start = min_train + index * block
        stop = length if index == folds - 1 else start + block
        windows.append((slice(0, start), slice(start, stop)))
    return windows


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


def label_tradability(flags: Sequence[bool], horizon: int = DEFAULT_HORIZON) -> list[bool]:
    """Buy-side at t **and** sell-side at t+h must both be tradable."""
    total = len(flags)
    return [bool(flags[index] and index + horizon < total and flags[index + horizon])
            for index in range(total)]


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


# -- size and industry exposures --------------------------------------------
def float_shares_from_series(volumes: Sequence[float], factors: Sequence[float],
                             turns: Sequence[float]) -> list[float]:
    """Daily float shares; delegates to the verified free_sources formula."""
    result = []
    for volume, factor, turn in zip(volumes, factors, turns):
        if not all(math.isfinite(item) for item in (volume, factor, turn)) or turn <= 0 or factor <= 0:
            result.append(float("nan"))
            continue
        result.append(free_sources.float_shares_from_archive(volume, factor, turn))
    return result


def log_float_cap(closes: Sequence[float], factors: Sequence[float],
                  volumes: Sequence[float], turns: Sequence[float]) -> list[float]:
    """ln(raw close x float shares); raw close = adjusted close / factor."""
    shares = float_shares_from_series(volumes, factors, turns)
    result = []
    for close, factor, share in zip(closes, factors, shares):
        if not all(math.isfinite(item) for item in (close, factor, share)) or factor <= 0 or share <= 0:
            result.append(float("nan"))
            continue
        result.append(math.log((close / factor) * share))
    return result


def rolling_industry(returns_by_symbol: dict[str, Sequence[float]], dates: Sequence[date],
                     *, window: int = 120, n_clusters: int = 8, step: int = 21) -> dict[str, dict[str, int]]:
    """Cluster trailing return windows on a fixed grid: labels use past data only (PIT)."""
    from .free_sources import statistical_industry

    result: dict[str, dict[str, int]] = {}
    for index in range(len(dates)):
        if index < window or index % step:
            continue
        trailing = {symbol: list(values[index - window + 1:index + 1])
                    for symbol, values in returns_by_symbol.items()}
        usable = {symbol: values for symbol, values in trailing.items()
                  if len(values) == window and all(math.isfinite(value) for value in values)
                  and len(set(values)) > 1}
        if len(usable) < n_clusters * 2:
            continue
        result[dates[index].isoformat()] = statistical_industry(usable, n_clusters=n_clusters)
    return result


def rolling_beta(returns_by_symbol: dict[str, Sequence[float]], market_returns: Sequence[float],
                 *, window: int = 120, step: int = 21) -> dict[int, dict[str, float]]:
    """Trailing market beta on a fixed grid; uses only past returns (PIT)."""
    result: dict[int, dict[str, float]] = {}
    length = len(market_returns)
    for index in range(length):
        if index < window or index % step:
            continue
        market = market_returns[index - window:index]
        if len(market) != window or any(not math.isfinite(value) for value in market):
            continue
        market_mean = statistics.fmean(market)
        variance = sum((value - market_mean) ** 2 for value in market)
        if variance <= 0:
            continue
        row = {}
        for symbol, values in returns_by_symbol.items():
            series = list(values[index - window:index])
            if len(series) != window or any(not math.isfinite(value) for value in series):
                continue
            series_mean = statistics.fmean(series)
            covariance = sum((a - series_mean) * (b - market_mean)
                             for a, b in zip(series, market))
            row[symbol] = covariance / variance
        if row:
            result[index] = row
    return result


def neutralize(factor: dict[str, float], exposures: Sequence[dict[str, float]],
               industry: dict[str, int] | None = None) -> dict[str, float]:
    """Residualise the factor on cross-sectional exposures (e.g. size, beta) + industry."""
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover
        raise DataDirectoryError("neutralize needs numpy (install the 'analysis' extra)") from error

    exposures = list(exposures) or [{}]
    symbols = [symbol for symbol in sorted(factor)
               if math.isfinite(factor.get(symbol, float("nan")))
               and all(math.isfinite(item.get(symbol, float("nan"))) for item in exposures)]
    if len(symbols) < 20:
        return {}
    industry = industry or {}
    columns = [np.ones(len(symbols))]
    for item in exposures:
        columns.append(np.array([item[symbol] for symbol in symbols], dtype=float))
    categories = sorted({industry[symbol] for symbol in symbols if symbol in industry})
    for category in categories[1:]:
        columns.append(np.array([1.0 if industry.get(symbol) == category else 0.0
                                 for symbol in symbols]))
    matrix = np.column_stack(columns)
    target = np.array([factor[symbol] for symbol in symbols], dtype=float)
    coefficients, *_ = np.linalg.lstsq(matrix, target, rcond=None)
    residual = target - matrix @ coefficients
    return {symbol: float(value) for symbol, value in zip(symbols, residual)}


def stability(series: Sequence[float], folds: int = 6) -> dict:
    """Consecutive-fold IC stability: sign consistency and dispersion of fold means."""
    values = [value for value in series if math.isfinite(value)]
    if len(values) < folds * 5:
        return {"state": "insufficient", "folds": 0}
    size = len(values) // folds
    means = [statistics.fmean(values[index * size:(index + 1) * size]) for index in range(folds)]
    overall = statistics.fmean(values)
    signs = [1 if value > 0 else -1 for value in means]
    dominant = 1 if overall > 0 else -1
    return {"state": "available", "folds": folds,
            "fold_means": means,
            "same_sign_share": sum(1 for sign in signs if sign == dominant) / folds,
            "dispersion": (statistics.stdev(means) / abs(overall)) if len(means) > 1 and overall else None}


def cost_threshold(gross_spread: float, daily_rank_turnover: float, horizon: int,
                   round_trip_cost: float) -> dict:
    """Screening test: can the gross quantile spread cover the round-trip cost?

    Expected turnover over one holding period is capped at 2 (full replacement twice);
    this is a screening calculation, not a backtest.
    """
    expected_cost = min(2.0, horizon * daily_rank_turnover) * round_trip_cost
    net = gross_spread - expected_cost
    return {"gross_spread": gross_spread, "expected_cost": expected_cost, "net": net,
            "passes": net > 0, "round_trip_cost": round_trip_cost,
            "assumed_turnover": min(2.0, horizon * daily_rank_turnover)}


def rank_turnover(previous: dict[str, float], current: dict[str, float]) -> float | None:
    """Mean absolute change of cross-sectional percentile rank between two days."""
    before = cross_sectional_rank(previous)
    after = cross_sectional_rank(current)
    shared = sorted(before.keys() & after.keys())
    if len(shared) < 3:
        return None
    return statistics.fmean(abs(after[symbol] - before[symbol]) for symbol in shared)


def quantile_spread(factor: dict[str, float], label: dict[str, float],
                    groups: int = 5) -> dict | None:
    """Mean label per factor quantile plus the Q_top-Q_bottom spread."""
    shared = sorted((symbol for symbol in factor.keys() & label.keys()
                     if math.isfinite(factor[symbol]) and math.isfinite(label[symbol])),
                    key=lambda symbol: factor[symbol])
    if len(shared) < groups * 3:
        return None
    buckets: list[list[float]] = [[] for _ in range(groups)]
    for position, symbol in enumerate(shared):
        bucket = min(groups - 1, position * groups // len(shared))
        buckets[bucket].append(label[symbol])
    means = [statistics.fmean(bucket) if bucket else float("nan") for bucket in buckets]
    if any(not math.isfinite(value) for value in means):
        return None
    return {"group_means": means, "spread_top_bottom": means[-1] - means[0],
            "symbols": len(shared)}


# -- inference ---------------------------------------------------------------
def newey_west_t(values: Sequence[float], lags: int) -> float | None:
    """NW(Bartlett) t-statistic of the mean; same convention as FACTOR_ANALYSIS §4.1."""
    series = [value for value in values if math.isfinite(value)]
    count = len(series)
    if count < max(10, lags + 2):
        return None
    average = statistics.fmean(series)
    centred = [value - average for value in series]
    gamma0 = sum(value * value for value in centred) / count
    omega = gamma0
    for lag in range(1, lags + 1):
        covariance = sum(centred[index] * centred[index - lag]
                         for index in range(lag, count)) / count
        omega += 2 * (1 - lag / (lags + 1)) * covariance
    if omega <= 0:
        return None
    return average / math.sqrt(omega / count)


def benjamini_hochberg(p_values: dict[str, float]) -> dict[str, float]:
    """BH-FDR q-values over the tested hypotheses (family = the given mapping)."""
    items = [(key, value) for key, value in p_values.items() if math.isfinite(value)]
    total = len(items)
    if not total:
        return {}
    ordered = sorted(items, key=lambda item: item[1])
    q_values, running = {}, 1.0
    for rank in range(total, 0, -1):
        key, value = ordered[rank - 1]
        running = min(running, value * total / rank)
        q_values[key] = min(1.0, running)
    return q_values


def normal_two_sided_p(t_stat: float | None) -> float | None:
    if t_stat is None or not math.isfinite(t_stat):
        return None
    return math.erfc(abs(t_stat) / math.sqrt(2))


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
