#!/usr/bin/env python3
"""Fetch daily turnover and trading status for a universe from BaoStock.

Why: the FINV archive ships adjusted OHLCV only (no turnover/shares), and daily float
market cap needs turnover. This script caches the gap-filling fields outside the snapshot.

Contract: docs/spec/DATA_SOURCES.md §1B. BaoStock is `free_community_unverified`:
record it in provenance, never present it as official.

Output: <out>/turnover/<SYMBOL>.csv with header `date,turn,tradestatus,isST`, plus
<out>/unsupported_symbols.json for symbols BaoStock does not serve (e.g. Beijing).
Resumable: existing per-symbol files are skipped.

Usage:
  python3 scripts/fetch_csi500_turnover.py \
    --instruments ~/.qlib/qlib_data/free_cn_20260924/instruments/csi500.txt \
    --out ~/.qlib/qlib_data/free_cn_20260924_enrichment \
    --start 2015-01-01 --end 2026-09-30 --workers 4 [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

_STATE: dict = {}


def archive_symbol_to_baostock(symbol: str) -> str | None:
    """SH600000 -> sh.600000. Returns None for exchanges BaoStock does not serve."""
    if len(symbol) < 3:
        return None
    exchange, code = symbol[:2], symbol[2:]
    if exchange == "SH":
        return f"sh.{code}"
    if exchange == "SZ":
        return f"sz.{code}"
    return None


def load_universe(path: Path) -> list[str]:
    symbols = []
    for line in path.read_text().splitlines():
        if line.strip():
            symbols.append(line.split()[0])
    return sorted(set(symbols))


def _init_worker() -> None:
    import baostock as bs
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"baostock login failed: {login.error_msg}")
    _STATE["bs"] = bs


def _fetch_symbol(task: tuple[str, str, str, str, str]) -> tuple[str, str]:
    symbol, code, start, end, directory = task
    bs = _STATE["bs"]
    target = Path(directory) / f"{symbol}.csv"
    if target.exists() and target.stat().st_size > 0:
        return symbol, "skipped"
    result = bs.query_history_k_data_plus(
        code, "date,turn,tradestatus,isST", start_date=start, end_date=end,
        frequency="d", adjustflag="3")
    if result.error_code != "0":
        return symbol, f"error:{result.error_code}:{result.error_msg}"
    rows = []
    while result.next():
        rows.append(result.get_row_data())
    if not rows:
        return symbol, "empty"
    tmp = target.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write("date,turn,tradestatus,isST\n")
        for row in rows:
            handle.write(",".join(row) + "\n")
    os.replace(tmp, target)
    return symbol, f"ok:{len(rows)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instruments", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-09-30")
    parser.add_argument("--workers", type=int, default=2,
                        help="keep this low: heavy concurrency got this IP blacklisted once")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="seconds to sleep between submissions (be a considerate client)")
    parser.add_argument("--limit", type=int, default=0, help="0 means all")
    args = parser.parse_args()

    try:
        import baostock
    except ImportError:
        print("baostock is required: pip install baostock", file=sys.stderr)
        return 2

    preflight = baostock.login()
    if preflight.error_code != "0":
        print(f"baostock refused the connection: {preflight.error_code} {preflight.error_msg}\n"
              "the free source is unavailable (rate limiting or blacklisting); the cached "
              "turnover files remain usable, retry later with lower --workers",
              file=sys.stderr)
        return 3
    baostock.logout()

    universe = load_universe(Path(args.instruments).expanduser())
    if args.limit:
        universe = universe[: args.limit]
    out_dir = Path(args.out).expanduser()
    turnover_dir = out_dir / "turnover"
    turnover_dir.mkdir(parents=True, exist_ok=True)

    tasks, unsupported = [], []
    for symbol in universe:
        code = archive_symbol_to_baostock(symbol)
        if code is None:
            unsupported.append(symbol)
        else:
            tasks.append((symbol, code, args.start, args.end, str(turnover_dir)))

    (out_dir / "unsupported_symbols.json").write_text(
        json.dumps({"reason": "baostock does not serve this exchange",
                    "symbols": unsupported}, ensure_ascii=False, indent=2) + "\n")

    done = errors = 0
    try:
        with ProcessPoolExecutor(max_workers=max(1, args.workers), initializer=_init_worker) as pool:
            futures = {}
            for task in tasks:
                futures[pool.submit(_fetch_symbol, task)] = task[0]
                if args.sleep:
                    time.sleep(args.sleep)
            for future in as_completed(futures):
                symbol, status = future.result()
                done += 1
                if not status.startswith(("ok", "skipped")):
                    errors += 1
                    print(f"[warn] {symbol}: {status}", file=sys.stderr)
                if done % 25 == 0 or done == len(tasks):
                    print(f"[progress] {done}/{len(tasks)} symbols, errors={errors}", flush=True)
    except BrokenProcessPool:
        print(f"worker pool died after {done} symbols (likely a refused login); "
              "already-written files are kept, rerun later", file=sys.stderr)
        return 3

    print(json.dumps({"symbols": len(universe), "fetched_or_skipped": done,
                      "errors": errors, "unsupported": len(unsupported),
                      "out_dir": str(out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
