"""Shared numeric helpers and tolerances (third-review C3/C9).

One implementation for the lazy numpy import, the Sharpe base quantity and the two tolerances
the platform uses. Domain minimums (how many observations a given estimator needs) stay in
their own modules on purpose: they answer different questions, see VALIDATION.md.
"""

from __future__ import annotations

import math

# comparison table: below this relative difference two values count as the same (float noise)
RANK_TOLERANCE = 1e-9
# a dispersion at or below this counts as zero (no ratio can be formed from it)
ZERO_TOLERANCE = 1e-12


def numpy(error: type[Exception] = RuntimeError,
          message: str = "numeric analysis needs numpy (install the 'analysis' extra)"):
    """Import numpy lazily and surface the caller's own error type when it is missing."""
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - declared in the analysis extra
        raise error(message) from exc
    return np


def sharpe(values, periods_per_year: int | None = None):
    """mean/std (ddof=1), optionally annualised; None when the dispersion is degenerate."""
    np = numpy()
    array = np.asarray(values, dtype=float)
    if len(array) < 2:
        return None
    std = float(array.std(ddof=1))
    if std <= ZERO_TOLERANCE:
        return None
    ratio = float(array.mean()) / std
    return ratio * math.sqrt(periods_per_year) if periods_per_year else ratio


def moment_stats(values):
    """Skewness and kurtosis (non-excess, i.e. 3.0 for a normal sample); None if degenerate."""
    np = numpy()
    array = np.asarray(values, dtype=float)
    if len(array) < 2:
        return None, None
    std = float(array.std(ddof=1))
    if std <= ZERO_TOLERANCE:
        return None, None
    centred = array - array.mean()
    return float((centred ** 3).mean() / std ** 3), float((centred ** 4).mean() / std ** 4)
