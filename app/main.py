"""VOXORA AI Engine - FastAPI application factory."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.health import router as health_router
from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers

DESCRIPTION = """
Self-hosted AI voice platform: **voice cloning, text-to-speech, speech-to-text, translation and dubbing**
behind one REST API. All models run on your own hardware.

### Authentication
Send your API key in the `X-API-Key` header (or `Authorization: Bearer <key>`).

### Asynchronous jobs
Long operations return `202` with a `job_id`. Poll `GET /api/v1/jobs/{job_id}` until `status` is
`completed` or `failed` (`queued` -> `processing` -> `completed` | `failed`; `progress` is 0-100).

### Errors
Every error uses `{"error": {"code", "message", "details"}, "request_id"}`. If a model is not installed
the API answers **503 `AI_ENGINE_NOT_CONFIGURED`** with a hint on how to install it - it never fakes output.

### Voice cloning and consent
Cloning requires `consent_confirmed=true` from the person whose voice is sampled. With the default
XTTS-v2 engine a voice is a *zero-shot profile* (reference audio + cached latents), not a fine-tuned model.
"""


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        for d in (settings.data_dir, settings.storage_root, settings.models_root, settings.tmp_root):
            d.mkdir(parents=True, exist_ok=True)
        if settings.auto_create_tables:
            from app.database.session import create_all_tables

            create_all_tables()
        if settings.job_backend == "local":
            from app.workers.executor import get_executor
            from app.workers.runner import recover_jobs

            recover_jobs(get_executor().submit)
        yield
        if settings.job_backend != "celery":
            from app.workers.executor import reset_executor

            reset_executor()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["X-API-Key", "Authorization", "Content-Type"],
            expose_headers=["X-Request-ID", "Retry-After"],
            max_age=600,
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID", "")[:64] or uuid.uuid4().hex
        # Cheap early rejection of oversized bodies (the real limit is enforced while streaming to disk).
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_upload_bytes + 5 * 1024 * 1024:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "FILE_TOO_LARGE",
                        "message": f"The request exceeds the {settings.max_upload_mb} MB upload limit.",
                        "details": {},
                    },
                    "request_id": request.state.request_id,
                },
            )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": settings.app_name, "version": __version__, "docs": "/docs", "health": "/health/live"}

    return app


app = create_app()
