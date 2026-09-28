#!/usr/bin/env python3
"""Full factor-research slice on the csi500 snapshot.

Adds to the first slice: two-sided tradability, float market cap (size), PIT statistical
industry, size/industry neutralisation, Newey-West t, quantile spread, rank turnover and
BH-FDR across the tested hypotheses.

Contract: docs/spec/FACTOR_ANALYSIS.md §4, DATA_SOURCES.md §1A/§1B.
Read-only with respect to the snapshot; writes only the evidence file.

Usage:
  python3 scripts/run_factor_research.py --data-root ~/.qlib/qlib_data \
    --registry ~/.qlib/qlib_data/_registry --snapshot-id free_cn_20260924_processed_v1 \
    --start 2025-01-02 --end 2026-09-24 \
    --output docs/spec/evidence/20260927-factor-research.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extensions" / "workbench"))
from quant_workbench import data_directory as dd  # noqa: E402
from quant_workbench import factor_pipeline as fp  # noqa: E402
from quant_workbench import free_sources  # noqa: E402

FACTORS = ("momentum_20", "volatility_20", "turnover_20")
HORIZONS = (5, 10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--snapshot-id", default="free_cn_20260924_processed_v1")
    parser.add_argument("--enrichment", help="deprecated; must match the sealed status directory")
    parser.add_argument("--universe", default="csi500")
    parser.add_argument("--start", default="2025-01-02")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--industry-window", type=int, default=120)
    parser.add_argument("--industry-clusters", type=int, default=8)
    parser.add_argument("--stability-folds", type=int, default=6)
    parser.add_argument("--round-trip-cost", type=float, default=0.00092,
                        help="commission+stamp+transfer both ways (configs/cn: 9.2bp)")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    reader = dd.FreeSnapshotReader(args.data_root, dd.load_snapshot(args.registry, args.snapshot_id))
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    dates = [day for day in reader.calendar() if start <= day <= end]
    symbols, membership = fp.historical_membership(reader, dates, args.universe)
    if args.enrichment and (Path(args.enrichment).expanduser() / 'turnover').resolve() != reader.path('status').resolve():
        parser.error('--enrichment must refer to the sealed snapshot; omit this deprecated option')

    closes, returns, size, flags_by_symbol = {}, {}, {}, {}
    turns_by_symbol = {}
    for symbol in symbols:
        enrichment = reader.turnover(symbol)
        loaded = fp.load_symbol_series(reader, symbol, dates, enrichment)
        close, high, low, change = (loaded["close"], loaded["high"],
                                    loaded["low"], loaded["change"])
        volume, factor, turns = loaded["volume"], loaded["factor"], loaded["turn"]
        closes[symbol] = close
        turns_by_symbol[symbol] = turns
        size[symbol] = fp.log_float_cap(close, factor, volume, turns)
        flags_by_symbol[symbol] = fp.tradable({"high": high, "low": low, "change": change},
                                              dates, enrichment)
        returns[symbol] = [close[index] / close[index - 1] - 1.0
                           if index and math.isfinite(close[index]) and math.isfinite(close[index - 1])
                           and close[index - 1] > 0 else float("nan")
                           for index in range(len(close))]

    industry_by_date = fp.rolling_industry(returns, dates, window=args.industry_window,
                                           n_clusters=args.industry_clusters, step=21, membership=membership)
    industry_keys = sorted(industry_by_date)

    def industry_for(day: str) -> dict[str, int]:
        usable = [key for key in industry_keys if key <= day]
        return industry_by_date[usable[-1]] if usable else {}

    market_close = fp.aligned_series(reader, "SH000905", "close", dates)
    market_returns = [market_close[index] / market_close[index - 1] - 1.0
                      if index and math.isfinite(market_close[index])
                      and math.isfinite(market_close[index - 1]) and market_close[index - 1] > 0
                      else float("nan") for index in range(len(market_close))]
    beta_grid = fp.rolling_beta(returns, market_returns, window=args.industry_window, step=21)
    beta_keys = sorted(beta_grid)
    beta_by_date = {dates[index].isoformat(): beta_grid[index] for index in beta_keys}
    beta_keys_by_date = sorted(beta_by_date)

    def beta_for(day: str, index: int) -> dict[str, float]:
        usable = [key for key in beta_keys_by_date if key <= day]
        return beta_by_date[usable[-1]] if usable else {}

    def exposures_for(day: str, index: int) -> list[dict[str, float]]:
        size_row = {symbol: size[symbol][index] for symbol in closes}
        return [size_row, beta_for(day, index)]

    panels = {name: [dict() for _ in dates] for name in FACTORS}
    labels = {horizon: [dict() for _ in dates] for horizon in HORIZONS}
    for symbol in closes:
        close, turns = closes[symbol], turns_by_symbol[symbol]
        flags = flags_by_symbol[symbol]
        series = {"momentum_20": fp.momentum(close, 20),
                  "volatility_20": fp.volatility(close, 20),
                  "turnover_20": fp.mean_of(turns, 20)}
        for horizon in HORIZONS:
            tradable_label = fp.label_tradability(flags, horizon)
            raw_label = fp.forward_return(close, horizon)
            for index in range(len(dates)):
                if symbol in membership[index] and tradable_label[index] and math.isfinite(raw_label[index]):
                    labels[horizon][index][symbol] = raw_label[index]
        for name, values in series.items():
            for index in range(len(dates)):
                if symbol in membership[index] and flags[index] and math.isfinite(values[index]):
                    panels[name][index][symbol] = values[index]

    hypotheses, ic_series, spreads = {}, {}, {}
    for name in FACTORS:
        for horizon in HORIZONS:
            for variant in ("raw", "neutralized"):
                series, spread_values = [], []
                for index, day in enumerate(dates):
                    factor = dict(panels[name][index])
                    if variant == "neutralized":
                        factor = fp.neutralize(factor, exposures_for(day.isoformat(), index),
                                               industry_for(day.isoformat()))
                    series.append(fp.rank_ic(factor, labels[horizon][index]))
                    spread = fp.quantile_spread(factor, labels[horizon][index])
                    spread_values.append(spread['spread_top_bottom'] if spread else None)
                warmup = 20 if variant == 'raw' else ((args.industry_window + 20) // 21) * 21
                stat = fp.research_stats(series, horizon, warmup)
                key = f"{name}_h{horizon}_{variant}"
                ic_series[key] = series
                hypotheses[key] = {
                    "factor": name, "horizon": horizon, "variant": variant,
                    "days": stat['days'], 'expected_days': stat['expected_days'],
                    'warmup_days': warmup, 'immature_tail_days': horizon,
                    "mean_rank_ic": stat['ic_mean'], "std_rank_ic": stat['ic_std'],
                    "icir": stat['icir'], "nw_t": stat['t_stat'], "p_value": stat['p_value'],
                    "positive_share": stat['positive_ratio'],
                    'significance_available': stat['significance_available'],
                    'significance_reason': stat['significance_reason'],
                }
                eligible = fp.label_window(slice(0, len(dates)), horizon, warmup)
                valid_spreads = [v for v in spread_values[eligible] if v is not None]
                if valid_spreads:
                    spreads[key] = {'days': len(valid_spreads), 'mean_spread': statistics.fmean(valid_spreads)}

    turnover_stats = {}
    for name in FACTORS:
        per_day = []
        for index in range(1, len(dates)):
            value = fp.rank_turnover(panels[name][index - 1], panels[name][index])
            if value is not None:
                per_day.append(value)
        if per_day:
            turnover_stats[name] = {"days": len(per_day),
                                    "mean_rank_turnover": statistics.fmean(per_day)}

    round_trip_cost = args.round_trip_cost
    q_values = fp.benjamini_hochberg({key: item["p_value"] for key, item in hypotheses.items()
                                      if item["p_value"] is not None})
    for key, item in hypotheses.items():
        item["fdr_q"] = q_values.get(key)
        item["ic_series_digest"] = "sha256:" + hashlib.sha256(
            json.dumps([round(value, 8) if value is not None else None for value in ic_series[key]]).encode()).hexdigest()
        item["stability"] = fp.stability([v if v is not None else float('nan') for v in ic_series[key][fp.label_window(slice(0, len(dates)), item['horizon'], item['warmup_days'])]], folds=args.stability_folds)
        turnover = turnover_stats.get(item["factor"], {}).get("mean_rank_turnover")
        if turnover is not None:
            spread = spreads.get(key)
            if spread:
                item["cost_screen"] = fp.cost_threshold(
                    spread["mean_spread"], turnover, item["horizon"], round_trip_cost)

    fdr_survivors = [key for key, item in hypotheses.items()
                     if item.get("fdr_q") is not None and item["fdr_q"] <= 0.05]
    cost_survivors = [key for key, item in hypotheses.items()
                      if (item.get("cost_screen") or {}).get("passes")]
    evidence = {
        "summary": {
            "fdr_survivors": sorted(fdr_survivors),
            "cost_survivors": sorted(cost_survivors),
            "survives_both": sorted(set(fdr_survivors) & set(cost_survivors)),
            "interpretation": ("a hypothesis must pass FDR **and** cover round-trip cost to be "
                               "worth further work; the intersection here is the headline"),
        },
        "slice": "csi500_factor_research",
        "snapshot_id": reader.record["snapshot_id"],
        "snapshot_content_digest": reader.record["content_digest"],
        "window": {"start": args.start, "end": args.end, "trading_days": len(dates)},
        "universe": {"name": args.universe, "symbols": len(symbols)},
        "industry": {"kind": "statistical_industry_trailing_returns",
                     "window": args.industry_window, "clusters": args.industry_clusters,
                     "recluster_step_days": 21, "points": len(industry_keys),
                     "note": "clusters use past returns only; not a named industry classification"},
        "market_factor": {"symbol": "SH000905", "kind": "csi500_index_returns",
                          "beta_window": args.industry_window, "beta_step_days": 21,
                          "points": len(beta_grid)},
        "neutralization": {"exposures": ["log_float_cap", "market_beta", "industry_dummies"],
                           "method": "cross_sectional_ols_residual"},
        "label": {"horizons": list(HORIZONS), "basis": "adjusted close on snapshot calendar",
                  "whole_window_status_mask": True},
        "hypotheses": hypotheses,
        "quantile_spread_by_hypothesis": spreads,
        "factor_rank_turnover": turnover_stats,
        "families": {"hypotheses_tested": len(hypotheses), "fdr": "benjamini_hochberg"},
        "cost_model": {"round_trip_cost": round_trip_cost,
                       "basis": "configs/cn commission 2bp x2 + stamp 5bp sell + transfer 0.1bp x2",
                       "formula": "expected_cost = min(2, h*daily_rank_turnover) * round_trip_cost",
                       "kind": "screening only, not a backtest"},
        "limitations": [
            "free_community_unverified inputs; exploratory only, not alpha evidence",
            "industry is a statistical proxy, not a PIT named classification",
            "size uses derived float shares from turnover; corporate-action jumps remain",
            "size, market beta and statistical industry only; not a full risk model",
            "all flat bars excluded conservatively; not a legal limit or fill model",
        ],
        "paths_recorded": False,
    }
    if Path(args.output).exists():
        raise ValueError("output already exists; choose a new result version")
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    top = sorted(((k, v) for k, v in hypotheses.items() if v["mean_rank_ic"] is not None), key=lambda item: item[1]["mean_rank_ic"])
    print(json.dumps({"hypotheses": len(hypotheses),
                      "most_negative": {top[0][0]: round(top[0][1]["mean_rank_ic"], 4)} if top else None,
                      "most_positive": {top[-1][0]: round(top[-1][1]["mean_rank_ic"], 4)} if top else None,
                      "fdr_survivors": sum(1 for item in hypotheses.values()
                                           if item.get("fdr_q") is not None and item["fdr_q"] <= 0.05)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
