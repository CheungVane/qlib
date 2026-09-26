"""Engine-neutral calculations on a complete immutable result revision."""
from .model import _instant


def coordinate(entry, point):
    return _instant(point['x'], 'point.x').isoformat() if entry['axis'] == 'time' else point['x']


def summarize(entry):
    points = entry.get('points', []) if entry else []
    valid = [p for p in points if p['value'] is not None]
    first, last = (points[0], points[-1]) if points else ({}, {})
    missing = len(points) - len(valid)
    reason = (entry or {}).get('availability', 'not_recorded')
    return {'point_count':len(points), 'valid_points':len(valid), 'missing_points':missing,
            'start':first.get('x'), 'end':last.get('x'),
            'first':first.get('value'), 'last':last.get('value'),
            'first_reason':first.get('reason', reason if not points else None),
            'last_reason':last.get('reason', reason if not points else None),
            'minimum':min(p['value'] for p in valid) if valid and not missing else None,
            'last_valid':valid[-1] if valid else None,
            'complete':bool(points) and not missing}


def equity_drawdown(points, initial=None):
    if not points or any(p['value'] is None or p['value'] <= 0 for p in points):
        return None
    high = initial if initial is not None else points[0]['value']
    if high <= 0:
        return None
    result = []
    for p in points:
        high = max(high, p['value'])
        result.append(p['value'] / high - 1)
    return min(result)
