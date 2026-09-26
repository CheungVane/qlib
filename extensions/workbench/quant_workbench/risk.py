"""Performance and risk statistics for a recorded return series (RESULT_CONTRACT U22).

Platform-computed: every report carries formulas, the sample basis, the annualisation used
and the unavailable list. Degenerate inputs fail closed instead of returning approximations.
"""

from __future__ import annotations

import math
from typing import Any

from . import numeric
from .dto import json_safe

MIN_OBSERVATIONS = 20
ZERO_TOLERANCE = numeric.ZERO_TOLERANCE


class RiskError(ValueError):
    """Invalid risk input; the API maps this to 400 with the reason preserved."""


def _numpy():
    return numeric.numpy(RiskError, "risk metrics need numpy (install the 'analysis' extra)")


def performance_report(dates: list[str], returns: list[float], *, periods_per_year: int = 238,
                       var_quantile: float = 0.05, episodes: int = 3) -> dict[str, Any]:
    np = _numpy()
    if len(dates) != len(returns):
        raise RiskError("dates and returns must have the same length")
    values = np.asarray([value for value in returns if value is not None], dtype=float)
    if len(values) < MIN_OBSERVATIONS:
        raise RiskError(f"risk metrics need at least {MIN_OBSERVATIONS} observations")
    if not np.isfinite(values).all():
        raise RiskError("returns contain non-finite values")
    if isinstance(periods_per_year, bool) or not isinstance(periods_per_year, int) or periods_per_year < 1:
        raise RiskError("periods_per_year must be a positive integer")
    if not 0 < var_quantile < 1:
        raise RiskError("var_quantile must be between 0 and 1")
    count = len(values)
    equity = np.cumprod(1 + values)
    total_return = float(equity[-1] - 1)
    years = count / periods_per_year
    annualised = float((1 + total_return) ** (1 / years) - 1) if years > 0 and total_return > -1 else None
    mean, std = float(values.mean()), float(values.std(ddof=1))
    volatility = std * math.sqrt(periods_per_year)
    # near-zero dispersion would produce an absurd ratio; treat it as degenerate instead
    degenerate = std <= ZERO_TOLERANCE
    sharpe = mean / std * math.sqrt(periods_per_year) if not degenerate else None
    downside = values[values < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (mean / downside_std * math.sqrt(periods_per_year)
               if downside_std > ZERO_TOLERANCE else None)
    drawdowns, peaks = [], []
    peak = equity[0]
    for value in equity:
        peak = max(peak, value)
        peaks.append(peak)
        drawdowns.append(value / peak - 1)
    max_drawdown = float(min(drawdowns))
    calmar = annualised / abs(max_drawdown) if annualised is not None and max_drawdown < 0 else None
    quantile = float(np.quantile(values, var_quantile))
    tail = values[values <= quantile]
    centred = values - mean
    skew = float((centred ** 3).mean() / std ** 3) if not degenerate else None
    kurtosis = float((centred ** 4).mean() / std ** 4) if not degenerate else None
    episodes_list = _drawdown_episodes(dates, equity, peaks, drawdowns, limit=episodes)
    unavailable = []
    if degenerate:
        unavailable.append({"metric": "sharpe", "reason": "收益离散度低于 1e-12，Sharpe 无定义"})
    if downside_std <= ZERO_TOLERANCE:
        unavailable.append({"metric": "sortino", "reason": "样本内没有负收益或下行离散度低于 1e-12，Sortino 无定义"})
    if max_drawdown == 0:
        unavailable.append({"metric": "calmar", "reason": "样本内没有回撤，Calmar 无定义"})
    if len(tail) < 2:
        unavailable.append({"metric": "cvar", "reason": f"分位以下样本不足（{len(tail)} 个）"})
    annualised_returns, monthly = _calendar_returns(dates, values)
    return json_safe({
        "basis": {
            "kind": "platform_risk",
            "formulas": {
                "total_return": "Π(1+r)-1",
                "annualised_return": "(1+total_return)^(ppy/N)-1",
                "volatility": "std(r, ddof=1)·√ppy",
                "sharpe": "mean(r)/std(r)·√ppy",
                "sortino": "mean(r)/std(r|r<0)·√ppy",
                "calmar": "annualised_return / |max_drawdown|",
                "max_drawdown": "min(equity_t / peak_t - 1)",
                "var_cvar": f"history: {int(var_quantile*100)}% quantile and the mean below it",
            },
            "parameters": {"periods_per_year": periods_per_year, "var_quantile": var_quantile},
            "sample": {"start": dates[0], "end": dates[-1], "observations": count},
            "provenance": "平台计算（收益来自已记录结果；不是引擎原生指标）",
        },
        "metrics": {
            "total_return": total_return, "annualised_return": annualised,
            "volatility": volatility, "sharpe": sharpe, "sortino": sortino, "calmar": calmar,
            "max_drawdown": max_drawdown, "mean_daily": mean, "std_daily": std,
            "var": quantile, "cvar": float(tail.mean()) if len(tail) else None,
            "positive_ratio": float((values > 0).mean()), "skew": skew, "kurtosis": kurtosis,
            "best_day": float(values.max()), "worst_day": float(values.min()),
        },
        "drawdown_episodes": episodes_list,
        "calendar": {"annual": annualised_returns, "monthly": monthly},
        "not_available": [*unavailable,
                          {"metric": "dividend_reinvestment",
                           "reason": "分红再投资与真实成本细分未接入；当前只使用已记录的复权收益序列"}],
        "limitations": [
            "年化使用配置中的交易日数，不做其它假设",
            "VaR/CVaR 为历史法，只描述样本内的尾部，不是未来损失保证",
            "缺月显示为 null，不填 0",
        ],
    })


def _drawdown_episodes(dates, equity, peaks, drawdowns, limit=3) -> list[dict[str, Any]]:
    out, index, count = [], 0, len(drawdowns)
    while index < count:
        if drawdowns[index] == 0:
            index += 1
            continue
        start = index - 1
        trough = index
        while index < count and drawdowns[index] < 0:
            if drawdowns[index] < drawdowns[trough]:
                trough = index
            index += 1
        recovery = index if index < count and drawdowns[index] == 0 else None
        out.append({"start": dates[max(start, 0)], "trough": dates[trough],
                    "recovery": dates[recovery] if recovery is not None else None,
                    "depth": float(drawdowns[trough]),
                    "length_days": (recovery if recovery is not None else count - 1) - max(start, 0),
                    "status": "recovered" if recovery is not None else "recovering"})
    out.sort(key=lambda item: item["depth"])
    return out[:limit]


def _calendar_returns(dates, values) -> tuple[dict[str, Any], dict[str, Any]]:
    annual: dict[str, float] = {}
    monthly: dict[str, dict[str, float | None]] = {}
    for day, value in zip(dates, values):
        year, month = day[:4], day[5:7]
        annual[year] = (1 + annual.get(year, 0.0)) * (1 + float(value)) - 1
        bucket = monthly.setdefault(year, {})
        bucket[month] = (1 + (bucket.get(month) or 0.0)) * (1 + float(value)) - 1
    months = [f"{index:02d}" for index in range(1, 13)]
    return annual, {year: {month: months_map.get(month) for month in months}
                    for year, months_map in monthly.items()}
