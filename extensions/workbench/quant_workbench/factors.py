"""Factor layer: canonical panels, forward returns from recorded snapshots, statistics.

Contract: docs/spec/FACTOR_ANALYSIS.md. Everything here is platform-computed (工作台计算):
results must carry the formula, the sample basis and the data content version.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from . import numeric
from .dto import json_safe

PANEL_LIMITS = {"dates": 2000, "instruments": 2000, "cells": 400_000, "bytes": 16 * 1024 * 1024}
DEFAULT_HORIZONS = (1, 5, 10, 20)
MIN_CROSS_SECTION = 5
MAX_FACTORS_PER_ANALYSIS = 20


class FactorError(ValueError):
    """Invalid factor input; the API maps this to 400 with the reason preserved."""


def utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_panel(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise one factor panel; missing stays null, never 0."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise FactorError("panel schema_version must be 1")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise FactorError("panel name is required")
    dates, instruments, values = payload.get("dates"), payload.get("instruments"), payload.get("values")
    if not isinstance(dates, list) or not isinstance(instruments, list) or not isinstance(values, list):
        raise FactorError("panel needs dates[], instruments[] and values[]")
    if not dates or not instruments:
        raise FactorError("panel must not be empty")
    if len(dates) > PANEL_LIMITS["dates"] or len(instruments) > PANEL_LIMITS["instruments"]:
        raise FactorError("panel exceeds the date/instrument bound")
    if len(set(dates)) != len(dates) or dates != sorted(dates):
        raise FactorError("panel dates must be unique and sorted")
    if len(set(instruments)) != len(instruments):
        raise FactorError("panel instruments must be unique")
    expected = len(dates) * len(instruments)
    if expected > PANEL_LIMITS["cells"]:
        raise FactorError("panel exceeds the cell bound")
    if len(values) != expected:
        raise FactorError(f"panel values must have {expected} cells (date-major)")
    clean: list[float | None] = []
    valid = 0
    for cell in values:
        if cell is None:
            clean.append(None)
            continue
        if isinstance(cell, bool) or not isinstance(cell, (int, float)) or not math.isfinite(cell):
            raise FactorError("panel values must be finite numbers or null")
        clean.append(float(cell))
        valid += 1
    numbers = [cell for cell in clean if cell is not None]
    panel = {
        "schema_version": 1,
        "name": name.strip(),
        "calendar_id": payload.get("calendar_id"),
        "dates": list(dates),
        "instruments": list(instruments),
        "values": clean,
        "date_count": len(dates),
        "instrument_count": len(instruments),
        "cell_count": expected,
        "valid_count": valid,
        "coverage": (valid / expected) if expected else None,
        "value_stats": ({"min": min(numbers), "max": max(numbers), "mean": sum(numbers) / len(numbers)}
                        if numbers else None),
        "source_ref": payload.get("source_ref"),
        "notes": list(payload.get("notes") or []),
    }
    if len(json.dumps(panel, ensure_ascii=False, allow_nan=False).encode()) > PANEL_LIMITS["bytes"]:
        raise FactorError("panel exceeds the byte bound")
    return panel


def panel_matrix(panel: dict[str, Any]):
    """Dense numpy matrix (dates × instruments) with NaN for missing cells."""
    np = _numpy()
    rows, columns = panel["date_count"], panel["instrument_count"]
    grid = np.full((rows, columns), np.nan, dtype=float)
    for index, cell in enumerate(panel["values"]):
        if cell is not None:
            grid[index // columns][index % columns] = cell
    return grid


def load_close_series(snapshot: Path, dates: list[str], instruments: list[str]) -> dict[str, Any]:
    """Read adjusted close from a recorded local snapshot (declared bin layout)."""
    np = _numpy()
    day_file = snapshot / "calendars/day.txt"
    if not day_file.is_file():
        raise FactorError(f"snapshot has no calendar: {snapshot.name}")
    calendar = day_file.read_text(encoding="utf-8").split()
    index = {day: position for position, day in enumerate(calendar)}
    grid = np.full((len(dates), len(instruments)), np.nan, dtype=float)
    missing = []
    for column, code in enumerate(instruments):
        folder = snapshot / "features" / code.lower()
        close_file, factor_file = folder / "close.day.bin", folder / "factor.day.bin"
        if not close_file.is_file():
            missing.append(code)
            continue
        close = np.fromfile(close_file, dtype="<f4")
        start = int(close[0])
        close = close[1:]
        factor = None
        if factor_file.is_file():
            raw = np.fromfile(factor_file, dtype="<f4")
            factor = raw[1:]
        for row, day in enumerate(dates):
            position = index.get(day)
            if position is None:
                continue
            offset = position - start
            if 0 <= offset < len(close):
                value = float(close[offset])
                if factor is not None and offset < len(factor):
                    value *= float(factor[offset])
                grid[row][column] = value
    return {"values": grid, "missing_instruments": missing,
            "fields": "close*factor" if (snapshot / "features").exists() else "close"}


def forward_returns(prices, horizon: int):
    """r_{t→t+h} = close_{t+h}/close_t - 1 over the same grid."""
    np = _numpy()
    if horizon < 1:
        raise FactorError("horizon must be >= 1")
    rows, columns = prices.shape
    out = np.full((rows, columns), np.nan, dtype=float)
    for row in range(rows - horizon):
        base, future = prices[row], prices[row + horizon]
        with np.errstate(invalid="ignore", divide="ignore"):
            out[row] = np.where((base > 0) & np.isfinite(base) & np.isfinite(future),
                                future / base - 1.0, np.nan)
    return out


def verify_snapshot(snapshot: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless the local snapshot content matches the recorded version."""
    from .cn_market import snapshot_content_digest
    if not snapshot.is_dir():
        raise FactorError(f"snapshot directory not found: {snapshot.name}")
    digest = snapshot_content_digest(snapshot)
    recorded = (dataset or {}).get("version")
    if not recorded or digest["digest"] != recorded:
        raise FactorError("snapshot content does not match the recorded dataset version")
    return digest


