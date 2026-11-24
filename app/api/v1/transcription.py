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
from app.services import transcription_service
from app.services.job_service import dispatch, get_job
from app.storage.base import StorageBackend
from app.utils import subtitles

router = APIRouter(prefix="/transcription", tags=["Speech to text"])


@router.post(
    "",
    response_model=JobAccepted,
    status_code=202,
    summary="Transcribe audio or video (WAV, MP3, M4A, FLAC, MP4, ...)",
    dependencies=[Depends(heavy_rate_limit)],
)
def create_transcription(
    file: UploadFile | None = File(None, description="Media file to transcribe."),
    file_id: str | None = Form(None, description="Alternatively: id of a file you already uploaded."),
    language: str | None = Form(None, description="Spoken language, or omit/'auto' to detect."),
    project_id: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
    settings: Settings = Depends(get_settings_dep),
    registry: EngineRegistry = Depends(get_registry_dep),
) -> JobAccepted:
    job = transcription_service.submit_transcription(
        db, storage, settings, registry, user, file, file_id, language, project_id
    )
    db.commit()
    dispatch(job.id)
    db.refresh(job)
    return accepted(job, f"/api/v1/transcription/{job.id}")


@router.get(
    "/{job_id}",
    response_model=JobOut,
    summary="Get a transcription (text, detected language, timestamped segments, status)",
)
def get_transcription(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobOut:
    return JobOut.from_job(get_job(db, user, job_id, "transcription"))


@router.get("/{job_id}/export", summary="Export the transcript as TXT, SRT or VTT")
def export_transcription(
    job_id: str,
    fmt: Literal["txt", "srt", "vtt"] = Query("txt", alias="format"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = get_job(db, user, job_id, "transcription")
    if job.status != "completed" or not job.result:
        raise JobNotReady(f"The job is '{job.status}'.", details={"status": job.status})
    body = subtitles.export(job.result["segments"], fmt)
    return Response(
        content=body,
        media_type=subtitles.EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="transcript-{job.id[-8:]}.{fmt}"'},
    )
