from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.ai_engine.registry import EngineRegistry
from app.api.deps import (
    get_current_user,
    get_db,
    get_registry_dep,
    get_settings_dep,
    get_storage_dep,
    heavy_rate_limit,
)
from app.core.config import Settings
from app.core.errors import JobNotReady
from app.models.user import User
from app.schemas.job import JobAccepted, JobOut, accepted
from app.schemas.misc import TextTranslationRequest, TextTranslationResponse
from app.services import translation_service
from app.services.job_service import dispatch, get_job
from app.storage.base import StorageBackend
from app.utils import subtitles

router = APIRouter(prefix="/translation", tags=["Translation"])


@router.post(
    "/text",
    response_model=TextTranslationResponse,
    summary="Translate text (synchronous)",
    dependencies=[Depends(heavy_rate_limit)],
)
def translate_text(
    body: TextTranslationRequest,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings_dep),
    registry: EngineRegistry = Depends(get_registry_dep),
) -> TextTranslationResponse:
    return translation_service.translate_text(registry, settings, body)


@router.post(
    "/audio",
    response_model=JobAccepted,
    status_code=202,
    summary="Translate spoken audio: transcribe, then translate each segment (text output)",
    dependencies=[Depends(heavy_rate_limit)],
)
def translate_audio(
    file: UploadFile | None = File(None),
    file_id: str | None = Form(None),
    source_language: str | None = Form(None, description="Spoken language or omit/'auto' to detect."),
    target_language: str = Form(...),
    project_id: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
    settings: Settings = Depends(get_settings_dep),
    registry: EngineRegistry = Depends(get_registry_dep),
) -> JobAccepted:
    job = translation_service.submit_audio_translation(
        db, storage, settings, registry, user, file, file_id, source_language, target_language, project_id
    )
    db.commit()
    dispatch(job.id)
    db.refresh(job)
    return accepted(job, f"/api/v1/translation/{job.id}")


@router.get("/{job_id}", response_model=JobOut, summary="Get an audio-translation job")
def get_translation(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobOut:
    return JobOut.from_job(get_job(db, user, job_id, "translation"))


@router.get("/{job_id}/export", summary="Export the translated (or source) transcript as TXT, SRT or VTT")
def export_translation(
    job_id: str,
    fmt: Literal["txt", "srt", "vtt"] = Query("srt", alias="format"),
    track: Literal["translated", "source"] = "translated",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = get_job(db, user, job_id, "translation")
    if job.status != "completed" or not job.result:
        raise JobNotReady(f"The job is '{job.status}'.", details={"status": job.status})
    body = subtitles.export(job.result[track]["segments"], fmt)
    return Response(
        content=body,
        media_type=subtitles.EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{track}-{job.id[-8:]}.{fmt}"'},
    )
