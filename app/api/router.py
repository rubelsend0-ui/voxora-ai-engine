from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import rate_limit
from app.api.v1 import dubbing, files, jobs, projects, speech, system, transcription, translation, voices
from app.schemas.common import ErrorResponse

api_router = APIRouter(
    dependencies=[Depends(rate_limit)],  # also enforces authentication on every /api/v1 route
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        503: {"model": ErrorResponse, "description": "AI_ENGINE_NOT_CONFIGURED: a required model is not installed"},
    },
)
for module in (system, voices, speech, transcription, translation, dubbing, jobs, projects, files):
    api_router.include_router(module.router)
