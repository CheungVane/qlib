#!/usr/bin/env python3
"""Explicit, idempotent import of real snapshot baselines; no download or training."""
import argparse
import json
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extensions' / 'workbench'))
from quant_workbench.bootstrap import WorkbenchSettings, build_workbench
from quant_workbench import data_directory as dd
from quant_workbench.adapters.baseline_factors import baseline_panels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--snapshot-id', default='free_cn_20260924_processed_v1')
    parser.add_argument('--start', type=date.fromisoformat, default=date(2025, 1, 2))
    parser.add_argument('--end', type=date.fromisoformat, default=date(2026, 9, 24))
    args = parser.parse_args()
    record = dd.load_snapshot(args.data_root / '_registry', args.snapshot_id)
    reader = dd.FreeSnapshotReader(args.data_root, record)
    service = build_workbench(WorkbenchSettings(args.root, args.data_root), with_executors=False)
    results = []
    for identity, panel in baseline_panels(reader, args.start, args.end):
        result = service.import_factor_panel(identity, panel)
        results.append({**result, 'name': identity['name'], 'dates': len(panel['dates']),
                        'instruments': len(panel['instruments']),
                        'valid_values': sum(v is not None for v in panel['values'])})
    print(json.dumps({'snapshot_id': args.snapshot_id, 'content_digest': record['content_digest'],
                      'panels': results}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
