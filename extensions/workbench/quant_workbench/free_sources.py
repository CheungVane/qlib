"""Free-source helpers: unit conventions, universe, float shares, PIT industry proxy.

Contract: docs/spec/DATA_SOURCES.md §1A/§1B and docs/spec/PROVENANCE_AUDIT.md.
Everything here is derived from `free_community_unverified` sources: keep that label,
do not present these values as official, and never use them to certify alpha.
"""

from __future__ import annotations

import math
import struct
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

ARCHIVE_FIELDS = ("open", "close", "high", "low", "vwap", "volume",
                  "amount", "factor", "adjclose", "change")
# Verified on sh600000 2026-09-24 against BaoStock and East Money (exact float32 values):
#   raw_close = close / factor = 6.1169338 / 0.67965931 = 9.0000001  (sources said 9.00)
#   raw_lots  = volume * factor = 777395.3125 * 0.67965931 = 528363.96 (sources said 528,364)
#   amount is thousand CNY: 475964.875 -> 475,964,875 CNY (BaoStock said 475,964,884.07)
AMOUNT_UNIT = "thousand_CNY"
VOLUME_UNIT = "adjusted_lot_100_shares"


class FreeSourceError(ValueError):
    """Invalid or unusable free-source input."""


# -- qlib bin reading (no qlib import needed) --------------------------------
def read_bin_head_tail(path: str | Path) -> dict:
    """Read the header index and last value of a qlib `.bin` file."""
    target = Path(path)
    size = target.stat().st_size
    if size < 8 or (size - 4) % 4:
        raise FreeSourceError(f"not a qlib bin file: {target}")
    with target.open("rb") as handle:
        start = int(struct.unpack("<f", handle.read(4))[0])
        handle.seek(-4, 2)
        last = float(struct.unpack("<f", handle.read(4))[0])
    return {"start_index": start, "points": (size - 4) // 4, "last": last}


def read_bin_values(path: str | Path) -> list[float]:
    """Read the full value array (float32) of a qlib `.bin` file."""
    target = Path(path)
    raw = target.read_bytes()
    if len(raw) < 8 or (len(raw) - 4) % 4:
        raise FreeSourceError(f"not a qlib bin file: {target}")
    count = (len(raw) - 4) // 4
    return list(struct.unpack(f"<{count}f", raw[4:]))


# -- unit conventions --------------------------------------------------------
def raw_price(adjusted_price: float, factor: float) -> float:
    """Undo the archive's adjustment: raw = adjusted / factor."""
    if not math.isfinite(factor) or factor <= 0:
        raise FreeSourceError("factor must be a positive finite number")
    return adjusted_price / factor


def raw_volume_lots(adjusted_volume: float, factor: float) -> float:
    """Archive volume is inversely adjusted: raw lots = adjusted * factor."""
    if not math.isfinite(factor) or factor <= 0:
        raise FreeSourceError("factor must be a positive finite number")
    return adjusted_volume * factor


# -- gap 1: daily float shares ----------------------------------------------
def float_shares_from_turnover(raw_volume_shares: float, turnover_percent: float) -> float:
    """流通股本 ≈ 成交量(股) / 换手率(%)."""
    if not math.isfinite(raw_volume_shares) or raw_volume_shares < 0:
        raise FreeSourceError("raw_volume_shares must be a non-negative number")
    if not math.isfinite(turnover_percent) or turnover_percent <= 0:
        raise FreeSourceError("turnover_percent must be positive; suspended days cannot imply shares")
    return raw_volume_shares / (turnover_percent / 100.0)


def float_market_cap(raw_close: float, raw_volume_shares: float, turnover_percent: float) -> float:
    """日频流通市值 ≈ 原始收盘价 × 由换手率反推的流通股本。"""
    return raw_close * float_shares_from_turnover(raw_volume_shares, turnover_percent)


# -- gap 3: date-ranged universe / survivorship -----------------------------
def load_instruments(text: str) -> list[dict]:
    """Parse a qlib instruments file: `SYMBOL<TAB>START<TAB>END`."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 3:
            raise FreeSourceError(f"bad instruments line: {line!r}")
        symbol, start, end = parts
        rows.append({"symbol": symbol, "start": date.fromisoformat(start),
                     "end": date.fromisoformat(end)})
    if not rows:
        raise FreeSourceError("instruments file is empty")
    return rows


def active_universe(rows: Iterable[dict], as_of: date) -> list[str]:
    """Symbols whose recorded interval covers `as_of` (delisted names drop out by date)."""
    return [row["symbol"] for row in rows if row["start"] <= as_of <= row["end"]]


def survivorship_report(rows: Iterable[dict], as_of: date,
                        delist_dates: dict[str, object] | None = None) -> dict:
    """Flag instruments whose data ended early while no delisting is recorded.

    `stale` entries are coverage gaps, not delistings: using them as if the stock
    stopped trading would silently drop live names from the universe.
    """
    delist_dates = delist_dates or {}
    active, stale, delisted = [], [], []
    for row in rows:
        symbol = row["symbol"]
        if row["end"] >= as_of:
            active.append(symbol)
        elif delist_dates.get(symbol):
            delisted.append({"symbol": symbol, "end": row["end"].isoformat(),
                             "delist_date": str(delist_dates[symbol])})
        else:
            stale.append({"symbol": symbol, "end": row["end"].isoformat()})
    return {"as_of": as_of.isoformat(), "active": len(active), "delisted": len(delisted),
            "stale": len(stale), "stale_symbols": stale[:50], "active_symbols": active}


# -- gap 2: PIT industry proxy ----------------------------------------------
def statistical_industry(window: dict[str, Sequence[float]], n_clusters: int,
                         iterations: int = 25) -> dict[str, int]:
    """Cluster instruments by their own return history — PIT by construction.

    Uses only `window` (a trailing return window). Deterministic seeding keeps the
    labels reproducible; the result is a statistical grouping, not a named industry.
    """
    symbols = [code for code, values in window.items() if len(values) >= 10]
    if n_clusters < 2 or len(symbols) < n_clusters:
        raise FreeSourceError("need at least n_clusters symbols with 10+ observations")
    try:
        import numpy as np
    except ImportError as error:  # pragma: no cover - numpy is an analysis extra
        raise FreeSourceError("statistical_industry needs numpy") from error

    matrix = np.asarray([[float(value) for value in window[code]] for code in symbols], dtype=float)
    if not np.isfinite(matrix).all():
        raise FreeSourceError("return window contains missing or non-finite values")
    matrix -= matrix.mean(axis=1, keepdims=True)
    spread = matrix.std(axis=1, keepdims=True)
    spread[spread <= 1e-12] = 1e-12
    matrix /= spread

    seeds = [int(round(index * (len(symbols) - 1) / max(n_clusters - 1, 1)))
             for index in range(n_clusters)]
    centroids = matrix[seeds].copy()
    labels = np.zeros(len(symbols), dtype=int)
    for _ in range(iterations):
        distance = ((matrix[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        updated = distance.argmin(axis=1)
        if np.array_equal(updated, labels):
            break
        labels = updated
        for cluster in range(n_clusters):
            members = matrix[labels == cluster]
            if len(members):
                centroids[cluster] = members.mean(axis=0)
    return {code: int(label) for code, label in zip(symbols, labels)}
