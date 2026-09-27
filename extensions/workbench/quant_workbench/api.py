"""Read-only HTTP boundary over the shared application service."""

from __future__ import annotations

import uuid
import time
from typing import Any

from .telemetry import RequestTelemetry

from .application import WorkbenchService, display_run_title
from .metrics import summarize


def create_app(service: WorkbenchService):
    import json
    from importlib.resources import files

    from fastapi import Body, FastAPI, HTTPException, Query, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse, FileResponse

    from urllib.parse import urlsplit

    from .dashboard import QUERY_IDS, validate_dashboard
    from .execution import ExecutionError

    # ``from __future__ import annotations`` turns annotations into strings; FastAPI resolves
    # them against module globals, so register the lazily imported request type explicitly.
    globals().setdefault("Request", Request)

    def require_same_origin(request: Request) -> None:
        """OPS01: browser writes must come from the workbench origin."""
        site = (request.headers.get("sec-fetch-site") or "").strip().lower()
        origin = (request.headers.get("origin") or "").strip()
        if site == "cross-site":
            raise HTTPException(403, "cross-site write requests are rejected")
        if origin:
            if urlsplit(origin).netloc != (request.headers.get("host") or ""):
                raise HTTPException(403, "write requests must come from the workbench origin")

    app = FastAPI(title="Quant Workbench", version="0.1.0")

    @app.exception_handler(ExecutionError)
    async def execution_error(request: Request, exc: ExecutionError):
        rid = getattr(request.state, "request_id", uuid.uuid4().hex)
        return JSONResponse(status_code=exc.status_code,
                            content={"code": exc.code, "message": str(exc), "request_id": rid,
                                     "details": exc.as_details()})

    @app.exception_handler(LookupError)
    async def lookup_error(request: Request, exc: LookupError):
        rid = getattr(request.state, "request_id", uuid.uuid4().hex)
        return JSONResponse(status_code=404,
                            content={"code": "not_found", "message": str(exc), "request_id": rid,
                                     "details": {}})
    telemetry = RequestTelemetry()
    ui_root = files("quant_workbench.ui")

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        started = time.perf_counter()
        rid = uuid.uuid4().hex
        request.state.request_id = rid
        try:
            response = await call_next(request)
        except ValueError as exc:
            response = JSONResponse(status_code=400, content={"code": "invalid_request", "message": str(exc),
                                                              "request_id": rid, "details": {}})
        except Exception:
            response = JSONResponse(status_code=500, content={'code':'internal_error','message':'服务处理失败，请凭 request_id 排查服务日志','request_id':rid,'details':{}})
            import logging
            logging.getLogger(__name__).exception('API failure request_id=%s', rid)
        if request.url.path.startswith('/v1/') and request.url.path not in {'/v1/health','/v1/observability','/v1/widgets/api.error_rate.5m'}:
            telemetry.record(response.status_code, (time.perf_counter()-started)*1000)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        rid = getattr(request.state, "request_id", uuid.uuid4().hex)
        return JSONResponse(status_code=exc.status_code,
                            content={"code": "not_found" if exc.status_code == 404 else "http_error",
                                     "message": str(exc.detail), "request_id": rid, "details": {}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", uuid.uuid4().hex)
        return JSONResponse(status_code=422,
                            content={"code": "invalid_request", "message": "request validation failed",
                                     "request_id": rid, "details": {"errors": exc.errors()}})

    @app.get('/v1/observability')
    def observability():
        # OBS01/EXEC10: HTTP process telemetry and attempt-level rates are separate blocks.
        return {**telemetry.snapshot(), "attempts": service.execution_stats()}

    @app.get("/v1/health")
    def health():
        return service.health()

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(ui_root / "index.html"), headers={"Cache-Control": "no-store"})

    @app.get("/ui/{asset}", include_in_schema=False)
    def ui_asset(asset: str):
        if asset not in {"app.js", "style.css"}:
            raise HTTPException(404, "asset not found")
        return FileResponse(str(ui_root / asset), headers={"Cache-Control": "no-store"})

    @app.get('/v1/provenance/capabilities')
    def provenance_capabilities():
        return {'items':service.provenance_capabilities()}

    @app.get("/v1/capabilities")
    def capabilities():
        return service.capabilities()

    @app.get("/v1/agents/rdagent")
    def rdagent_status():
        return service.rdagent_status()

    @app.get('/v1/research')
    def research_list(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), query: str = Query('', max_length=200)):
        return service.research_list(limit, offset, query)

    @app.get('/v1/research/{identity}')
    def research_detail(identity: str):
        result = service.research_detail(identity)
        if result is None: raise HTTPException(404, 'research not found')
        return result

    @app.get("/v1/factors")
    def factors():
        return service.list_factors()

    @app.get("/v1/factors/{factor_id}")
    def factor_detail(factor_id: str, panel_id: str | None = None):
        result = service.factor_detail(factor_id, panel_id)
        if result is None:
            raise HTTPException(404, "factor not found")
        return result

    @app.post("/v1/factors")
    def create_factor(request: Request, payload: dict[str, Any] = Body(...)):
        """Import one canonical factor panel (write endpoint, same-origin)."""
        require_same_origin(request)
        unknown = set(payload) - {"factor", "panel"}
        if unknown:
            raise HTTPException(400, f"unknown request fields: {', '.join(sorted(unknown))}")
        identity = payload.get("factor")
        panel = payload.get("panel")
        if not isinstance(identity, dict) or not isinstance(panel, dict):
            raise HTTPException(400, "factor and panel objects are required")
        return service.import_factor_panel(identity, panel)

    @app.get("/v1/factor-analysis")
    def factor_analysis(factor_id: list[str] = Query(...), horizon: list[int] | None = Query(None),
                        analysis_version: int = Query(1, ge=1, le=2)):
        return service.factor_analysis(factor_id, horizon, analysis_version=analysis_version)

    @app.get("/v1/validation")
    def validation(run_id: list[str] = Query(...), horizon: int = Query(1, ge=1, le=60),
                   splits: int = Query(5, ge=2, le=20), embargo: int | None = Query(None, ge=0, le=60),
                   trials: int | None = Query(None, ge=2, le=1000), blocks: int = Query(8, ge=4, le=12)):
        """VALIDATION U20: PSR/DSR per run, PBO across runs and the leakage summary."""
        return service.strategy_validation(run_id, horizon, splits, embargo, trials, blocks)

    @app.get("/v1/risk")
    def risk(run_id: list[str] = Query(...), periods_per_year: int | None = Query(None, ge=1, le=1000),
             analysis_version: int = Query(1, ge=1, le=2),
             risk_free_rate: float | None = Query(None), target_return: float | None = Query(None)):
        """U22: performance and risk metrics for one or more recorded runs."""
        return service.risk_report(run_id, periods_per_year, analysis_version=analysis_version,
                                   risk_free_rate=risk_free_rate, target_return=target_return)

    @app.get("/v1/attention")
    def attention(limit: int = Query(20, ge=1, le=100)):
        """UI07:待处理事项（失败执行、未入库结果、探针结果、取消请求中）。"""
        return service.attention(limit)

    @app.get('/v1/runs/{run_id}/review')
    def review(run_id: str, revision_id: str | None = None):
        result = service.review(run_id, revision_id)
        if result is None: raise HTTPException(404, 'run not found')
        return result

    @app.get("/v1/dashboards/overview")
    def dashboard():
        data = json.loads((ui_root / "dashboard.default.json").read_text(encoding="utf-8"))
        return validate_dashboard(data)

    @app.get("/v1/widgets/{query_id}")
    def widget(query_id: str):
        if query_id == "runs.latest":
            result = service.list_runs(limit=10)
            return {"query_id": query_id, "availability": "available" if result["items"] else "empty",
                    "data": result}
        if query_id == "data.freshness":
            return {"query_id": query_id, "availability": "not_recorded", "data": None,
                    "reason": "数据目录尚未接入"}
        if query_id == "api.error_rate.5m":
            stats=telemetry.snapshot()
            return {"query_id":query_id, "availability":stats['availability'], "data":stats}
        if query_id in QUERY_IDS:
            return {"query_id": query_id, "availability": "unsupported", "data": None,
                    "reason": "该查询已在面板清单登记但尚未实现，界面不得显示为 0"}
        raise HTTPException(404, "query not registered")

    @app.get("/v1/runs")
    def runs(limit: int = Query(20, ge=1, le=100), cursor: str | None = None):
        return service.list_runs(limit, cursor)

    @app.get("/v1/runs/{run_id}")
    def run(run_id: str):
        result = service.get_run(run_id)
        if result is None:
            raise HTTPException(404, "run not found")
        return result

    @app.get("/v1/runs/{run_id}/revisions")
    def revisions(run_id: str, limit: int = Query(20, ge=1, le=100), cursor: str | None = None):
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return service.list_revisions_page(run_id, limit, cursor)

    @app.get("/v1/runs/{run_id}/revisions/{revision_id}")
    def revision(run_id: str, revision_id: str):
        result = service.get_revision(run_id, revision_id)
        if result is None:
            raise HTTPException(404, "revision not found")
        return {k: v for k, v in result.items() if k != "result"} | {
            "run": result["result"]["run"],
            "display_title": display_run_title(result["result"]["run"]),
            "series": [{k: v for k, v in entry.items() if k != "points"} | {"point_count": len(entry["points"]), "summary": summarize(entry)}
                       for entry in result["result"]["series"]],
            "evidence": result["result"].get("evidence", {}),
        }

    @app.get("/v1/runs/{run_id}/series")
    def series(run_id: str, metric_id: str, revision_id: str | None = None,
               limit: int = Query(2000, ge=1, le=2000), offset: int = Query(0, ge=0)):
        result = service.get_series(run_id, metric_id, revision_id, limit, offset)
        if result is None:
            raise HTTPException(404, "series not found")
        return result

    @app.get("/v1/compare")
    def compare(run_id: list[str] = Query(...), metric_id: str = Query(...), mode: str = Query("auto")):
        return service.compare(run_id, metric_id, mode)

    @app.get("/v1/compare/table")
    def compare_table(run_id: list[str] = Query(...), metric_id: list[str] | None = Query(None)):
        """UI06: one row per metric, one column per run, best/worst computed server-side."""
        return service.compare_table(run_id, metric_id)

    @app.get("/v1/executions/catalog")
    def executions_catalog(refresh: bool = False):
        return service.execution_catalog(refresh)

    @app.get("/v1/executions")
    def executions(limit: int = Query(20, ge=1, le=100), cursor: str | None = None):
        return service.executions(limit, cursor)

    @app.get("/v1/executions/{attempt_id}")
    def execution(attempt_id: str):
        result = service.execution(attempt_id)
        if result is None:
            raise HTTPException(404, "attempt not found")
        return result

    @app.get("/v1/executions/{attempt_id}/log")
    def execution_log(attempt_id: str, tail: int = Query(200, ge=1, le=1000)):
        return service.execution_log(attempt_id, tail)

    @app.post("/v1/executions")
    def create_execution(request: Request, payload: dict[str, Any] = Body(...)):
        require_same_origin(request)
        unknown = set(payload) - {"kind", "params", "idempotency_key"}
        if unknown:
            raise HTTPException(400, f"unknown request fields: {', '.join(sorted(unknown))}")
        idempotency_key = payload.get("idempotency_key") or request.headers.get("idempotency-key")
        result = service.submit_execution(payload.get("kind"), payload.get("params") or {}, idempotency_key,
                                          getattr(request.state, "request_id", None))
        return JSONResponse(status_code=201 if result["created"] else 200, content=result)

    @app.post("/v1/executions/{attempt_id}/cancel")
    def cancel_execution(attempt_id: str, request: Request):
        require_same_origin(request)
        return service.cancel_execution(attempt_id)

    @app.post("/v1/executions/{attempt_id}/import")
    def import_execution(attempt_id: str, request: Request):
        """EXEC12 explicit retry; only an attempt without a successful receipt is imported."""
        require_same_origin(request)
        return service.import_execution(attempt_id)

    return app
