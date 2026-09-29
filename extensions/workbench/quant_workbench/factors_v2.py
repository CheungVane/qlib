"""Corrected factor statistics and explicit input/definition records (T01-F)."""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from . import factors as legacy


def align(entries, snapshot: Path | None = None, *, calendar=None):
    """Restore missing calendar rows before constructing h-trading-day labels."""
    calendar = list(calendar) if calendar is not None else (snapshot / "calendars/day.txt").read_text().split()
    try:
        valid = all(date.fromisoformat(day).isoformat() == day for day in calendar)
    except ValueError:
        valid = False
    if not valid or not calendar or calendar != sorted(set(calendar)):
        raise legacy.FactorError("snapshot calendar must contain sorted unique ISO dates")
    panels = [entry["panel"] for entry in entries]
    known = set(calendar)
    if any(not set(panel["dates"]).issubset(known) for panel in panels):
        raise legacy.FactorError("factor dates are outside the recorded snapshot calendar")
    start = max(panel["dates"][0] for panel in panels)
    end = min(panel["dates"][-1] for panel in panels)
    dates = [day for day in calendar if start <= day <= end]
    _, instruments = legacy.aligned_rows(panels)
    if len(dates) > legacy.PANEL_LIMITS["dates"] or len(dates)*len(instruments) > legacy.PANEL_LIMITS["cells"]:
        raise legacy.FactorError("calendar-aligned analysis exceeds the panel budget")
    if len(dates) < 2 or len(instruments) < legacy.MIN_CROSS_SECTION:
        raise legacy.FactorError("factors do not share enough dates/instruments to analyse")
    aligned = []
    for entry in entries:
        lookup = legacy._panel_lookup(entry["panel"])
        panel = legacy.canonical_panel({"schema_version": 1, "name": entry["name"],
            "calendar_id": entry["panel"].get("calendar_id"), "dates": dates, "instruments": instruments,
            "values": [lookup.get((day, code)) for day in dates for code in instruments]})
        aligned.append({**entry, "panel": panel})
    return aligned


def stats(series, horizon, factor_count, expected_dates):
    np = legacy._numpy()
    values = np.asarray([row["ic"] for row in series], dtype=float)
    count = len(values)
    lag = min(horizon-1, max(0, count-1))
    result = {"horizon": horizon, "days": count, "available": count >= 2,
              "ic_mean": float(values.mean()) if count else None,
              "ic_std": float(values.std(ddof=1)) if count >= 2 else None,
              "icir": None, "positive_ratio": float((values > 0).mean()) if count else None,
              "nw_lag": lag, "nw_se_mean": None, "nw_omega": None,
              "t_stat": None, "p_value": None, "tests_disclosed": factor_count,
              "significance_available": False, "significance_reason": None,
              "expected_days": len(expected_dates)}
    constant = bool(count and np.all(values == values[0]))
    if constant and count >= 2:
        result["ic_std"] = 0.0
    if result["ic_std"] and result["ic_std"] > 0:
        result["icir"] = result["ic_mean"] / result["ic_std"]
    if [row["date"] for row in series] != list(expected_dates):
        result["significance_reason"] = "missing_trading_day_ic"
    elif count < max(10, lag+2):
        result["significance_reason"] = "insufficient_observations"
    elif not np.isfinite(values).all():
        result["significance_reason"] = "nonfinite_ic"
    else:
        centred = values - values.mean()
        # All lag covariance sums use N, not N-k. No variance floor/correction.
        omega = 0.0 if constant else float(np.dot(centred, centred) / count)
        if not constant:
            for k in range(1, lag+1):
                omega += 2*(1-k/(lag+1))*float(np.dot(centred[k:], centred[:-k])/count)
        result["nw_omega"] = omega
        if not math.isfinite(omega) or omega <= 0:
            result["significance_reason"] = "nonpositive_long_run_variance"
        else:
            se = math.sqrt(omega/count)
            t = result["ic_mean"] / se
            if not math.isfinite(se) or not math.isfinite(t):
                result["significance_reason"] = "nonfinite_standard_error"
            else:
                result.update(nw_se_mean=se, t_stat=t, p_value=legacy._two_sided_p(t),
                              significance_available=True)
    if count < 2:
        result["reason"] = "not_enough_observations"
    return result


