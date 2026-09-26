"""Create deterministic, synthetic CN daily data for an end-to-end Qlib run.

The generated prices and index membership are fictional. Never use this dataset
to evaluate a trading strategy.
"""

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / ".data" / "cn_demo"


def write_field(directory: Path, name: str, values: np.ndarray) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    np.concatenate(([0], values)).astype("<f4").tofile(directory / f"{name}.day.bin")


def main() -> None:
    rng = np.random.default_rng(20260925)
    # Qlib's final backtest step asks for the next calendar boundary.
    dates = pd.bdate_range("2019-10-01", "2022-01-10")
    (TARGET / "calendars").mkdir(parents=True, exist_ok=True)
    (TARGET / "instruments").mkdir(parents=True, exist_ok=True)
    (TARGET / "calendars" / "day.txt").write_text(
        "\n".join(dates.strftime("%Y-%m-%d")) + "\n", encoding="utf-8"
    )
    (TARGET / "calendars" / "day_future.txt").write_text(
        "\n".join(dates.strftime("%Y-%m-%d")) + "\n", encoding="utf-8"
    )
    stocks = [f"SH600{i:03d}" for i in range(16)]
    first, last = dates[0].date(), dates[-1].date()
    (TARGET / "instruments" / "csi500.txt").write_text(
        "".join(f"{code}\t{first}\t{last}\n" for code in stocks), encoding="utf-8"
    )
    (TARGET / "instruments" / "all.txt").write_text(
        "".join(f"{code}\t{first}\t{last}\n" for code in stocks + ["SH000905"]), encoding="utf-8"
    )

    for i, code in enumerate(stocks + ["SH000905"]):
        market = i == len(stocks)
        returns = rng.normal(0.0002, 0.009 if market else 0.018, len(dates))
        close = (1000 if market else 15 + i) * np.exp(np.cumsum(returns))
        open_ = close * np.exp(rng.normal(0, 0.003, len(dates)))
        high = np.maximum(open_, close) * (1 + rng.uniform(0.001, 0.01, len(dates)))
        low = np.minimum(open_, close) * (1 - rng.uniform(0.001, 0.01, len(dates)))
        vwap = (open_ + close + high + low) / 4
        volume = rng.integers(100_000, 1_000_000, len(dates)).astype(float)
        change = np.r_[0, close[1:] / close[:-1] - 1]
        fields = dict(open=open_, high=high, low=low, close=close, vwap=vwap,
                      volume=volume, change=change, factor=np.ones(len(dates)))
        for field, values in fields.items():
            write_field(TARGET / "features" / code.lower(), field, values)

    print(f"Synthetic CN demo data ready: {TARGET} ({len(stocks)} stocks, {len(dates)} weekdays)")


if __name__ == "__main__":
    main()