def _numpy():
    return numeric.numpy(FactorError, "factor analysis needs numpy (install the 'analysis' extra)")


# -- statistics ---------------------------------------------------------------
def _rankdata(values):
    """Average ranks with ties, matching scipy.stats.rankdata."""
    np = _numpy()
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    ranks[order] = np.arange(1, len(values) + 1)
    index = 0
    while index < len(values):
        end = index
        while end + 1 < len(values) and values[order[end + 1]] == values[order[index]]:
            end += 1
        if end > index:
            ranks[order[index:end + 1]] = ranks[order[index:end + 1]].mean()
        index = end + 1
    return ranks


def _pearson(left, right):
    np = _numpy()
    left, right = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    if len(left) < 2:
        return None
    left_std, right_std = left.std(), right.std()
    if left_std == 0 or right_std == 0:
        return None
    return float(((left - left.mean()) * (right - right.mean())).mean() / (left_std * right_std))


def _newey_west_se(values, lag):
    np = _numpy()
    values = np.asarray(values, dtype=float)
    count = len(values)
    if count < 2:
        return None
    demeaned = values - values.mean()
    total = float((demeaned ** 2).mean())
    for offset in range(1, min(lag, count - 1) + 1):
        weight = 1 - offset / (lag + 1)
        total += 2 * weight * float((demeaned[offset:] * demeaned[:-offset]).mean())
    total = max(total, 1e-18)
    return math.sqrt(total / count)


def _two_sided_p(t_value):
    return math.erfc(abs(t_value) / math.sqrt(2))


