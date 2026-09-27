#!/usr/bin/env python3
"""Register and verify an extracted free-source snapshot (docs/spec/DATA_SOURCES.md).

Read-only: verifies archive/manifest identity, calendar semantics, instrument coverage
and feature fields, then writes a snapshot record. It never modifies the snapshot and
never claims the free source is official.

Usage:
    python3 scripts/verify_free_snapshot.py --snapshot ~/.qlib/qlib_data/free_cn_20260924 \
        --manifest ~/.qlib/qlib_data/_downloads/2026-09-27/qlib_bin.manifest.json \
        --archive  ~/.qlib/qlib_data/_downloads/2026-09-27/qlib_bin.tar.gz \
        --output docs/spec/evidence/20260927-free-snapshot.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SOURCE_CLASS = "free_community_unverified"
REQUIRED_MEMBERS = ("calendars/day.txt", "calendars/day_future.txt", "instruments/all.txt",
                    "instruments/csi300.txt", "instruments/csi500.txt",
                    "instruments/csi800.txt", "instruments/csi1000.txt", "instruments/csiall.txt")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def load_instruments(path: Path) -> list[tuple[str, str, str]]:
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            symbol, start, end = line.split()
            rows.append((symbol, start, end))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--archive")
    parser.add_argument("--enrichment", help="turnover cache directory written by fetch_csi500_turnover.py")
    parser.add_argument("--universe", default="csi500", help="universe file used to scope the enrichment")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    snapshot, manifest_path = Path(args.snapshot).expanduser(), Path(args.manifest).expanduser()
    manifest = json.loads(manifest_path.read_text())
    record = {
        "snapshot_kind": "free_source_qlib_bin",
        "source_class": SOURCE_CLASS,
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot_label": snapshot.name,
        "paths_recorded": False,
        "manifest": {key: manifest.get(key) for key in
                     ("release_tag", "target_trade_date", "future_start_date", "future_end_date",
                      "dolt_commit", "investment_data_commit", "qlib_commit",
                      "archive_size_bytes", "archive_sha256")},
        "manifest_sha256": sha256_file(manifest_path),
        "limitations": [
            "free community source; not official; do not present as certified market data",
            "prices are adjusted: raw = adjusted / factor; archive volume is inversely adjusted",
            "amount unit is thousand CNY",
            "absolute paths and machine names are deliberately not recorded",
        ],
    }

    if args.archive:
        archive = Path(args.archive).expanduser()
        actual = sha256_file(archive)
        record["archive_sha256_actual"] = actual
        record["archive_sha256_matches_manifest"] = (
            actual == (manifest.get("archive_sha256") or "").removeprefix("sha256:"))
        record["archive_bytes_actual"] = archive.stat().st_size

    missing = [member for member in REQUIRED_MEMBERS if not (snapshot / member).exists()]
    record["missing_members"] = missing

    calendar = (snapshot / "calendars/day.txt").read_text().split()
    record["calendar"] = {"first": calendar[0], "last": calendar[-1], "days": len(calendar),
                          "matches_target_trade_date": calendar[-1] == manifest.get("target_trade_date")}

    rows = load_instruments(snapshot / "instruments/all.txt")
    by_exchange = Counter(symbol[:2] for symbol, _, _ in rows)
    end_dates = Counter(end for _, _, end in rows)
    stale = [{"symbol": symbol, "end": end} for symbol, _, end in rows
             if end < manifest.get("target_trade_date", "") and symbol.startswith("BJ")]
    record["instruments"] = {
        "rows": len(rows),
        "distinct_symbols": len({symbol for symbol, _, _ in rows}),
        "by_exchange_prefix": dict(sorted(by_exchange.items())),
        "top_end_dates": end_dates.most_common(6),
        "delisted_example": next(({"symbol": symbol, "start": start, "end": end}
                                  for symbol, start, end in rows if symbol == "SH600005"), None),
        "stale_beijing_instruments": len(stale),
        "stale_beijing_sample": stale[:5],
    }
    for name in ("csi300", "csi500", "csi1000", "csiall"):
        members = load_instruments(snapshot / f"instruments/{name}.txt")
        record["instruments"][f"{name}_rows"] = len(members)
        record["instruments"][f"{name}_beijing_rows"] = sum(1 for symbol, _, _ in members
                                                            if symbol.startswith("BJ"))

    sample_dir = snapshot / "features/sh600000"
    record["sample_symbol"] = "sh600000"
    record["sample_fields"] = sorted(path.name.split(".")[0] for path in sample_dir.iterdir())

    if args.enrichment:
        enrichment = Path(args.enrichment).expanduser()
        turnover_dir = enrichment / "turnover"
        universe_symbols = {symbol for symbol, _, _ in
                            load_instruments(snapshot / f"instruments/{args.universe}.txt")}
        cached = sorted(path.stem for path in turnover_dir.glob("*.csv")) if turnover_dir.exists() else []
        rows = dates = 0
        first = last = None
        for path in turnover_dir.glob("*.csv") if turnover_dir.exists() else []:
            lines = path.read_text().splitlines()
            if len(lines) <= 1:
                continue
            rows += len(lines) - 1
            dates += 1
            first = min(first, lines[1].split(",")[0]) if first else lines[1].split(",")[0]
            last = max(last, lines[-1].split(",")[0]) if last else lines[-1].split(",")[0]
        missing_cache = sorted(universe_symbols - set(cached))
        record["enrichment"] = {
            "source_class": SOURCE_CLASS,
            "kind": "baostock_daily_turnover_status",
            "universe": args.universe,
            "universe_symbols": len(universe_symbols),
            "cached_symbols": len(cached),
            "rows": rows,
            "first_date": first,
            "last_date": last,
            "symbols_without_cache": len(missing_cache),
            "symbols_without_cache_sample": missing_cache[:20],
            "note": ("symbols without cache are names delisted before the fetch window; "
                     "they stay out of the study window instead of being filled"),
        }

    Path(args.output).write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"ok": not missing and record["calendar"]["matches_target_trade_date"],
                      "output": args.output,
                      "calendar_last": calendar[-1],
                      "instruments": record["instruments"]["rows"],
                      "stale_beijing": record["instruments"]["stale_beijing_instruments"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
