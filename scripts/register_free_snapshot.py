#!/usr/bin/env python3
"""T05: publish the free snapshot into the data-directory registry and audit it.

Read-only with respect to the snapshot; writes only the registry, the materialized panel
and the evidence file. Legacy paths are registered explicitly so they can never be
silently promoted into a snapshot.

Usage:
  python3 scripts/register_free_snapshot.py --data-root ~/.qlib/qlib_data \
    --registry ~/.qlib/qlib_data/_registry \
    --record docs/spec/evidence/20260927-free-snapshot-record.json \
    --universe csi500 --bars-limit 50 --panel-start 2026-09-01 --panel-end 2026-09-24 \
    --legacy cn_data --legacy qwb_cn_current \
    --output docs/spec/evidence/20260927-t05-directory.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extensions" / "workbench"))
from quant_workbench import data_directory as dd  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--record", required=True)
    parser.add_argument("--universe", default="csi500")
    parser.add_argument("--bars-limit", type=int, default=50, help="0 audits the whole universe")
    parser.add_argument("--panel-start", default="2026-09-01")
    parser.add_argument("--panel-end", default="2026-09-24")
    parser.add_argument("--panel-limit", type=int, default=20)
    parser.add_argument("--legacy", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data_root = Path(args.data_root).expanduser()
    registry = Path(args.registry).expanduser()
    record = json.loads(Path(args.record).read_text())
    reader = dd.FreeSnapshotReader(data_root, record)
    reader.require_verified().verify_all()
    from quant_workbench.adapters.data_preparation import audit_bars
    symbols_all = sorted({r['symbol'] for r in reader.instruments(args.universe)})
    quality = audit_bars(reader.path('bar'), reader.calendar(), symbols_all)
    if not quality['passed']:
        Path(args.output).write_text(json.dumps({'published': False, 'quality': quality}, indent=2))
        return 2
    stored = record

    legacy = []
    for label in args.legacy:
        if not (data_root / label).exists():
            continue
        dd.register_legacy(registry, legacy_id=label, path_label=label,
                           reason="pre-existing local data without recorded digest or upstream")
        legacy.append(label)

    symbols = reader.universe_on(date.fromisoformat(args.panel_end), args.universe)
    audit_symbols = symbols if not args.bars_limit else symbols[: args.bars_limit]
    bars = dd.validate_bars(reader, audit_symbols)

    start, end = date.fromisoformat(args.panel_start), date.fromisoformat(args.panel_end)
    panel_paths = []
    for index in (1, 2):
        target = registry.parent / f"panel-{args.universe}-{args.panel_start}-{index}.csv"
        record_out = dd.materialize_panel(
            reader, output=target, universe=args.universe, fields=["close", "volume"],
            start=start, end=end, seed=0, limit=args.panel_limit)
        panel_paths.append((target, record_out))
    first, second = panel_paths
    replay = dd.verify_materialization(first[1], first[0])

    if not bars['ok'] or not replay['ok'] or first[1]['output_digest'] != second[1]['output_digest']:
        Path(args.output).write_text(json.dumps({'published': False, 'bar_quality': bars, 'replay': replay}, indent=2))
        return 2
    published = dd.publish_snapshot(registry, record, data_root=data_root)
    evidence = {
        "t05_slice": "directory_registry_materialization",
        "snapshot_id": stored["snapshot_id"],
        "snapshot_content_digest": stored["content_digest"],
        "registry_record": published.name,
        "manifest_validation": reader.validate(),
        "bar_quality_gate": {"audited_symbols": len(audit_symbols),
                             "universe_symbols": len(symbols),
                             "ok": bars["ok"], "issue_count": bars["issue_count"],
                             "issues_sample": bars["issues"][:10]},
        "materialization": {
            "window": {"start": args.panel_start, "end": args.panel_end},
            "fields": ["close", "volume"], "seed": 0,
            "rows": first[1]["rows"],
            "first_digest": first[1]["output_digest"],
            "second_digest": second[1]["output_digest"],
            "deterministic_replay": first[1]["output_digest"] == second[1]["output_digest"],
            "replay_check": replay["ok"],
        },
        "legacy_registered": legacy,
        "legacy_count": len(dd.list_legacy(registry)),
        "reproducibility": dd.reproducibility(stored),
        "paths_recorded": False,
        "notes": ["registry and materialized panel live outside the repository",
                  "the bar audit is a sample unless --bars-limit 0",
                  "legacy paths are registered as legacy_unknown and cannot be promoted silently"],
    }
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"ok": evidence["bar_quality_gate"]["ok"] and replay["ok"],
                      "audited_symbols": len(audit_symbols),
                      "issue_count": bars["issue_count"],
                      "deterministic_replay": evidence["materialization"]["deterministic_replay"],
                      "legacy_registered": legacy}, ensure_ascii=False))
    return 0 if evidence["bar_quality_gate"]["ok"] and replay["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
