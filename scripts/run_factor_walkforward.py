#!/usr/bin/env python3
"""Walk-forward factor evaluation: select on a train window, score on the next block.

The discipline this enforces: a factor may only be selected with information available
before the block it is evaluated on. Selection = FDR q<=alpha **and** cost-screen pass,
both computed on the train window only.

Contract: docs/spec/FACTOR_ANALYSIS.md §4, DATA_SOURCES.md §1A/§1B.
Read-only with respect to the snapshot; writes only the evidence file.

Usage:
  python3 scripts/run_factor_walkforward.py --data-root ~/.qlib/qlib_data \
    --registry ~/.qlib/qlib_data/_registry --snapshot-id free_cn_20260924 \
    --enrichment ~/.qlib/qlib_data/free_cn_20260924_enrichment \
    --start 2025-01-02 --end 2026-09-24 --folds 4 --min-train 120 \
    --output docs/spec/evidence/20260927-factor-walkforward.json
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
VARIANTS = ("raw", "neutralized")


def finite_mean(values) -> float | None:
    usable = [value for value in values if value is not None and math.isfinite(value)]
    return statistics.fmean(usable) if usable else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--snapshot-id", default="free_cn_20260924")
    parser.add_argument("--enrichment", required=True)
    parser.add_argument("--universe", default="csi500")
    parser.add_argument("--start", default="2025-01-02")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--min-train", type=int, default=120)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--round-trip-cost", type=float, default=0.00092)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    reader = dd.FreeSnapshotReader(args.data_root, dd.load_snapshot(args.registry, args.snapshot_id))
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    dates = [day for day in reader.calendar() if start <= day <= end]
    symbols = reader.universe_on(end, args.universe)
    turnover_dir = Path(args.enrichment).expanduser() / "turnover"

    closes, returns, size, flags_by_symbol, turns_by_symbol = {}, {}, {}, {}, {}
    for symbol in symbols:
        cache = turnover_dir / f"{symbol}.csv"
        if not cache.exists():
            continue
        enrichment = free_sources.load_turnover_csv(cache)
        loaded = fp.load_symbol_series(reader, symbol, dates, enrichment)
        closes[symbol] = loaded["close"]
        turns_by_symbol[symbol] = loaded["turn"]
        size[symbol] = fp.log_float_cap(loaded["close"], loaded["factor"],
                                       loaded["volume"], loaded["turn"])
        flags_by_symbol[symbol] = fp.tradable(
            {"high": loaded["high"], "low": loaded["low"], "change": loaded["change"]},
            dates, enrichment)
        returns[symbol] = [loaded["close"][index] / loaded["close"][index - 1] - 1.0
                           if index and math.isfinite(loaded["close"][index])
                           and math.isfinite(loaded["close"][index - 1])
                           and loaded["close"][index - 1] > 0 else float("nan")
                           for index in range(len(loaded["close"]))]

    market_close = fp.aligned_series(reader, "SH000905", "close", dates)
    market_returns = [market_close[index] / market_close[index - 1] - 1.0
                      if index and math.isfinite(market_close[index])
                      and math.isfinite(market_close[index - 1]) and market_close[index - 1] > 0
                      else float("nan") for index in range(len(market_close))]
    industry_grid = fp.rolling_industry(returns, dates, window=120, n_clusters=8, step=21)
    industry_keys = sorted(industry_grid)
    beta_grid = fp.rolling_beta(returns, market_returns, window=120, step=21)
    beta_keys = {dates[index].isoformat(): grid for index, grid in beta_grid.items()}
    beta_key_list = sorted(beta_keys)

    def latest(mapping_keys, mapping, day):
        usable = [key for key in mapping_keys if key <= day]
        return mapping[usable[-1]] if usable else {}

    raw_panels = {name: [dict() for _ in dates] for name in FACTORS}
    neutral_panels = {name: [dict() for _ in dates] for name in FACTORS}
    labels = {horizon: [dict() for _ in dates] for horizon in HORIZONS}
    for symbol in closes:
        close, turns, flags = closes[symbol], turns_by_symbol[symbol], flags_by_symbol[symbol]
        series = {"momentum_20": fp.momentum(close, 20),
                  "volatility_20": fp.volatility(close, 20),
                  "turnover_20": fp.mean_of(turns, 20)}
        for horizon in HORIZONS:
            mask = fp.label_tradability(flags, horizon)
            raw = fp.forward_return(close, horizon)
            for index in range(len(dates)):
                if mask[index] and math.isfinite(raw[index]):
                    labels[horizon][index][symbol] = raw[index]
        for name, values in series.items():
            for index in range(len(dates)):
                if flags[index] and math.isfinite(values[index]):
                    raw_panels[name][index][symbol] = values[index]

    for index, day in enumerate(dates):
        exposure = {symbol: size[symbol][index] for symbol in closes}
        beta_row = latest(beta_key_list, beta_keys, day.isoformat())
        industry_row = latest(industry_keys, industry_grid, day.isoformat())
        for name in FACTORS:
            neutral_panels[name][index] = fp.neutralize(
                raw_panels[name][index], [exposure, beta_row], industry_row)

    ic_series, spread_series = {}, {}
    for name in FACTORS:
        for horizon in HORIZONS:
            for variant in VARIANTS:
                panels = raw_panels if variant == "raw" else neutral_panels
                key = f"{name}_h{horizon}_{variant}"
                ic_series[key] = [fp.rank_ic(panels[name][index], labels[horizon][index])
                                  for index in range(len(dates))]
                spread_series[key] = []
                for index in range(len(dates)):
                    spread = fp.quantile_spread(panels[name][index], labels[horizon][index])
                    spread_series[key].append(spread["spread_top_bottom"] if spread else None)
    turnover_series = {}
    for name in FACTORS:
        turnover_series[name] = [fp.rank_turnover(raw_panels[name][index - 1],
                                                  raw_panels[name][index]) if index else None
                                 for index in range(len(dates))]

    windows = fp.walk_forward_windows(len(dates), folds=args.folds, min_train=args.min_train)
    if not windows:
        print("window too short for the requested folds/min-train", file=sys.stderr)
        return 2

    folds = []
    for number, (train, test) in enumerate(windows, start=1):
        train_keys = [key for key in ic_series
                      if len([v for v in ic_series[key][train] if v is not None]) >= 20]
        p_values = {}
        for key in train_keys:
            values = [v for v in ic_series[key][train] if v is not None]
            horizon = int(key.split("_h")[1].split("_")[0])
            t_stat = fp.newey_west_t(values, lags=horizon - 1)
            probability = fp.normal_two_sided_p(t_stat)
            if probability is not None:
                p_values[key] = probability
        q_values = fp.benjamini_hochberg(p_values)
        selected = []
        for key in sorted(p_values):
            name = key.split("_h")[0]
            horizon = int(key.split("_h")[1].split("_")[0])
            spread = finite_mean(spread_series[key][train])
            turnover = finite_mean(turnover_series[name][train])
            if spread is None or turnover is None:
                continue
            screen = fp.cost_threshold(spread, turnover, horizon, args.round_trip_cost)
            if q_values.get(key, 1.0) <= args.alpha and screen["passes"]:
                selected.append(key)
        fold = {
            "fold": number,
            "train": {"start": dates[train.start].isoformat(), "end": dates[train.stop - 1].isoformat(),
                      "days": train.stop - train.start},
            "test": {"start": dates[test.start].isoformat(), "end": dates[test.stop - 1].isoformat(),
                     "days": test.stop - test.start},
            "selected": selected,
            "test_ic_by_selected": {key: finite_mean(ic_series[key][test]) for key in selected},
            "test_ic_mean_of_selected": finite_mean(
                [finite_mean(ic_series[key][test]) for key in selected]) if selected else None,
            "train_ic_mean_of_selected": finite_mean(
                [finite_mean(ic_series[key][train]) for key in selected]) if selected else None,
        }
        folds.append(fold)

    realised = [fold["test_ic_mean_of_selected"] for fold in folds
                if fold["test_ic_mean_of_selected"] is not None]
    kept_sign = [fold for fold in folds
                 if fold["test_ic_mean_of_selected"] is not None
                 and fold["train_ic_mean_of_selected"] is not None
                 and (fold["test_ic_mean_of_selected"] > 0)
                 == (fold["train_ic_mean_of_selected"] > 0)]
    evidence = {
        "slice": "csi500_factor_walkforward",
        "snapshot_id": reader.record["snapshot_id"],
        "snapshot_content_digest": reader.record["content_digest"],
        "window": {"start": args.start, "end": args.end, "trading_days": len(dates)},
        "design": {"kind": "expanding_window_walk_forward", "folds": args.folds,
                   "min_train_days": args.min_train, "alpha": args.alpha,
                   "round_trip_cost": args.round_trip_cost,
                   "selection": "train-window FDR q<=alpha AND train-window cost-screen pass",
                   "evaluation": "mean Rank IC of the selected set on the following block only"},
        "folds": folds,
        "summary": {
            "folds_with_selection": sum(1 for fold in folds if fold["selected"]),
            "folds_total": len(folds),
            "realised_test_ic_mean": statistics.fmean(realised) if realised else None,
            "realised_test_ic_digest": "sha256:" + hashlib.sha256(
                json.dumps([round(value, 8) for value in realised]).encode()).hexdigest(),
            "sign_kept_share": (len(kept_sign) / len(realised)) if realised else None,
        },
        "limitations": [
            "free_community_unverified inputs; exploratory only, not alpha evidence",
            "expanding window means later folds train on data that overlaps earlier tests "
            "(standard walk-forward, but not a purged/embargoed protocol)",
            "no portfolio construction, no impact/liquidity cost, no execution model",
            "industry is a statistical proxy and size is derived from turnover",
        ],
        "paths_recorded": False,
    }
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"folds": len(folds),
                      "selected_per_fold": [len(fold["selected"]) for fold in folds],
                      "realised_test_ic_mean": evidence["summary"]["realised_test_ic_mean"],
                      "sign_kept_share": evidence["summary"]["sign_kept_share"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
