#!/usr/bin/env python3
"""Freeze and audit existing free data offline; failed quality exits nonzero without publication."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'extensions/workbench'))
from quant_workbench.adapters.data_preparation import prepare

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--snapshot-id', default='free_cn_20260924_processed_v1')
    args = parser.parse_args()
    report = prepare(args.data_root.expanduser(), snapshot_id=args.snapshot_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['published'] else 2)
