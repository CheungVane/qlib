"""CLI boundary; it uses the same service methods as the HTTP API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .adapters.json_result import JsonResultImporter
from .application import WorkbenchService
from .adapters.rdagent_status import RDAgentStatusProvider
from .storage import LocalResultRepository
from .research import ResearchSnapshots


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
    a = sub.add_parser("series")
    a.add_argument("run_id")
    a.add_argument("metric_id")
    a.add_argument("--revision-id")
    a.add_argument("--limit", type=int, default=2000)
    a.add_argument("--offset", type=int, default=0)
    a = sub.add_parser("compare")
    a.add_argument("metric_id")
    a.add_argument("run_ids", nargs="+")
    a = sub.add_parser('research-list')
    a.add_argument('--limit', type=int, default=20)
    a.add_argument('--offset', type=int, default=0)
    a.add_argument('--query', default='')
    a = sub.add_parser('research-detail')
    a.add_argument('identity')
    a = sub.add_parser('review')
    a.add_argument('run_id')
    sub.add_parser("capabilities")
    sub.add_parser("agent-status", help="show sanitized RD-Agent integration status")
    sub.add_parser("health")
    a = sub.add_parser("serve", help="start read-only API on loopback")
    a.add_argument("--port", type=int, default=8765)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        agent_root = os.environ.get("QWB_RDAGENT_ROOT")
        observer = RDAgentStatusProvider(agent_root) if agent_root else None
        service = WorkbenchService(LocalResultRepository(Path(args.root)), observer, ResearchSnapshots(Path(args.root) / "research"))
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
            result = {"items": service.list_revisions(args.run_id)}
        elif args.command == "series":
            result = service.get_series(args.run_id, args.metric_id, args.revision_id, args.limit, args.offset)
        elif args.command == "compare":
            result = service.compare(args.run_ids, args.metric_id)
        elif args.command == 'research-list':
            result = service.research_list(args.limit, args.offset, args.query)
        elif args.command == 'research-detail':
            result = service.research_detail(args.identity)
        elif args.command == 'review':
            result = service.review(args.run_id)
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
    except (OSError, RuntimeError, ValueError, LookupError) as exc:
        print(json.dumps({"code": "command_failed", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
