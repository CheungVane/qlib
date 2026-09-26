"""Read-only HTTP boundary over the shared application service."""

from __future__ import annotations

import uuid
import time
from typing import Any

from .telemetry import RequestTelemetry

from .application import WorkbenchService
from .metrics import summarize


def create_app(service: WorkbenchService):
    import json
    from importlib.resources import files

    from fastapi import Body, FastAPI, HTTPException, Query, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse, FileResponse

    from urllib.parse import urlsplit

    from .dashboard import validate_dashboard
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
    def revisions(run_id: str):
        if service.get_run(run_id) is None:
            raise HTTPException(404, "run not found")
        return {"items": service.list_revisions(run_id)}

    @app.get("/v1/runs/{run_id}/revisions/{revision_id}")
    def revision(run_id: str, revision_id: str):
        result = service.get_revision(run_id, revision_id)
        if result is None:
            raise HTTPException(404, "revision not found")
        return {k: v for k, v in result.items() if k != "result"} | {
            "run": result["result"]["run"],
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
