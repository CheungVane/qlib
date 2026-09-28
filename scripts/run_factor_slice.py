#!/usr/bin/env python3
"""First factor slice on the csi500 snapshot: labels, tradability, factors, Rank IC.

Contract: docs/spec/FACTOR_ANALYSIS.md §3.3/§4.1 and DATA_SOURCES.md §1A.
Read-only with respect to the snapshot; writes only the evidence file.

Usage:
  python3 scripts/run_factor_slice.py --data-root ~/.qlib/qlib_data \
    --registry ~/.qlib/qlib_data/_registry --snapshot-id free_cn_20260924_processed_v1 \
    --start 2025-01-02 --end 2026-09-24 --horizon 5 \
    --output docs/spec/evidence/20260927-factor-slice.json
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--snapshot-id", default="free_cn_20260924_processed_v1")
    parser.add_argument("--enrichment", help="deprecated; must match the sealed status directory")
    parser.add_argument("--universe", default="csi500")
    parser.add_argument("--start", default="2025-01-02")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    reader = dd.FreeSnapshotReader(args.data_root, dd.load_snapshot(args.registry, args.snapshot_id))
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    dates = [day for day in reader.calendar() if start <= day <= end]
    symbols, membership = fp.historical_membership(reader, dates, args.universe)
    if args.enrichment and (Path(args.enrichment).expanduser() / 'turnover').resolve() != reader.path('status').resolve():
        parser.error('--enrichment must refer to the sealed snapshot; omit this deprecated option')

    factors = {name: [] for name in ("momentum_20", "volatility_20", "turnover_20")}
    labels_by_day: list[dict[str, float]] = [dict() for _ in dates]
    factor_by_day: dict[str, list[dict[str, float]]] = {name: [dict() for _ in dates] for name in factors}
    stats = {"symbols": 0, "missing_turnover": 0, "tradable_rows": 0, "filtered_rows": 0}

    for symbol in symbols:
        closes = fp.aligned_series(reader, symbol, "close", dates)
        high = fp.aligned_series(reader, symbol, "high", dates)
        low = fp.aligned_series(reader, symbol, "low", dates)
        change = fp.aligned_series(reader, symbol, "change", dates)
        enrichment = reader.turnover(symbol)
        turns = [enrichment.get(day.isoformat(), {}).get("turn") if enrichment.get(day.isoformat(), {}).get("turn") is not None else float("nan") for day in dates]
        flags = fp.tradable({"high": high, "low": low, "change": change}, dates, enrichment)
        labels = fp.forward_return(closes, args.horizon)
        label_mask = fp.label_tradability(flags, args.horizon)
        series = {"momentum_20": fp.momentum(closes, 20),
                  "volatility_20": fp.volatility(closes, 20),
                  "turnover_20": fp.mean_of(turns, 20)}
        stats["symbols"] += 1
        for index, day in enumerate(dates):
            if symbol not in membership[index]:
                continue
            if not flags[index]:
                stats["filtered_rows"] += 1
                continue
            stats["tradable_rows"] += 1
            if label_mask[index] and math.isfinite(labels[index]):
                labels_by_day[index][symbol] = labels[index]
            for name, values in series.items():
                if math.isfinite(values[index]):
                    factor_by_day[name][index][symbol] = values[index]

    summary = {}
    for name in factors:
        indices = range(20, max(20, len(dates) - args.horizon))
        axis = [{'date': dates[index].isoformat(),
                 'ic': fp.rank_ic(factor_by_day[name][index], labels_by_day[index])}
                for index in indices]
        daily = [row['ic'] for row in axis if row['ic'] is not None]
        payload = json.dumps(axis, sort_keys=True).encode()
        summary[name] = {
            "days": len(daily), "expected_days": len(axis), "warmup_days": 20,
            "missing_ic_days": len(axis) - len(daily), "immature_tail_days": args.horizon,
            "mean_rank_ic": statistics.fmean(daily) if daily else None,
            "std_rank_ic": statistics.stdev(daily) if len(daily) > 1 else None,
            "positive_share": (sum(1 for value in daily if value > 0) / len(daily)) if daily else None,
            "ic_series_digest": "sha256:" + hashlib.sha256(payload).hexdigest(),
        }

    evidence = {
        "slice": "csi500_factor_pipeline_first",
        "snapshot_id": reader.record["snapshot_id"],
        "snapshot_content_digest": reader.record["content_digest"],
        "window": {"start": args.start, "end": args.end, "trading_days": len(dates)},
        "universe": {"name": args.universe, "symbols": len(symbols)},
        "label": {"kind": "forward_return", "horizon": args.horizon,
                  "basis": "adjusted close on the snapshot calendar",
                  "note": "last h rows have no label; full window requires observed positive prices, trading status and non-ST"},
        "tradability": {"rule": "tradestatus==1, non-ST, positive high/low and non-flat bar",
                        "excluded_st": True, **stats},
        "factors": summary,
        "limitations": [
            "free_community_unverified sources; exploratory only",
            "all flat bars excluded conservatively; not a legal limit or fill model",
            "entry through exit observations are required; this is not an execution simulation",
            "factor values are raw; no industry/size neutralisation yet",
        ],
        "paths_recorded": False,
    }
    if Path(args.output).exists():
        raise ValueError("output already exists; choose a new result version")
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({name: {"days": item["days"], "mean_rank_ic": item["mean_rank_ic"]}
                      for name, item in summary.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