def correlations(panels):
    np = legacy._numpy()
    names = [panel["name"] for panel in panels]
    lookups = [legacy._panel_lookup(panel) for panel in panels]
    matrix = [[None]*len(panels) for _ in panels]
    counts = [[0]*len(panels) for _ in panels]
    for i in range(len(panels)):
        for j in range(i, len(panels)):
            dates, instruments = legacy.aligned_rows([panels[i], panels[j]])
            daily = []
            for day in dates:
                pairs = [(lookups[i][day, code], lookups[j][day, code]) for code in instruments
                         if (day, code) in lookups[i] and (day, code) in lookups[j]]
                if len(pairs) < legacy.MIN_CROSS_SECTION:
                    continue
                rho = legacy._pearson(legacy._rankdata(np.asarray([p[0] for p in pairs])),
                                      legacy._rankdata(np.asarray([p[1] for p in pairs])))
                if rho is not None and math.isfinite(rho):
                    daily.append(max(-1.0, min(1.0, rho)))
            value = float(np.mean(daily)) if daily else None
            matrix[i][j] = matrix[j][i] = value
            counts[i][j] = counts[j][i] = len(daily)
    return {"labels": names, "matrix": matrix, "valid_days": counts,
            "method": "mean cross-sectional Spearman"}


def finish(report, entries):
    """Attach immutable input refs; legacy estimates retain explicit formula limitations."""
    basis = report["basis"]
    refs = {"panels": [{"factor_id": e["factor_id"], "panel_id": e.get("panel_id"),
                        "content_hash": e.get("content_hash")} for e in entries],
            "dataset": basis["dataset"], "calendar_id": basis["calendar_id"]}
    params = {"horizons": basis["horizons"], "primary_horizon": basis["primary_horizon"],
              "requested_factor_count": len(entries), "cross_section_min": legacy.MIN_CROSS_SECTION,
              "ddof": 1, "small_sample_correction": False,
              "sample": basis["sample"], "factor_names": [e["name"] for e in entries]}
    input_basis = {"kind": "absolute_forward_price_return", "cost_basis": "before_cost",
                   "price_rule": "legacy close * optional factor; materialization semantics not certified",
                   "window": "shared calendar range; last h days excluded from significance"}

    def card(name, formula, available=True, reason=None, extra=None):
        factor_only = name in ("coverage", "turnover", "value_correlation", "collinearity",
                               "absolute_correlation_similarity", "correlation_distance")
        return {"definition_id": f"platform.factor.{name}.v2", "formula": formula,
                "input_refs": refs, "input_basis": {"kind": "factor_values", "cost_basis": "not_applicable"} if factor_only else input_basis,
                "parameters": {**params, **(extra or {})},
                "availability": "available" if available else "unavailable",
                "reason": None if available else reason or "not_enough_observations"}

    formulas = {"ic_mean": "mean(daily cross-sectional IC)", "ic_std": "std(daily IC, ddof=1)",
                "icir": "mean(IC)/std(IC, ddof=1)", "positive_ratio": "count(IC>0)/N",
                "nw_omega": "gamma0+2*sum((1-k/(L+1))*gamma_k); gamma_k=sum(products)/N",
                "nw_se_mean": "sqrt(omega/N); L=min(h-1,N-1); no small-sample correction",
                "t_stat": "mean(IC)/se_mean", "p_value": "erfc(abs(t)/sqrt(2)); normal approximation"}
    for row, entry in zip(report["factors"], entries):
        row["panel_id"] = entry.get("panel_id")
        row["provenance"] = entry.get("provenance") or {"data_nature": "unknown"}
        row["research_status"] = "exploratory"
        for group in row["horizons"].values():
            for method in ("rank_ic", "ic"):
                values = group.get(method)
                if not values:
                    continue
                values["definitions"] = {key: card(method+"."+key, formula, values.get(key) is not None,
                    None if values.get(key) is not None else values.get("significance_reason") or "undefined_for_sample",
                    {"horizon": group["horizon"], "lag": values["nw_lag"], "factor_id": entry["factor_id"],
                     "method": "spearman" if method == "rank_ic" else "pearson"}) for key, formula in formulas.items()}
        row["definitions"] = {
            "coverage": card("coverage", "valid cells / calendar-aligned cells", row.get("coverage") is not None),
            "fdr_q": card("fdr_q", "BH adjusted primary-horizon Rank IC p; valid tests only", row["fdr_q"] is not None,
                          None if row["fdr_q"] is not None else "significance_unavailable"),
            "quantile_spread": card("quantile_spread", "five rank groups; mean(Q5)-mean(Q1); monotonicity=Pearson(group index, group means), proxy threshold abs(r)>0.8",
                                    row["quantile_spread"].get("available", False), row["quantile_spread"].get("reason")),
            "turnover": card("turnover", "1-mean(Spearman(previous valid cross-section,current)); gaps may be skipped",
                             row["turnover"].get("available", False), row["turnover"].get("reason")),
        }
    overlap = report["overlap"]
    correlation = correlations([entry["panel"] for entry in entries])
    overlap["value_correlation"] = correlation
    overlap["collinearity"] = legacy.collinearity(correlation)
    overlap.pop("redundancy")
    for key, formula in (("absolute_correlation_similarity", "abs(mean(daily Spearman))"),
                          ("correlation_distance", "1-abs(mean(daily Spearman))")):
        pairs = []
        for i, left in enumerate(correlation["labels"]):
            for j in range(i+1, len(entries)):
                corr = correlation["matrix"][i][j]
                value = None if corr is None else abs(corr) if key == "absolute_correlation_similarity" else 1-abs(corr)
                pairs.append({"left": left, "right": correlation["labels"][j], "correlation": corr,
                              "valid_days": correlation["valid_days"][i][j], "value": value,
                              "definition": card(key, formula, value is not None,
                                                 None if value is not None else "no_valid_cross_sections")})
        overlap[key] = {"pairs": pairs}
    overlap["definitions"] = {
        key: card(key, formula, available, reason) for key, formula, available, reason in [
            ("value_correlation", "mean(daily cross-sectional Spearman); valid_days per pair", any(v is not None for row in correlation["matrix"] for v in row), None),
            ("collinearity", "diag(inverse(mean daily correlation matrix)); VIF>10 heuristic", overlap["collinearity"].get("available", False), overlap["collinearity"].get("reason")),
            ("ic_series_correlation", "Pearson of aligned daily Rank IC pairs; at least 5 shared dates; diagonal=1 is legacy identity convention", any(v is not None for i, row in enumerate(overlap["ic_series_correlation"].get("matrix", [])) for j, v in enumerate(row) if i != j), None),
            ("orthogonal_ic", "cross-sectional OLS residual Pearson IC; compare raw Spearman IC (legacy mixed-method diagnostic)", any(v.get("ic_mean") is not None and math.isfinite(v["ic_mean"]) for v in overlap["orthogonal_ic"].values()), None),
            ("combined_ic", "mean(daily Pearson(equal-weight zscored factors,forward return))", report["overlap"]["combined_ic"].get("ic_mean") is not None, None),
            ("incremental_ic", "combined IC minus leave-one-factor-out IC; valid samples may differ", any(v.get("delta") is not None for v in overlap["incremental_ic"] or []), None),
        ]}
    tested = sum(row["fdr_q"] is not None for row in report["factors"])
    params["tested_factor_count"] = tested
    for row in report["factors"]:
        row["definitions"]["fdr_q"]["parameters"]["tested_factor_count"] = tested
    report["schema_version"] = 2
    basis.update(input_refs=refs, parameters=params, significance="Bartlett HAC mean SE; covariance denominator N; no variance floor; normal two-sided p; BH on available primary Rank IC tests")
    report["limitations"] = ["探索性分析；显著性不能证明训练无泄漏或策略有效",
        "仅分析本次选中面板，未覆盖完整试验选择历史；来源性质未知时保持unknown",
        "价格使用已核验内容摘要的快照；复权/PIT/历史修订语义未认证，不证明无未来数据",
        "其余统计族保留既有估计量：换手可能跨缺口，正交增量混合相关方法，留一组合样本可能不同；定义卡披露这些限制",
        *[value for value in report["limitations"] if "未使用未来修订数据" not in value]]
    return report
