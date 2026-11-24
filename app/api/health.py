"""Unauthenticated health endpoints for load balancers, Docker and Kubernetes."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.ai_engine.registry import get_registry
from app.database.session import get_engine
from app.storage.local import get_storage

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live", summary="Liveness: the process is up")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness: database + storage reachable; reports which AI engines are usable")
def ready():
    checks: dict[str, bool] = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False
    try:
        checks["storage"] = get_storage().healthy()
    except Exception:
        checks["storage"] = False
    engines = {kind: st.available for kind, st in get_registry().statuses().items()}
    ok = all(checks.values())
    body = {"status": "ready" if ok else "unavailable", "checks": checks, "engines": engines}
    return JSONResponse(status_code=200 if ok else 503, content=body)
