"""Versioned risk analysis over one immutable, explicitly identified result revision.

Legacy calculations remain in risk.py. This module does not read engine objects or
infer unknown history from the current environment.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

from . import risk
from .dto import json_safe
from .series_view import NATIVE_RETURN, NATIVE_LABEL, DERIVED_LABEL

FORMULAS = {
    "total_return": "prod(1+r)-1",
    "annualised_return": "(1+total_return)^(ppy/N)-1; total_return > -1",
    "volatility": "std(r, ddof=1)*sqrt(ppy)",
    "sharpe": "mean(r-rf)/std(r-rf, ddof=1)*sqrt(ppy)",
    "sortino_target_downside": "mean(r-T)/sqrt(mean(min(0,r-T)^2))*sqrt(ppy); mean over all N",
    "calmar": "annualised_return/abs(max_drawdown)",
    "max_drawdown": "min(E_t/max(E_0,...,E_t)-1); E=cumprod(1+r)",
    "mean_daily": "mean(r)", "std_daily": "std(r, ddof=1)",
    "var": "quantile(r, q, method=linear)",
    "cvar": "mean(r[r<=VaR]); at least 2 tail observations",
    "positive_ratio": "count(r>0)/N",
    "skew": "mean((r-mean(r))^3)/std(r, ddof=1)^3",
    "kurtosis": "mean((r-mean(r))^4)/std(r, ddof=1)^4; non-excess",
    "best_day": "max(r)", "worst_day": "min(r)",
    "calendar": "prod(1+r)-1 in each observed year/month; missing month=null",
    "drawdown_episodes": "peak-to-recovery episodes of observed E, sorted by depth; first 3",
}
LIMITATIONS = [
    "工作台计算；输入定义映射不是来源真实性或策略有效性认证",
    "sqrt(ppy)年化为工程约定；没有验证收益独立同分布，重叠收益不视为独立样本",
    "回撤从首个观测权益起，不含首个观测之前的损失；不是完整初始账户回撤",
    "VaR/CVaR为样本内历史法；偏度/峰度沿用既有估计量，未作无偏修正",
    "仅支持已登记的日频绝对收益及无外部现金流；未接入分红再投资与真实成本细分",
    "已拒绝显式缺测；尚未用完整日历快照核验未记录日期，不能证明日历覆盖完整",
]


def scalar(value: float | None, name: str) -> dict[str, Any]:
    if value is None:
        return {"value": 0.0, "source": "default", "unit": "daily_decimal_return"}
    if type(value) not in (int, float) or not math.isfinite(value):
        raise risk.RiskError(f"{name} must be a finite same-frequency scalar")
    return {"value": float(value), "source": "caller", "unit": "daily_decimal_return"}


def input_view(revision: dict[str, Any]) -> dict[str, Any]:
    package = revision["result"]
    entries = {entry["metric_id"]: entry for entry in package.get("series", [])}
    # A present but unusable primary source must not disappear behind a fallback.
    native = entries.get(NATIVE_RETURN)
    entry = native if native is not None else entries.get("platform.equity")
    context = package.get("evidence", {}).get("comparison") or {}
    basis = {"kind": "absolute", "relative_to": None,
             "cost_basis": "before_cost" if native is not None else "after_cost",
             "frequency": "daily", "cashflow_policy": context.get("cashflow_policy"),
             "definition_source": "registered_definition"}
    view = {"dates": [], "values": [], "source": NATIVE_LABEL if native is not None else DERIVED_LABEL,
            "input_basis": basis, "entry": entry, "reason": None}
    if entry is None:
        view.update(reason="no_return_series", source=None, input_basis={"kind": "unknown"})
        return view
    expected = "native.qlib.report.return.v1" if native is not None else "platform.equity.account.v1"
    if entry.get("definition_id") != expected:
        view.update(reason="return_basis_unknown", input_basis={"kind": "unknown", "declared_definition": entry.get("definition_id")})
        return view
    if context.get("cashflow_policy") != "none":
        view["reason"] = "cashflow_policy_unknown_or_unsupported"
        return view
    if entry.get("axis") != "trading_date" or not entry.get("calendar_id"):
        view["reason"] = "daily_calendar_required"
        return view
    if native is not None and entry.get("unit") != "ratio":
        view["reason"] = "return_unit_unsupported"
        return view
    if entry.get("availability") != "available":
        view["reason"] = "source_unavailable"
        return view
    points = entry.get("points", [])
    dates = [point["x"] for point in points]
    values = [point.get("value") for point in points]
    view["dates"] = dates
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        view["reason"] = "missing_or_nonfinite_observation"
        return view
    try:
        valid_dates = all(date.fromisoformat(day).isoformat() == day for day in dates)
    except (ValueError, TypeError):
        valid_dates = False
    if not valid_dates or dates != sorted(set(dates)):
        view["reason"] = "invalid_daily_coordinates"
        return view
    if native is None:
        if any(value <= 0 for value in values):
            view["reason"] = "nonpositive_equity"
            return view
        values = [values[i] / values[i-1] - 1 for i in range(1, len(values))]
        view["dates"] = dates[1:]
        basis["window"] = "between_observed_equity_points"
    elif any(value <= -1 for value in values):
        view["reason"] = "nonpositive_wealth_unsupported"
        return view
    view["values"] = values
    if len(values) < risk.MIN_OBSERVATIONS:
        view["reason"] = "insufficient_observations"
    return view


def report(revision: dict[str, Any], *, periods_per_year: int,
           annualisation_source: str, risk_free_rate: float | None = None,
           target_return: float | None = None) -> dict[str, Any]:
    rf, target = scalar(risk_free_rate, "risk_free_rate"), scalar(target_return, "target_return")
    view = input_view(revision)
    reason = view["reason"]
    package = revision["result"]
    entry = view["entry"] or {}
    refs = {"run_id": revision["run_id"], "revision_id": revision["revision_id"],
            "metric_id": entry.get("metric_id"), "definition_id": entry.get("definition_id"),
            "dataset": package["run"].get("dataset") or {},
            "snapshot_id": (package["run"].get("dataset") or {}).get("snapshot_id"),
            "calendar_id": entry.get("calendar_id")}
    params = {"periods_per_year": periods_per_year, "periods_per_year_source": annualisation_source,
              "risk_free_rate": rf, "target_return": target, "var_quantile": 0.05,
              "ddof": 1, "zero_tolerance": risk.ZERO_TOLERANCE, "episodes": 3}
    reasons: dict[str, str] = {}
    if not reason:
        np = risk._numpy()
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                result = risk.performance_report(view["dates"], view["values"], periods_per_year=periods_per_year)
        except (OverflowError, FloatingPointError):
            reason = "nonfinite_calculation"
    if reason:
        metrics = {key: None for key in FORMULAS if key not in ("calendar", "drawdown_episodes")}
        result = {"metrics": metrics, "calendar": {"annual": {}, "monthly": {}}, "drawdown_episodes": []}
        reasons = {key: reason for key in FORMULAS}
    else:
        metrics = result["metrics"]
        metrics.pop("sortino")
        np = risk._numpy()
        values = np.asarray(view["values"], dtype=float)
        excess, downside_target = values - rf["value"], values - target["value"]
        std = float(excess.std(ddof=1))
        dd = math.hypot(*(min(0.0, float(value)) / math.sqrt(len(values)) for value in downside_target))
        metrics["sharpe"] = float(excess.mean()) / std * math.sqrt(periods_per_year) if std > risk.ZERO_TOLERANCE else None
        metrics["sortino_target_downside"] = float(downside_target.mean()) / dd * math.sqrt(periods_per_year) if dd > 0 else None
        if metrics["sharpe"] is None:
            reasons["sharpe"] = "zero_return_dispersion"
        if metrics["sortino_target_downside"] is None:
            reasons["sortino_target_downside"] = "no_downside_deviation"
        tail_count = int((values <= metrics["var"]).sum())
        params["tail_observations"] = tail_count
        if tail_count < 2:
            metrics["cvar"] = None
            reasons["cvar"] = "insufficient_tail_observations"
        for key, value in metrics.items():
            if value is None:
                reasons.setdefault(key, "no_drawdown" if key == "calmar" and metrics["max_drawdown"] == 0 else "undefined_for_sample")
            elif not math.isfinite(value):
                metrics[key] = None
                reasons[key] = "nonfinite_calculation"
    definitions = {}
    for key, formula in FORMULAS.items():
        definition_id = "platform.sortino.target_downside.v2" if key == "sortino_target_downside" else f"platform.risk.{key}.v2"
        definitions[key] = {"definition_id": definition_id, "formula": formula, "input_refs": refs,
                            "input_basis": view["input_basis"], "parameters": params,
                            "availability": "unavailable" if key in reasons else "available",
                            "reason": reasons.get(key)}
    result.update(schema_version=2, run_id=revision["run_id"], revision_id=revision["revision_id"],
                  title=package["run"]["title"], return_source=view["source"],
                  provenance=revision.get("provenance", {"verification": "not_classified"}),
                  synthetic=package["run"].get("synthetic"), definitions=definitions,
                  basis={"kind": "platform_risk", "formulas": FORMULAS, "parameters": params,
                         "dataset": refs["dataset"], "periods_per_year_source": annualisation_source,
                         "sample": {"start": view["dates"][0] if view["dates"] else None,
                                    "end": view["dates"][-1] if view["dates"] else None,
                                    "observations": len(view["values"]) if not reason else None,
                                    "source_observations": len(entry.get("points", [])),
                                    "reason": reason},
                         "provenance": "工作台计算；来源与行情性质见provenance"},
                  not_available=[{"metric": key, "reason": value} for key, value in reasons.items()],
                  limitations=LIMITATIONS)
    return json_safe(result)
