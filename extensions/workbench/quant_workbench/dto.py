"""DTO helpers shared by every domain module (third-review C3)."""

from __future__ import annotations

import math


def json_safe(value):
    """Non-finite floats become null: DTOs must stay JSON compliant (allow_nan=False)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value
