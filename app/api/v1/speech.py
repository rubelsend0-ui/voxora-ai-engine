from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.ai_engine.registry import EngineRegistry
from app.api.deps import (
    file_response,
    get_current_user,
    get_db,
    get_registry_dep,
    get_settings_dep,
    get_storage_dep,
    heavy_rate_limit,
)
from app.core.config import Settings
from app.core.errors import JobNotReady
from app.models.file import FileAsset
from app.models.user import User
from app.schemas.job import JobAccepted, JobOut, accepted
from app.schemas.speech import SpeechRequest
from app.services import speech_service
from app.services.common import get_owned
from app.services.job_service import dispatch, get_job
from app.storage.base import StorageBackend

router = APIRouter(prefix="/speech", tags=["Text to speech"])


@router.post(
    "/generate",
    response_model=JobAccepted,
    status_code=202,
    summary="Generate speech from text with one of your voices",
    dependencies=[Depends(heavy_rate_limit)],
)
def generate_speech(
    body: SpeechRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    registry: EngineRegistry = Depends(get_registry_dep),
) -> JobAccepted:
    job = speech_service.submit_speech(db, settings, registry, user, body)
    db.commit()
    dispatch(job.id)
    db.refresh(job)
    return accepted(job, f"/api/v1/speech/{job.id}")


@router.get("/{job_id}", response_model=JobOut, summary="Get a speech job (status, progress, result)")
def get_speech(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobOut:
    job = get_job(db, user, job_id, "speech")
    return JobOut.from_job(job, extra_result={"download_url": f"/api/v1/speech/{job.id}/download"})


@router.get("/{job_id}/download", response_class=FileResponse, summary="Download the generated audio")
def download_speech(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
) -> FileResponse:
    job = get_job(db, user, job_id, "speech")
    if job.status != "completed" or not job.result:
        raise JobNotReady(f"The job is '{job.status}'.", details={"status": job.status})
    asset = get_owned(db, FileAsset, job.result["file_id"], user.id, "File")
    return file_response(storage, asset)
