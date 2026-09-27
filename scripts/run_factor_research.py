#!/usr/bin/env python3
"""Full factor-research slice on the csi500 snapshot.

Adds to the first slice: two-sided tradability, float market cap (size), PIT statistical
industry, size/industry neutralisation, Newey-West t, quantile spread, rank turnover and
BH-FDR across the tested hypotheses.

Contract: docs/spec/FACTOR_ANALYSIS.md §4, DATA_SOURCES.md §1A/§1B.
Read-only with respect to the snapshot; writes only the evidence file.

Usage:
  python3 scripts/run_factor_research.py --data-root ~/.qlib/qlib_data \
    --registry ~/.qlib/qlib_data/_registry --snapshot-id free_cn_20260924 \
    --enrichment ~/.qlib/qlib_data/free_cn_20260924_enrichment \
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
    parser.add_argument("--snapshot-id", default="free_cn_20260924")
    parser.add_argument("--enrichment", required=True)
    parser.add_argument("--universe", default="csi500")
    parser.add_argument("--start", default="2025-01-02")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--industry-window", type=int, default=120)
    parser.add_argument("--industry-clusters", type=int, default=8)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    reader = dd.FreeSnapshotReader(args.data_root, dd.load_snapshot(args.registry, args.snapshot_id))
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    dates = [day for day in reader.calendar() if start <= day <= end]
    symbols = reader.universe_on(end, args.universe)
    turnover_dir = Path(args.enrichment).expanduser() / "turnover"

    closes, returns, size, flags_by_symbol = {}, {}, {}, {}
    turns_by_symbol = {}
    for symbol in symbols:
        cache = turnover_dir / f"{symbol}.csv"
        if not cache.exists():
            continue
        enrichment = free_sources.load_turnover_csv(cache)
        close = fp.aligned_series(reader, symbol, "close", dates)
        high = fp.aligned_series(reader, symbol, "high", dates)
        low = fp.aligned_series(reader, symbol, "low", dates)
        change = fp.aligned_series(reader, symbol, "change", dates)
        volume = fp.aligned_series(reader, symbol, "volume", dates)
        factor = fp.aligned_series(reader, symbol, "factor", dates)
        turns = [enrichment.get(day.isoformat(), {}).get("turn") or float("nan") for day in dates]
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
                                           n_clusters=args.industry_clusters, step=21)
    industry_keys = sorted(industry_by_date)

    def industry_for(day: str) -> dict[str, int]:
        usable = [key for key in industry_keys if key <= day]
        return industry_by_date[usable[-1]] if usable else {}

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
                if tradable_label[index] and math.isfinite(raw_label[index]):
                    labels[horizon][index][symbol] = raw_label[index]
        for name, values in series.items():
            for index in range(len(dates)):
                if flags[index] and math.isfinite(values[index]):
                    panels[name][index][symbol] = values[index]

    hypotheses, ic_series = {}, {}
    for name in FACTORS:
        for horizon in HORIZONS:
            for variant in ("raw", "neutralized"):
                series = []
                for index, day in enumerate(dates):
                    factor = dict(panels[name][index])
                    if variant == "neutralized":
                        factor = fp.neutralize(factor, {key: size[key][index] for key in closes},
                                               industry_for(day.isoformat()))
                    value = fp.rank_ic(factor, labels[horizon][index])
                    if value is not None:
                        series.append(value)
                if len(series) < 10:
                    continue
                t_stat = fp.newey_west_t(series, lags=horizon - 1)
                key = f"{name}_h{horizon}_{variant}"
                ic_series[key] = series
                hypotheses[key] = {
                    "factor": name, "horizon": horizon, "variant": variant,
                    "days": len(series),
                    "mean_rank_ic": statistics.fmean(series),
                    "std_rank_ic": statistics.stdev(series) if len(series) > 1 else None,
                    "icir": (statistics.fmean(series) / statistics.stdev(series)
                             if len(series) > 1 and statistics.stdev(series) > 0 else None),
                    "nw_t": t_stat,
                    "p_value": fp.normal_two_sided_p(t_stat),
                    "positive_share": sum(1 for value in series if value > 0) / len(series),
                }

    q_values = fp.benjamini_hochberg({key: item["p_value"] for key, item in hypotheses.items()
                                      if item["p_value"] is not None})
    for key, item in hypotheses.items():
        item["fdr_q"] = q_values.get(key)
        item["ic_series_digest"] = "sha256:" + hashlib.sha256(
            json.dumps([round(value, 8) for value in ic_series[key]]).encode()).hexdigest()

    spreads = {}
    for name in FACTORS:
        for variant in ("raw", "neutralized"):
            values = []
            for index, day in enumerate(dates):
                factor = dict(panels[name][index])
                if variant == "neutralized":
                    factor = fp.neutralize(factor, {key: size[key][index] for key in closes},
                                           industry_for(day.isoformat()))
                spread = fp.quantile_spread(factor, labels[5][index])
                if spread is not None:
                    values.append(spread["spread_top_bottom"])
            if values:
                spreads[f"{name}_{variant}"] = {"days": len(values),
                                                "mean_spread": statistics.fmean(values)}

    turnover_stats = {}
    for name in FACTORS:
        per_day = []
        for index in range(1, len(dates)):
            value = fp.rank_turnover(panels[name][index - 1], panels[name][index])
            if value is not None:
                per_day.append(value)
        if per_day:
            turnover_stats[name] = {"days": len(per_day), "mean_rank_turnover": statistics.fmean(per_day)}

    evidence = {
        "slice": "csi500_factor_research",
        "snapshot_id": reader.record["snapshot_id"],
        "snapshot_content_digest": reader.record["content_digest"],
        "window": {"start": args.start, "end": args.end, "trading_days": len(dates)},
        "universe": {"name": args.universe, "symbols": len(symbols)},
        "industry": {"kind": "statistical_industry_trailing_returns",
                     "window": args.industry_window, "clusters": args.industry_clusters,
                     "recluster_step_days": 21, "points": len(industry_keys),
                     "note": "clusters use past returns only; not a named industry classification"},
        "label": {"horizons": list(HORIZONS), "basis": "adjusted close on snapshot calendar",
                  "two_sided_tradability": True},
        "hypotheses": hypotheses,
        "quantile_spread_h5": spreads,
        "factor_rank_turnover": turnover_stats,
        "families": {"hypotheses_tested": len(hypotheses), "fdr": "benjamini_hochberg"},
        "limitations": [
            "free_community_unverified inputs; exploratory only, not alpha evidence",
            "industry is a statistical proxy, not a PIT named classification",
            "size uses derived float shares from turnover; corporate-action jumps remain",
            "no risk-model (beta/风格) neutralisation beyond size and industry",
            "one-word limit detection is approximate",
        ],
        "paths_recorded": False,
    }
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    top = sorted(hypotheses.items(), key=lambda item: item[1]["mean_rank_ic"])
    print(json.dumps({"hypotheses": len(hypotheses),
                      "most_negative": {top[0][0]: round(top[0][1]["mean_rank_ic"], 4)},
                      "most_positive": {top[-1][0]: round(top[-1][1]["mean_rank_ic"], 4)},
                      "fdr_survivors": sum(1 for item in hypotheses.values()
                                           if (item.get("fdr_q") or 1) <= 0.05)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
