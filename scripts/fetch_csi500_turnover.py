#!/usr/bin/env python3
"""Fetch daily turnover and trading status for a universe from BaoStock.

Why: the FINV archive ships adjusted OHLCV only (no turnover/shares), and daily float
market cap needs turnover. This script caches the gap-filling fields outside the snapshot.

**Pacing is mandatory, not tunable.** BaoStock is a free community source that blacklists
by public IP when it sees concurrency: the 2026-09-27 full fetch used 6 processes and got
this host blacklisted (`10001011`). The upstream docs publish no policy or unblock time, and
community reports show the trigger is concurrency and that recovery needs a new IP or days
of waiting. Therefore this script:

* walks the universe **one symbol at a time in a single process** — there is no worker or
  thread option, by design;
* **sleeps between symbols** (``--sleep``, default 0.5s, values below the floor are refused
  before any network call);
* stops immediately if the source reports the blacklist instead of retrying in a loop.

Contract: docs/spec/DATA_SOURCES.md (free source rules + the 2026-09-27 incident).
BaoStock is `free_community_unverified`: record it in provenance, never call it official.

Output: <out>/turnover/<SYMBOL>.csv with header `date,turn,tradestatus,isST`, plus
<out>/unsupported_symbols.json for symbols BaoStock does not serve (e.g. Beijing).
Resumable: existing per-symbol files are skipped.

Usage:
  python3 scripts/fetch_csi500_turnover.py \
    --instruments ~/.qlib/qlib_data/free_cn_20260924/instruments/csi500.txt \
    --out ~/.qlib/qlib_data/free_cn_20260924_enrichment \
    --start 2015-01-01 --end 2026-09-30 [--sleep 0.5] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

MIN_SLEEP_SECONDS = 0.5
BLACKLIST_CODES = {"10001011"}


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


def validate_pacing(sleep: float) -> float:
    """Refuse to run without a real pause: concurrency/pacing is what triggers blacklisting."""
    if isinstance(sleep, bool) or not isinstance(sleep, (int, float)):
        raise ValueError("--sleep must be a number")
    if float(sleep) < MIN_SLEEP_SECONDS:
        raise ValueError(f"--sleep must be >= {MIN_SLEEP_SECONDS} seconds; BaoStock blacklists "
                         "by IP when requests are issued without a pause")
    return float(sleep)


def is_blacklist(error_code: str, error_message: str) -> bool:
    return str(error_code) in BLACKLIST_CODES or "黑名单" in str(error_message)


def _write_symbol(bs, symbol: str, code: str, start: str, end: str, directory: Path) -> tuple[str, str]:
    """One sequential query; the caller owns pacing and blacklist handling."""
    target = directory / f"{symbol}.csv"
    if target.exists() and target.stat().st_size > 0:
        return symbol, "skipped"
    result = bs.query_history_k_data_plus(
        code, "date,turn,tradestatus,isST", start_date=start, end_date=end,
        frequency="d", adjustflag="3")
    if is_blacklist(result.error_code, result.error_msg):
        return symbol, f"blacklisted:{result.error_code}:{result.error_msg}"
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
    parser.add_argument("--sleep", type=float, default=MIN_SLEEP_SECONDS,
                        help=f"seconds between symbols; must be >= {MIN_SLEEP_SECONDS}")
    parser.add_argument("--limit", type=int, default=0, help="0 means all")
    args = parser.parse_args()

    try:
        pause = validate_pacing(args.sleep)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    try:
        import baostock
    except ImportError:
        print("baostock is required: pip install baostock", file=sys.stderr)
        return 2

    preflight = baostock.login()
    if preflight.error_code != "0":
        print(f"baostock refused the connection: {preflight.error_code} {preflight.error_msg}\n"
              "the free source is unavailable (rate limiting or IP blacklisting); the cached "
              "turnover files remain usable. Recovery needs a changed public IP or waiting; "
              "see docs/spec/DATA_SOURCES.md", file=sys.stderr)
        return 3

    universe = load_universe(Path(args.instruments).expanduser())
    if args.limit:
        universe = universe[: args.limit]
    out_dir = Path(args.out).expanduser()
    turnover_dir = out_dir / "turnover"
    turnover_dir.mkdir(parents=True, exist_ok=True)

    pending, unsupported = [], []
    for symbol in universe:
        code = archive_symbol_to_baostock(symbol)
        (unsupported if code is None else pending).append((symbol, code))

    (out_dir / "unsupported_symbols.json").write_text(
        json.dumps({"reason": "baostock does not serve this exchange",
                    "symbols": [symbol for symbol, _ in unsupported]},
                   ensure_ascii=False, indent=2) + "\n")

    done = errors = 0
    try:
        for index, (symbol, code) in enumerate(pending, start=1):
            symbol_name, status = _write_symbol(baostock, symbol, code, args.start, args.end,
                                                turnover_dir)
            done += 1
            if status.startswith("blacklisted"):
                print(f"[stop] {symbol_name}: {status}\n"
                      f"paused after {done} symbols; already-written files are kept. "
                      "Do not retry in a loop — see docs/spec/DATA_SOURCES.md", file=sys.stderr)
                return 3
            if not status.startswith(("ok", "skipped")):
                errors += 1
                print(f"[warn] {symbol_name}: {status}", file=sys.stderr)
            if index % 25 == 0 or index == len(pending):
                print(f"[progress] {index}/{len(pending)} symbols, errors={errors}", flush=True)
            if not status.startswith("skipped"):
                # Pacing protects the source, so it only applies where we actually queried it.
                time.sleep(pause)
    finally:
        baostock.logout()

    print(json.dumps({"symbols": len(universe), "fetched_or_skipped": done, "errors": errors,
                      "unsupported": len(unsupported), "sleep_seconds": pause,
                      "out_dir": str(out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
