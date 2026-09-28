"""Pure calendar and declared price semantics. IO remains in data adapters."""
import math
import struct


def decode_bin(data: bytes, calendar_length: int) -> tuple[int, tuple[float, ...]]:
    if len(data) < 8 or len(data) % 4:
        raise ValueError('invalid bin length')
    start = struct.unpack('<f', data[:4])[0]
    if not math.isfinite(start) or start < 0 or int(start) != start:
        raise ValueError('invalid bin start')
    values = struct.unpack(f'<{len(data) // 4 - 1}f', data[4:])
    if int(start) + len(values) > calendar_length:
        raise ValueError('bin extends beyond calendar')
    return int(start), values


def adjusted_close(close: float, factor: float | None, price_basis: str) -> float:
    if price_basis == 'finv_adjusted_v1' or price_basis == 'adjusted_v1':
        return close
    if price_basis == 'raw_with_factor_v1':
        if factor is None or not math.isfinite(factor) or factor <= 0:
            return float('nan')
        return close * factor
    raise ValueError('unknown price basis')