def bh_fdr(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg q values; the caller must disclose the number of tests."""
    count = len(p_values)
    if not count:
        return []
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 1.0
    for position in range(count - 1, -1, -1):
        index = order[position]
        running = min(running, p_values[index] * count / (position + 1))
        adjusted[index] = max(0.0, min(1.0, running))
    return adjusted


def ic_series(factor_grid, returns_grid, dates: list[str], method: str = "spearman") -> list[dict[str, Any]]:
    np = _numpy()
    rows = int(min(len(dates), factor_grid.shape[0], returns_grid.shape[0]))
    series = []
    for row in range(rows):
        factor, forward = factor_grid[row], returns_grid[row]
        mask = np.isfinite(factor) & np.isfinite(forward)
        if int(mask.sum()) < MIN_CROSS_SECTION:
            continue
        values, target = factor[mask], forward[mask]
        if np.unique(values).size < 2 or np.unique(target).size < 2:
            continue
        if method == "spearman":
            ic = _pearson(_rankdata(values), _rankdata(target))
        elif method == "pearson":
            ic = _pearson(values, target)
        else:
            raise FactorError(f"unknown IC method: {method}")
        if ic is None or not math.isfinite(ic):
            continue
        series.append({"date": dates[row], "ic": ic, "n": int(mask.sum())})
    return series


def _series_stats(series: list[dict[str, Any]], horizon: int, factor_count: int) -> dict[str, Any]:
    np = _numpy()
    values = np.asarray([row["ic"] for row in series], dtype=float)
    if len(values) < 2:
        return {"horizon": horizon, "days": len(values), "available": False,
                "reason": "not_enough_observations"}
    mean, std = float(values.mean()), float(values.std(ddof=1))
    lag = max(0, horizon - 1)
    se = _newey_west_se(values, lag)
    t_value = (mean / se) if se else None
    p_value = _two_sided_p(t_value) if t_value is not None else None
    return {
        "horizon": horizon, "days": int(len(values)), "available": True,
        "ic_mean": mean, "ic_std": std, "icir": (mean / std) if std else None,
        "nw_lag": lag, "nw_se": se, "t_stat": t_value, "p_value": p_value,
        "positive_ratio": float((values > 0).mean()),
        "tests_disclosed": factor_count,
    }


def quantile_spread(factor_grid, returns_grid, dates: list[str], groups: int = 5) -> dict[str, Any]:
    np = _numpy()
    rows = int(min(len(dates), factor_grid.shape[0], returns_grid.shape[0]))
    buckets: list[list[float]] = []
    for row in range(rows):
        factor, forward = factor_grid[row], returns_grid[row]
        mask = np.isfinite(factor) & np.isfinite(forward)
        if int(mask.sum()) < groups * 2:
            continue
        values, target = factor[mask], forward[mask]
        if np.unique(values).size < groups:
            continue
        ranks = _rankdata(values)
        index = np.minimum(((ranks - 1) * groups / len(values)).astype(int), groups - 1)
        buckets.append([float(target[index == group].mean()) if (index == group).any() else float("nan")
                        for group in range(groups)])
    if not buckets:
        return {"available": False, "reason": "not_enough_observations"}
    means = np.nanmean(np.asarray(buckets), axis=0)
    spread = float(means[-1] - means[0])
    monotonic = _pearson(np.arange(groups, dtype=float), means)
    return {"available": True, "groups": groups, "group_means": [float(x) for x in means],
            "top_minus_bottom": spread, "monotonicity": monotonic,
            "monotonic": bool(monotonic is not None and abs(monotonic) > 0.8 and
                              (spread > 0) == (monotonic > 0)),
            "days": len(buckets)}


def rank_turnover(factor_grid) -> dict[str, Any]:
    np = _numpy()
    stabilities = []
    previous = previous_mask = None
    for row in range(factor_grid.shape[0]):
        current = factor_grid[row]
        mask = np.isfinite(current)
        if int(mask.sum()) < MIN_CROSS_SECTION:
            continue
        if previous is not None:
            common = mask & previous_mask
            if int(common.sum()) >= MIN_CROSS_SECTION:
                left, right = current[common], previous[common]
                if np.unique(left).size > 1 and np.unique(right).size > 1:
                    rho = _pearson(_rankdata(left), _rankdata(right))
                    if rho is not None:
                        stabilities.append(rho)
        previous, previous_mask = current, mask
    if not stabilities:
        return {"available": False, "reason": "not_enough_observations"}
    stability = float(np.mean(stabilities))
    return {"available": True, "rank_stability": stability, "turnover": max(0.0, 1.0 - stability),
            "pairs": len(stabilities)}


def aligned_rows(panels: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Common dates and instruments across panels (order preserved from the first panel)."""
    date_sets = [set(panel["dates"]) for panel in panels]
    instrument_sets = [set(panel["instruments"]) for panel in panels]
    dates = [day for day in panels[0]["dates"] if all(day in group for group in date_sets)]
    instruments = [code for code in panels[0]["instruments"] if all(code in group for group in instrument_sets)]
    return dates, instruments


def _panel_lookup(panel: dict[str, Any]) -> dict[tuple[str, str], float]:
    columns = panel["instrument_count"]
    lookup = {}
    for index, cell in enumerate(panel["values"]):
        if cell is None:
            continue
        lookup[(panel["dates"][index // columns], panel["instruments"][index % columns])] = cell
    return lookup


def pairwise_value_correlation(panels: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean cross-sectional Spearman correlation between every pair of factors."""
    np = _numpy()
    lookups = [_panel_lookup(panel) for panel in panels]
    names = [panel["name"] for panel in panels]
    size = len(panels)
    matrix = [[None] * size for _ in range(size)]
    for row in range(size):
        matrix[row][row] = 1.0
        for column in range(row + 1, size):
            dates, instruments = aligned_rows([panels[row], panels[column]])
            per_day = []
            for day in dates:
                pairs = [(lookups[row][(day, code)], lookups[column][(day, code)])
                         for code in instruments
                         if (day, code) in lookups[row] and (day, code) in lookups[column]]
                if len(pairs) < MIN_CROSS_SECTION:
                    continue
                left = np.asarray([pair[0] for pair in pairs], dtype=float)
                right = np.asarray([pair[1] for pair in pairs], dtype=float)
                if np.unique(left).size < 2 or np.unique(right).size < 2:
                    continue
                rho = _pearson(_rankdata(left), _rankdata(right))
                if rho is not None:
                    per_day.append(rho)
            value = float(np.mean(per_day)) if per_day else None
            matrix[row][column] = matrix[column][row] = value
    return {"labels": names, "matrix": matrix, "method": "mean cross-sectional Spearman"}


def redundancy(correlation: dict[str, Any]) -> dict[str, Any]:
    labels, matrix = correlation["labels"], correlation["matrix"]
    pairs = []
    for row in range(len(labels)):
        for column in range(row + 1, len(labels)):
            value = matrix[row][column]
            pairs.append({"left": labels[row], "right": labels[column], "correlation": value,
                          "redundancy": None if value is None else 1 - abs(value)})
    return {"pairs": pairs}


def collinearity(correlation: dict[str, Any]) -> dict[str, Any]:
    """VIF from the correlation matrix; a singular matrix returns not_available."""
    np = _numpy()
    labels, matrix = correlation["labels"], correlation["matrix"]
    if len(labels) < 2:
        return {"available": False, "reason": "need_at_least_two_factors"}
    if any(value is None for row in matrix for value in row):
        return {"available": False, "reason": "correlation_incomplete"}
    try:
        inverse = np.linalg.inv(np.asarray(matrix, dtype=float))
    except np.linalg.LinAlgError:
        return {"available": False, "reason": "singular_correlation_matrix"}
    diagonal = np.diag(inverse)
    # A VIF below 1 means the matrix is numerically singular (perfectly collinear factors).
    values = np.where(np.isfinite(diagonal) & (diagonal >= 1.0), diagonal, np.inf)
    maximum = float(values.max())
    return {"available": True, "vif": {label: float(values[index]) for index, label in enumerate(labels)},
            "max_vif": maximum, "high_collinearity": maximum > 10.0,
            "perfect_collinearity": bool(np.isinf(values).any()),
            "note": "VIF > 10 表示与其它因子高度共线（冗余），不构成独立信息；inf 表示完全共线"}


def ic_series_correlation(panels: list[dict[str, Any]], returns_grid, dates: list[str]) -> dict[str, Any]:
    """Correlation of IC series: are two factors predicting the same days?"""
    np = _numpy()
    series = {}
    for panel in panels:
        grid = panel_matrix(panel)
        rows = int(min(len(dates), grid.shape[0], returns_grid.shape[0]))
        values = {}
        for row in ic_series(grid[:rows], returns_grid[:rows], dates[:rows]):
            values[row["date"]] = row["ic"]
        series[panel["name"]] = values
    labels = list(series)
    matrix = [[None] * len(labels) for _ in labels]
    for row, left in enumerate(labels):
        matrix[row][row] = 1.0
        for column in range(row + 1, len(labels)):
            right = labels[column]
            shared = sorted(set(series[left]) & set(series[right]))
            if len(shared) < 5:
                continue
            value = _pearson([series[left][day] for day in shared], [series[right][day] for day in shared])
            matrix[row][column] = matrix[column][row] = value
    return {"labels": labels, "matrix": matrix, "days_required": 5}


def orthogonal_and_incremental(panels: list[dict[str, Any]], returns_grid, dates: list[str]) -> dict[str, Any]:
    """Residual IC of each factor against the others, plus the equal-weight increment."""
    np = _numpy()
    grids = [panel_matrix(panel) for panel in panels]
    names = [panel["name"] for panel in panels]
    result: dict[str, Any] = {"orthogonal_ic": {}, "incremental_ic": None}
    ic_by_name = {name: ic_series(grid, returns_grid, dates) for name, grid in zip(names, grids)}
    base_ic = {}
    for name, series in ic_by_name.items():
        values = [row["ic"] for row in series]
        base_ic[name] = float(np.mean(values)) if values else None
    if len(names) >= 2:
        residual_ic = {}
        for index, name in enumerate(names):
            per_day = []
            others = [grid for position, grid in enumerate(grids) if position != index]
            rows = int(min([len(dates), grids[index].shape[0]] + [grid.shape[0] for grid in others]))
            for row in range(rows):
                target = grids[index][row]
                design = [grid[row] for grid in others]
                mask = np.isfinite(target)
                for column in design:
                    mask &= np.isfinite(column)
                if int(mask.sum()) < MIN_CROSS_SECTION + len(design):
                    continue
                y = _zscore(target[mask])
                x = np.column_stack([_zscore(column[mask]) for column in design])
                x = np.column_stack([np.ones(int(mask.sum())), x])
                try:
                    coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
                except np.linalg.LinAlgError:
                    continue
                residual = y - x @ coefficients
                forward = returns_grid[row][mask]
                ic = _pearson(residual, _zscore(forward)) if np.unique(residual).size > 1 else None
                if ic is not None:
                    per_day.append(ic)
            values = np.asarray(per_day, dtype=float)
            residual_ic[name] = ({"days": int(len(values)), "ic_mean": float(values.mean()),
                                  "delta_vs_raw": (float(values.mean()) - base_ic[name])
                                  if base_ic.get(name) is not None else None}
                                 if len(values) >= 2 else {"days": int(len(values)), "available": False})
        result["orthogonal_ic"] = residual_ic
    combined_days = []
    rows = int(min([len(dates)] + [grid.shape[0] for grid in grids] + [returns_grid.shape[0]]))
    for row in range(rows):
        columns = [grid[row] for grid in grids]
        mask = np.ones(len(dates), dtype=bool) if False else np.isfinite(columns[0])
        for column in columns:
            mask &= np.isfinite(column)
        forward = returns_grid[row]
        mask &= np.isfinite(forward)
        if int(mask.sum()) < MIN_CROSS_SECTION + len(columns):
            continue
        combined = np.mean([_zscore(column[mask]) for column in columns], axis=0)
        ic = _pearson(combined, forward[mask])
        if ic is not None:
            combined_days.append(ic)
    result["combined_ic"] = ({"days": len(combined_days), "ic_mean": float(np.mean(combined_days))}
                             if len(combined_days) >= 2 else {"available": False})
    if len(names) >= 2:
        leaves = []
        for index, name in enumerate(names):
            subset = [grid for position, grid in enumerate(grids) if position != index]
            days = []
            for row in range(rows):
                columns = [grid[row] for grid in subset]
                mask = np.isfinite(columns[0])
                for column in columns:
                    mask &= np.isfinite(column)
                forward = returns_grid[row]
                mask &= np.isfinite(forward)
                if int(mask.sum()) < MIN_CROSS_SECTION + len(columns):
                    continue
                combined = np.mean([_zscore(column[mask]) for column in columns], axis=0)
                value = _pearson(combined, forward[mask])
                if value is not None:
                    days.append(value)
            leaves.append((name, float(np.mean(days)) if len(days) >= 2 else None))
        result["incremental_ic"] = [{"factor": name, "without_ic": value,
                                     "delta": (result["combined_ic"].get("ic_mean") - value)
                                     if value is not None and result["combined_ic"].get("ic_mean") is not None else None}
                                    for name, value in leaves]
    return result


def _zscore(values):
    np = _numpy()
    values = np.asarray(values, dtype=float)
    std = values.std()
    return (values - values.mean()) / std if std else values - values.mean()


NOT_AVAILABLE = (
    {"metric": "holding_overlap",
     "reason": "缺少持仓/成交明细；引擎只导出组合序列，未导出逐日持仓"},
    {"metric": "crowding",
     "reason": "缺少市场层面因子使用与拥挤度数据；本机只有单一情景快照"},
)


def analyze(entries: list[dict[str, Any]], returns_by_horizon: dict[int, Any], *,
            horizons: tuple[int, ...] = DEFAULT_HORIZONS, dataset: dict[str, Any] | None = None,
            calendar_id: str | None = None, limitations: tuple[str, ...] = (),
            analysis_version: int = 1) -> dict[str, Any]:
    """Compose the factor report: single-factor statistics plus the overlap family."""
    if type(analysis_version) is not int or analysis_version not in (1, 2):
        raise FactorError("analysis_version must be 1 or 2")
    np = _numpy()
    if not entries:
        raise FactorError("no factors to analyse")
    if len(entries) > MAX_FACTORS_PER_ANALYSIS:
        raise FactorError(f"at most {MAX_FACTORS_PER_ANALYSIS} factors per analysis")
    panels = [entry["panel"] for entry in entries]
    dates, instruments = aligned_rows(panels)
    if len(dates) < 2 or len(instruments) < MIN_CROSS_SECTION:
        raise FactorError("factors do not share enough dates/instruments to analyse")
    column_index = {code: position for position, code in enumerate(instruments)}
    row_index = {day: position for position, day in enumerate(dates)}
    sliced = []
    for panel in panels:
        grid = panel_matrix(panel)
        own_columns = {code: position for position, code in enumerate(panel["instruments"])}
        own_rows = {day: position for position, day in enumerate(panel["dates"])}
        out = np.full((len(dates), len(instruments)), np.nan, dtype=float)
        for row, day in enumerate(dates):
            for column, code in enumerate(instruments):
                out[row][column] = grid[own_rows[day]][own_columns[code]]
        sliced.append(out)
    primary = horizons[0]
    factor_rows = []
    p_values = []
    for entry, grid in zip(entries, sliced):
        per_horizon = {}
        for horizon in horizons:
            forward = returns_by_horizon.get(horizon)
            if forward is None:
                per_horizon[str(horizon)] = {"horizon": horizon, "available": False,
                                             "reason": "no_returns_for_horizon"}
                continue
            if analysis_version == 2:
                from .factors_v2 import stats
                rank_stats = stats(ic_series(grid, forward, dates, "spearman"), horizon, len(entries), dates[:-horizon])
                ic_stats = stats(ic_series(grid, forward, dates, "pearson"), horizon, len(entries), dates[:-horizon])
            else:
                rank_stats = _series_stats(ic_series(grid, forward, dates, "spearman"), horizon, len(entries))
                ic_stats = _series_stats(ic_series(grid, forward, dates, "pearson"), horizon, len(entries))
            per_horizon[str(horizon)] = {
                "horizon": horizon, "available": bool(rank_stats.get("available") or ic_stats.get("available")),
                "rank_ic": rank_stats, "ic": ic_stats}
        primary_stats = per_horizon.get(str(primary)) or {}
        rank_primary = primary_stats.get("rank_ic") or {}
        if rank_primary.get("available") and rank_primary.get("p_value") is not None:
            p_values.append(rank_primary["p_value"])
        forward_primary = returns_by_horizon.get(primary)
        factor_rows.append({
            "factor_id": entry["factor_id"], "name": entry["name"],
            "coverage": entry["panel"].get("coverage"),
            "ic": primary_stats.get("ic"), "rank_ic": primary_stats.get("rank_ic"),
            "horizons": per_horizon,
            "quantile_spread": (quantile_spread(grid, forward_primary, dates)
                                if forward_primary is not None else {"available": False,
                                                                     "reason": "no_returns_for_horizon"}),
            "turnover": rank_turnover(grid),
        })
    adjusted = bh_fdr([value for value in p_values if value is not None]) if p_values else []
    cursor = 0
    for row in factor_rows:
        rank_stats = (row["rank_ic"] or {})
        if rank_stats.get("available") and rank_stats.get("p_value") is not None:
            row["fdr_q"] = adjusted[cursor] if cursor < len(adjusted) else None
            cursor += 1
        else:
            row["fdr_q"] = None
    correlation = pairwise_value_correlation(panels)
    overlap = {
        "value_correlation": correlation,
        "redundancy": redundancy(correlation),
        "collinearity": collinearity(correlation),
        "ic_series_correlation": (ic_series_correlation(panels, returns_by_horizon[primary], dates)
                                  if primary in returns_by_horizon else {"available": False,
                                                                         "reason": "no_returns_for_horizon"}),
        "not_available": list(NOT_AVAILABLE),
    }
    if primary in returns_by_horizon:
        overlap.update(orthogonal_and_incremental(panels, returns_by_horizon[primary], dates))
    else:
        overlap.update({"orthogonal_ic": {}, "incremental_ic": None})
    report = {
        "basis": {
            "kind": "platform_factor_analysis",
            "formula": "per-date cross-sectional correlation of factor value vs forward return "
                       "r_{t→t+h} = close_{t+h}/close_t - 1",
            "horizons": list(horizons),
            "primary_horizon": primary,
            "ic_methods": ["spearman(rank_ic)", "pearson(ic)"],
            "significance": "Newey-West standard error with lag=h-1; two-sided normal p-value; "
                            "significance is computed on the Rank IC series; Benjamini-Hochberg FDR "
                            "across the analysed factors",
            "sample": {"start": dates[0], "end": dates[-1], "dates": len(dates),
                       "instruments": len(instruments), "cells": len(dates) * len(instruments)},
            "factor_count": len(entries),
            "dataset": dataset or {},
            "calendar_id": calendar_id,
            "provenance": "平台计算（因子值与收益均为本地记录数据；不是引擎原生指标）",
        },
        "factors": factor_rows,
        "overlap": overlap,
        "limitations": [
            "因子面板来自已导入的记录；未导入的因子不参与计算",
            "收益标签由平台按声明公式从同一数据内容版本的快照计算，未使用未来修订数据",
            *limitations,
        ],
    }
    if analysis_version == 2:
        from .factors_v2 import finish
        report = finish(report, entries)
    return json_safe(report)
