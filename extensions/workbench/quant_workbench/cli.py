"""CLI boundary; it uses the same service methods as the HTTP API."""

from __future__ import annotations

from .domain.errors import SnapshotError
import argparse
import json
import os
import sys
from pathlib import Path

from .bootstrap import build_service
from .adapters.json_result import JsonResultImporter




def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qwb", description="Quant Workbench local result service")
    p.add_argument("--root", default=".data/workbench", help="platform data directory")
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("import-json", help="import an engine-neutral JSON package")
    a.add_argument("path")
    a.add_argument("--source-instance", required=True)
    a.add_argument("--external-id", required=True)
    a = sub.add_parser("import-qlib", help="import a trusted local Qlib MLflow run")
    a.add_argument("--tracking-uri", required=True)
    a.add_argument("--source-instance", required=True)
    a.add_argument("--external-id", required=True, help="MLflow run ID")
    a.add_argument("--dataset-id", required=True)
    a.add_argument("--dataset-version")
    kind = a.add_mutually_exclusive_group(required=True)
    kind.add_argument("--synthetic", action="store_true")
    kind.add_argument("--real", action="store_true")
    a.add_argument("--trust-local-artifacts", action="store_true")
    a.add_argument("--config-path")
    a = sub.add_parser("list-runs")
    a.add_argument("--limit", type=int, default=20)
    a.add_argument("--cursor")
    a = sub.add_parser("show-run")
    a.add_argument("run_id")
    a = sub.add_parser("revisions")
    a.add_argument("run_id")
    a.add_argument("--limit", type=int, default=20)
    a.add_argument("--cursor")
    a = sub.add_parser("series")
    a.add_argument("run_id")
    a.add_argument("metric_id")
    a.add_argument("--revision-id")
    a.add_argument("--limit", type=int, default=2000)
    a.add_argument("--offset", type=int, default=0)
    a = sub.add_parser("compare")
    a.add_argument("metric_id")
    a.add_argument("run_ids", nargs="+")
    a.add_argument("--mode", choices=["auto","equity","metric"], default="auto")
    a = sub.add_parser("compare-table", help="one row per metric, one column per run (UI06)")
    a.add_argument("run_ids", nargs="+")
    a.add_argument("--metric-id", action="append", dest="metric_ids")
    a = sub.add_parser('research-list')
    a.add_argument('--limit', type=int, default=20)
    a.add_argument('--offset', type=int, default=0)
    a.add_argument('--query', default='')
    a = sub.add_parser('research-detail')
    a.add_argument('identity')
    a = sub.add_parser("factors", help="list registered factor panels")
    a = sub.add_parser("factor", help="show one factor and its panel metadata")
    a.add_argument("factor_id")
    a.add_argument("--panel-id")
    a = sub.add_parser("import-factor-panel", help="import one canonical factor panel (JSON file)")
    a.add_argument("path")
    a.add_argument("--source-instance", required=True)
    a.add_argument("--external-id", required=True)
    a.add_argument("--dataset-id", required=True)
    a.add_argument("--dataset-version", required=True)
    a.add_argument("--snapshot-label", required=True)
    a.add_argument("--calendar-id")
    a.add_argument("--formulation")
    a.add_argument("--source-ref")
    a = sub.add_parser("factor-analysis", help="single-factor statistics, overlap and increment")
    a.add_argument("factor_ids", nargs="+")
    a.add_argument("--horizons", default="1,5,10,20")
    a.add_argument("--analysis-version", type=int, choices=[1, 2], default=1)
    a = sub.add_parser("risk", help="performance and risk metrics for one or more runs")
    a.add_argument("run_ids", nargs="+")
    a.add_argument("--periods-per-year", type=int)
    a.add_argument("--analysis-version", type=int, choices=[1, 2], default=1)
    a.add_argument("--risk-free-rate", type=float, help="same-frequency daily decimal return (v2)")
    a.add_argument("--target-return", type=float, help="same-frequency daily decimal return (v2)")
    a = sub.add_parser("validate", help="PSR/DSR/PBO validation for one or more runs")
    a.add_argument("run_ids", nargs="+")
    a.add_argument("--horizon", type=int, default=1)
    a.add_argument("--splits", type=int, default=5)
    a.add_argument("--embargo", type=int)
    a.add_argument("--trials", type=int)
    a.add_argument("--blocks", type=int, default=8)
    a.add_argument("--analysis-version", type=int, choices=[1, 2], default=1)
    a.add_argument("--revision-id", action="append", dest="revision_ids")
    a = sub.add_parser('review')
    a.add_argument('run_id')
    a.add_argument("--revision-id")
    a = sub.add_parser("data-snapshots", help="list registered data snapshots (T05/A40)")
    a = sub.add_parser("data-snapshot", help="show one registered data snapshot")
    a.add_argument("snapshot_id")
    a = sub.add_parser("execution-catalog", help="show execution entries and their preconditions")
    a.add_argument("--refresh", action="store_true")
    a = sub.add_parser("execute", help="start one isolated research attempt")
    a.add_argument("kind")
    a.add_argument("--params", default="{}", help="JSON object with entry parameters")
    a.add_argument("--idempotency-key", required=True, help="caller generated key; repeats reuse the attempt")
    a = sub.add_parser("executions", help="list attempts")
    a.add_argument("--limit", type=int, default=20)
    a.add_argument("--cursor")
    a = sub.add_parser("execution", help="show one attempt")
    a.add_argument("attempt_id")
    a = sub.add_parser("execution-log", help="show the sanitized log tail of one attempt")
    a.add_argument("attempt_id")
    a.add_argument("--tail", type=int, default=200)
    a = sub.add_parser("cancel", help="request cancellation and wait for the confirmed process end")
    a.add_argument("attempt_id")
    a = sub.add_parser("import-attempt", help="retry automatic publication of a succeeded attempt result")
    a.add_argument("attempt_id")
    a = sub.add_parser("attempt-stats", help="attempt-level rates, durations and coverage")
    a.add_argument("--window-seconds", type=int, default=86400)
    sub.add_parser("capabilities")
    sub.add_parser("agent-status", help="show sanitized RD-Agent integration status")
    sub.add_parser("health")
    a = sub.add_parser("serve", help="start read-only API on loopback")
    a.add_argument("--port", type=int, default=8765)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        service = build_service(Path(args.root))
        if args.command == "import-json":
            importer = JsonResultImporter()
            result = service.import_package(args.source_instance, args.external_id, importer.adapter_version,
                                            importer.load(args.path))
        elif args.command == "import-qlib":
            from .adapters.qlib_mlflow import QlibMlflowImporter

            importer = QlibMlflowImporter()
            result = service.import_package(
                args.source_instance, args.external_id, importer.adapter_version,
                importer.load(tracking_uri=args.tracking_uri, external_id=args.external_id,
                              dataset_id=args.dataset_id, dataset_version=args.dataset_version,
                              synthetic=args.synthetic, trust_local_artifacts=args.trust_local_artifacts,
                              config_path=args.config_path),
            )
        elif args.command == "list-runs":
            result = service.list_runs(args.limit, args.cursor)
        elif args.command == "show-run":
            result = service.get_run(args.run_id)
        elif args.command == "revisions":
            result = service.list_revisions_page(args.run_id, args.limit, args.cursor)
        elif args.command == "series":
            result = service.get_series(args.run_id, args.metric_id, args.revision_id, args.limit, args.offset)
        elif args.command == "compare":
            result = service.compare(args.run_ids, args.metric_id, args.mode)
        elif args.command == "compare-table":
            result = service.compare_table(args.run_ids, args.metric_ids)
        elif args.command == 'research-list':
            result = service.research_list(args.limit, args.offset, args.query)
        elif args.command == 'research-detail':
            result = service.research_detail(args.identity)
        elif args.command == 'factors':
            result = service.list_factors()
        elif args.command == 'factor':
            result = service.factor_detail(args.factor_id, args.panel_id)
        elif args.command == 'import-factor-panel':
            payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("factor panel file must contain a JSON object")
            identity = {
                "source_instance_id": args.source_instance, "external_id": args.external_id,
                "name": payload.get("name") or args.external_id,
                "definition": {"formulation": args.formulation, "source_ref": args.source_ref},
                "dataset": {"id": args.dataset_id, "version": args.dataset_version,
                            "snapshot_label": args.snapshot_label},
                "calendar_id": args.calendar_id or payload.get("calendar_id"),
                "provenance": {"import": "cli", "source_ref": args.source_ref},
            }
            result = service.import_factor_panel(identity, payload)
        elif args.command == 'factor-analysis':
            horizons = [int(value) for value in str(args.horizons).split(',') if value.strip()]
            result = service.factor_analysis(args.factor_ids, horizons, analysis_version=args.analysis_version)
            if args.analysis_version == 1:
                print("旧定义，未满足当前纠正合同；可使用 --analysis-version 2", file=sys.stderr)
        elif args.command == 'risk':
            result = service.risk_report(args.run_ids, args.periods_per_year,
                                        analysis_version=args.analysis_version,
                                        risk_free_rate=args.risk_free_rate, target_return=args.target_return)
            if args.analysis_version == 1:
                print("旧定义，未满足当前纠正合同；可使用 --analysis-version 2", file=sys.stderr)
        elif args.command == 'validate':
            result = service.strategy_validation(args.run_ids, args.horizon, args.splits,
                                                 args.embargo, args.trials, args.blocks,
                                                 analysis_version=args.analysis_version,
                                                 revision_ids=args.revision_ids)
        elif args.command == 'data-snapshots':
            result = service.data_snapshots()
        elif args.command == 'data-snapshot':
            snapshot = service.data_snapshot(args.snapshot_id)
            if snapshot is None:
                print(f"snapshot not available: {args.snapshot_id}", file=sys.stderr)
                return 1
            result = snapshot
        elif args.command == 'review':
            result = service.review(args.run_id, args.revision_id)
        elif args.command == 'execution-catalog':
            result = service.execution_catalog(args.refresh)
        elif args.command == 'execute':
            params = json.loads(args.params)
            if not isinstance(params, dict):
                raise ValueError("--params must be a JSON object")
            result = service.submit_execution(args.kind, params, args.idempotency_key, None)
        elif args.command == 'executions':
            result = service.executions(args.limit, args.cursor)
        elif args.command == 'execution':
            result = service.execution(args.attempt_id)
        elif args.command == 'execution-log':
            result = service.execution_log(args.attempt_id, args.tail)
        elif args.command == 'cancel':
            result = service.cancel_execution(args.attempt_id)
        elif args.command == 'import-attempt':
            result = service.import_execution(args.attempt_id)
        elif args.command == 'attempt-stats':
            result = service.execution_stats(args.window_seconds)
        elif args.command == "capabilities":
            result = service.capabilities()
        elif args.command == "agent-status":
            result = service.rdagent_status()
        elif args.command == "health":
            result = service.health()
        else:
            from .api import create_app
            import uvicorn

            if not 1 <= args.port <= 65535:
                raise ValueError("port must be between 1 and 65535")
            uvicorn.run(create_app(service), host="127.0.0.1", port=args.port)
            return 0
        if result is None:
            raise LookupError("not found")
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 0
    except SnapshotError as exc:
        print(json.dumps({'code': exc.code, 'message': str(exc), 'details': exc.details}), file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError, LookupError) as exc:
        print(json.dumps({"code": "command_failed", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
