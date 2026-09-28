"""Offline preparation of preserved free-source inputs; no network or automatic repairs."""
from __future__ import annotations

from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path
import tarfile

from .. import free_sources as fs
from ..domain.data import decode_bin
from .snapshot_files import atomic_create, file_entry, seal_record, VerifiedFiles

VERSION = '2'


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def preserve_copy(source, target):
    """Resume only exact copies. Never overwrite an existing different file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha(source) != sha(target):
            raise ValueError(f'frozen file differs: {target.name}')
        return
    # atomic_create prevents two preparation processes from clobbering each other.
    try:
        atomic_create(target, source.read_bytes())
    except FileExistsError:
        if sha(source) != sha(target):
            raise ValueError('concurrent frozen copy differs')


def audit_bars(feature_root, calendar, symbols, *, verified=None):
    """Independent per-field offsets; count invalid observations without deleting them."""
    import numpy as np
    errors, missing, observations = [], Counter(), Counter()
    for symbol in sorted(symbols):
        aligned = {}
        for field in fs.ARCHIVE_FIELDS:
            try:
                name = f'{symbol.lower()}/{field}.day.bin'
                data = verified.read('bar', name) if verified else (feature_root / name).read_bytes()
                start, values = decode_bin(data, len(calendar))
            except (OSError, ValueError) as exc:
                errors.append({'symbol': symbol, 'field': field, 'reason': str(exc) if isinstance(exc, ValueError) else 'missing_file'})
                continue
            values = np.array(values)
            missing[field] += int(np.isnan(values).sum())
            observations[field] += len(values)
            invalid = np.isinf(values)
            if field in ('open', 'high', 'low', 'close', 'vwap', 'factor', 'adjclose'):
                invalid |= values <= 0
            elif field in ('volume', 'amount'):
                invalid |= values < 0
            if invalid.any():
                first = int(np.flatnonzero(invalid)[0])
                errors.append({'symbol': symbol, 'field': field, 'reason': 'invalid_value',
                               'count': int(invalid.sum()), 'first_date': calendar[start + first].isoformat(),
                               'first_value': float(values[first]) if np.isfinite(values[first]) else str(values[first])})
            if field in ('open', 'high', 'low', 'close'):
                panel = np.full(len(calendar), np.nan)
                panel[start:start + len(values)] = values
                aligned[field] = panel
        if len(aligned) == 4:
            o, h, l, c = (aligned[f] for f in ('open', 'high', 'low', 'close'))
            tolerance = 1e-5 * np.maximum.reduce([np.abs(o), np.abs(h), np.abs(l), np.abs(c)])
            invalid = (l > np.minimum(o, c) + tolerance) | (h + tolerance < np.maximum(o, c)) | (l > h + tolerance)
            if invalid.any():
                idx = int(np.flatnonzero(invalid)[0])
                errors.append({'symbol': symbol, 'reason': 'ohlc_envelope', 'count': int(invalid.sum()),
                               'first_date': calendar[idx].isoformat(),
                               'first_ohlc': [float(aligned[f][idx]) for f in ('open', 'high', 'low', 'close')]})
    return {'passed': not errors, 'checked_symbols': len(symbols), 'invalid_groups': len(errors),
            'missing_field_points': dict(missing), 'observed_field_points': dict(observations),
            'errors': errors, 'relative_tolerance': 1e-5}


def prepare(root: Path, *, source_id='free_cn_20260924', snapshot_id='free_cn_20260924_processed_v1'):
    """Freeze observed inputs, audit all bars, then publish only a passing new identity."""
    from ..data_directory import load_snapshot, publish_snapshot
    root = Path(root)
    for identity in (source_id, snapshot_id):
        if not identity or Path(identity).name != identity or identity in ('.', '..'):
            raise ValueError('unsafe snapshot id')
    original = load_snapshot(root / '_registry', source_id)
    source = root / source_id
    archive = root / '_downloads' / original['source']['release_tag'] / 'qlib_bin.tar.gz'
    archive_sha = sha(archive)
    if archive_sha != original['provenance']['archive_sha256'].removeprefix('sha256:'):
        raise ValueError('archive digest mismatch')
    manifest_path = archive.with_name('qlib_bin.manifest.json')
    manifest = json.loads(manifest_path.read_text())
    manifest_sha = sha(manifest_path)
    if manifest_sha != original['provenance']['manifest_sha256'].removeprefix('sha256:'):
        raise ValueError('source manifest digest mismatch')
    if manifest['archive_sha256'].removeprefix('sha256:') != archive_sha or manifest['archive_size_bytes'] != archive.stat().st_size:
        raise ValueError('source manifest/archive mismatch')
    members = fs.load_instruments((source / 'instruments/csi500.txt').read_text())
    if any(row['start'] > row['end'] for row in members):
        raise ValueError('inverted membership interval')
    symbols = {row['symbol'] for row in members} | {'SH000905'}
    wanted = {'calendars/day.txt', 'instruments/all.txt', 'instruments/csi500.txt'}
    wanted |= {f'features/{s.lower()}/{f}.day.bin' for s in symbols for f in fs.ARCHIVE_FIELDS}
    frozen = root / 'processed' / snapshot_id
    preserve_copy(manifest_path, frozen / 'source-manifest.json')
    seen = set()
    with tarfile.open(archive, 'r|gz') as bundle:
        for member in bundle:
            name = member.name.removeprefix('qlib_bin/')
            if name not in wanted:
                continue
            if name in seen or not member.isfile():
                raise ValueError('duplicate or non-file archive member')
            data = bundle.extractfile(member).read()
            if hashlib.sha256(data).hexdigest() != sha(source / name):
                raise ValueError(f'archive/extracted mismatch: {name}')
            preserve_copy(source / name, frozen / name)
            # Compare the frozen bytes too, protecting against a changed source between reads.
            if hashlib.sha256(data).hexdigest() != sha(frozen / name):
                raise ValueError('source changed during freeze')
            seen.add(name)
    if seen != wanted:
        raise ValueError('required archive members missing')
    calendar = [date.fromisoformat(s) for s in (frozen / 'calendars/day.txt').read_text().split()]
    if not calendar or calendar != sorted(set(calendar)):
        raise ValueError('calendar invalid')
    if calendar[-1].isoformat() != manifest['target_trade_date']:
        raise ValueError('calendar does not reach source manifest target date')
    cache = root / (source_id + '_enrichment') / 'turnover'
    cache_counts, cache_errors, absent = Counter(), [], []
    coverage = Counter()
    study_dates = [d for d in calendar if date(2015, 1, 5) <= d <= date(2026, 9, 24)]
    for symbol in sorted(symbols - {'SH000905'}):
        target = cache / (symbol + '.csv')
        if not target.exists():
            intervals = [r for r in members if r['symbol'] == symbol]
            absent.append({'symbol': symbol, 'last_membership': max(r['end'] for r in intervals).isoformat()})
            continue
        preserve_copy(target, frozen / 'turnover' / target.name)
        try:
            rows = fs.parse_turnover_csv((frozen / 'turnover' / target.name).read_text())
            cache_counts['files'] += 1
            cache_counts['rows'] += len(rows)
            cache_counts['missing_turn'] += sum(r['turn'] is None for r in rows.values())
            cache_counts['zero_turn'] += sum(r['turn'] == 0 for r in rows.values())
            intervals = [(r['start'], r['end']) for r in members if r['symbol'] == symbol]
            for day in study_dates:
                if any(a <= day <= b for a, b in intervals):
                    coverage['membership_rows'] += 1
                    observed = rows.get(day.isoformat())
                    coverage['missing_status_dates'] += observed is None
                    coverage['observed_status_dates'] += observed is not None
                    coverage['observed_suspended_dates'] += bool(observed and observed['tradestatus'] == 0)
                    coverage['observed_st_dates'] += bool(observed and observed['isST'] == 1)
        except ValueError as exc:
            cache_errors.append({'symbol': symbol, 'error': str(exc)})
    quality = audit_bars(frozen / 'features', calendar, symbols)
    quality['cache'] = dict(cache_counts)
    quality['membership_status_coverage'] = dict(coverage)
    quality['cache_errors'] = cache_errors
    quality['missing_cache'] = absent
    quality['passed'] = quality['passed'] and not cache_errors and all(r['last_membership'] < '2015-01-05' for r in absent)
    report = {'version': VERSION, 'snapshot_id': snapshot_id, 'archive_sha256': archive_sha,
              'archive_members_compared': len(seen), 'source_manifest_sha256': manifest_sha, 'quality': quality, 'published': False,
              'historical_cache_completion': 'unknown', 'historical_available_at': 'unknown',
              'source_class': 'free_community_unverified'}
    if quality['passed']:
        record = dict(original)
        record.update(snapshot_id=snapshot_id, created_at=None,
                      materializer={'name': 'offline_free_preparation', 'version': VERSION})
        record['provenance'] = {**original['provenance'], 'completeness': 'limited',
                                'historical_cache_completion': 'unknown', 'archive_members_compared': len(seen)}
        locations = {'calendar': 'calendars/day.txt', 'bar': 'features', 'universe': 'instruments', 'status': 'turnover'}
        record['components'] = [{**c, 'uri': (frozen / locations[c['kind']]).relative_to(root).as_posix()} for c in original['components']]
        record['limitations'] = original['limitations'] + ['historical availability and cache completion unknown; not PIT certified']
        record = seal_record(root, record, {'price_basis': 'finv_adjusted_v1', 'universe': 'csi500',
                              'amount_unit': 'thousand_CNY', 'volume_unit': 'inverse_adjusted_lot',
                              'turn_unit': 'percent', 'historical_cache_completion': 'unknown'}, quality)
        report['verification'] = VerifiedFiles(root, record).verify_all()
        panels = normalized_panels(root, snapshot_id, date(2015,1,5), date(2026,9,24), record=record)
        report['normalized_panels'] = {'chunks': len(panels['chunks']), 'rows': sum(c['rows'] for c in panels['chunks']),
                                       'materializer_version': panels['materializer_version']}
        publish_snapshot(root / '_registry', record, data_root=root)
        report['published'] = True
    payload = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    report_path = frozen / 'preparation-report.json'
    if report_path.exists():
        if report_path.read_bytes() != payload:
            raise ValueError('preparation report differs; use a new version')
    else:
        atomic_create(report_path, payload)
    return report


PANEL_COLUMNS = ['date', 'symbol', 'adjusted_close', 'raw_close', 'raw_volume_shares',
                 'amount_cny', 'turn_percent', 'tradestatus', 'is_st',
                 'float_shares_estimate', 'float_cap_estimate']


def normalized_panels(root: Path, snapshot_id: str, start: date, end: date, *, record=None):
    """Annual output, independent membership-key scan and byte-for-byte replay."""
    import csv
    import math
    import tempfile
    from ..data_directory import FreeSnapshotReader, load_snapshot
    root = Path(root)
    record = record if record is not None else load_snapshot(root / '_registry', snapshot_id)
    reader = FreeSnapshotReader(root, record)
    reader.require_verified().verify_all()
    if record['interpretation']['price_basis'] != 'finv_adjusted_v1':
        raise ValueError('unsupported normalization basis')
    calendar = reader.calendar()
    positions = {d: i for i, d in enumerate(calendar)}
    members = reader.instruments('csi500')
    destination = root / 'processed' / snapshot_id / 'panels_v2_1'
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {'schema_version': 1, 'materializer_version': '2.1',
                'snapshot_id': snapshot_id, 'input_content_digest': record['content_digest'],
                'window': {'start': start.isoformat(), 'end': end.isoformat()},
                'columns': PANEL_COLUMNS, 'source_class': 'free_community_unverified',
                'price_basis': 'finv_adjusted_v1', 'missing_representation': 'empty CSV cell',
                'historical_cache_completion': 'unknown', 'historical_available_at': 'unknown', 'chunks': []}
    def render(path, dates):
        counts = Counter()
        rows = 0
        with path.open('w', newline='') as handle:
            writer = csv.writer(handle, lineterminator='\n')
            writer.writerow(PANEL_COLUMNS)
            for symbol in sorted({r['symbol'] for r in members if r['start'] <= dates[-1] and r['end'] >= dates[0]}):
                intervals = [(r['start'], r['end']) for r in members if r['symbol'] == symbol]
                series = {f: reader.bin_series(symbol, f) for f in ('close', 'factor', 'volume', 'amount')}
                status = reader.turnover(symbol)
                def value(field, day):
                    offset, values = series[field]
                    i = positions[day] - offset
                    if not 0 <= i < len(values):
                        counts['coverage_outside_' + field] += 1
                        return float('nan')
                    val = values[i]
                    counts['source_nan_' + field] += math.isnan(val)
                    return val
                for day in dates:
                    if not any(a <= day <= b for a, b in intervals):
                        continue
                    close, factor, volume, amount = (value(f, day) for f in ('close', 'factor', 'volume', 'amount'))
                    observed = status.get(day.isoformat(), {})
                    turn = observed.get('turn')
                    raw_close = close / factor if factor > 0 else float('nan')
                    shares = volume * factor * 100
                    float_shares = shares * 100 / turn if turn is not None and turn > 0 else float('nan')
                    values = [close, raw_close, shares, amount * 1000, turn, observed.get('tradestatus'),
                              observed.get('isST'), float_shares, raw_close * float_shares]
                    counts['missing_status_dates'] += not observed
                    cells = []
                    for key, val in zip(PANEL_COLUMNS[2:], values):
                        missing = val is None or not math.isfinite(val)
                        counts['missing_' + key] += missing
                        cells.append('' if missing else format(val, '.17g'))
                    writer.writerow([day.isoformat(), symbol, *cells])
                    rows += 1
        return rows, dict(counts)
    for year in range(start.year, end.year + 1):
        dates = [d for d in calendar if start <= d <= end and d.year == year]
        if not dates:
            continue
        with tempfile.TemporaryDirectory(dir=destination, prefix='.pending-') as temp:
            first, replay = Path(temp) / 'first.csv', Path(temp) / 'replay.csv'
            rows, missing = render(first, dates)
            render(replay, dates)
            if sha(first) != sha(replay):
                raise ValueError('non-deterministic materialization')
            # Independently enumerate membership per date, not the writer's symbol loop.
            expected = {(d.isoformat(), s) for d in dates for s in set(fs.active_universe(members, d))}
            actual = set()
            with first.open() as handle:
                for row in csv.DictReader(handle):
                    key = (row['date'], row['symbol'])
                    if key in actual:
                        raise ValueError('duplicate normalized key')
                    actual.add(key)
                    if row['turn_percent'] and float(row['turn_percent']) > 0 and row['raw_volume_shares']:
                        expected_shares = float(row['raw_volume_shares']) / (float(row['turn_percent']) / 100)
                        if not math.isclose(float(row['float_shares_estimate']), expected_shares, rel_tol=1e-12):
                            raise ValueError('float share conversion mismatch')
            if actual != expected or rows != len(actual):
                raise ValueError('normalized keys differ from independent membership enumeration')
            output = destination / f'{year}.csv'
            preserve_copy(first, output)
            manifest['chunks'].append({**file_entry(output, output.name), 'rows': rows, 'unique_keys': len(actual),
                'start': dates[0].isoformat(), 'end': dates[-1].isoformat(), 'missing': missing,
                'replay_verified': True, 'independent_keys_verified': True, 'unit_identity_verified': True})
    target = destination / 'manifest.json'
    payload = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    if target.exists():
        if target.read_bytes() != payload:
            raise ValueError('panel manifest differs')
    else:
        atomic_create(target, payload)
    return manifest


def validate_publication(root, record):
    """Recompute mandatory gates from the exact bytes authorized by the manifest."""
    verified = VerifiedFiles(root, record)
    verified.verify_all()
    calendar = [date.fromisoformat(d) for d in verified.read('calendar').decode().split()]
    if not calendar or calendar != sorted(set(calendar)):
        raise ValueError('invalid calendar')
    members = fs.load_instruments(verified.read('universe', 'csi500.txt').decode())
    fs.load_instruments(verified.read('universe', 'all.txt').decode())
    symbols = {row['symbol'] for row in members} | {'SH000905'}
    quality = audit_bars(None, calendar, symbols, verified=verified)
    if not quality['passed']:
        raise ValueError('bar quality failed; publication refused')
    names = verified.entries.get('status', (None, {}))[1]
    for name in names:
        fs.parse_turnover_csv(verified.read('status', name).decode())
    missing = [r['symbol'] for r in members if r['end'] >= date(2015, 1, 5)
               and r['symbol'] + '.csv' not in names]
    if missing:
        raise ValueError('required status files missing')
    return quality
