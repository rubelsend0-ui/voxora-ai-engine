from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
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
from app.services import dubbing_service
from app.services.common import get_owned
from app.services.job_service import dispatch, get_job
from app.storage.base import StorageBackend
from app.utils import subtitles

router = APIRouter(prefix="/dubbing", tags=["AI dubbing"])


@router.post(
    "",
    response_model=JobAccepted,
    status_code=202,
    summary="Dub a video/audio file into another language using one of your voices",
    dependencies=[Depends(heavy_rate_limit)],
)
def create_dubbing(
    input_file: UploadFile | None = File(None, description="Video or audio file to dub."),
    file_id: str | None = Form(None, description="Alternatively: id of a file you already uploaded."),
    source_language: str | None = Form(None, description="Spoken language, or omit/'auto' to detect."),
    target_language: str = Form(..., description="Language to dub into, e.g. 'es'."),
    voice_id: str = Form(..., description="One of your ready voices."),
    output_format: str | None = Form(None, description="mp4 (video input), or wav/mp3/flac/ogg/m4a. Default: mp4/mp3."),
    original_audio_volume: float = Form(
        0.0, ge=0.0, le=1.0, description="0 = drop original audio (default). >0 mixes the whole original track under the dub."
    ),
    project_id: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
    settings: Settings = Depends(get_settings_dep),
    registry: EngineRegistry = Depends(get_registry_dep),
) -> JobAccepted:
    """Pipeline: extract audio -> transcribe -> translate -> synthesize with the chosen voice -> fit timing ->
    combine with the video -> export. **No lip-sync**: timing is fitted per segment only. See `limitations`
    in the job result for everything this pipeline does not do."""
    job = dubbing_service.submit_dubbing(
        db, storage, settings, registry, user, input_file, file_id,
        source_language=source_language, target_language=target_language, voice_id=voice_id,
        output_format=output_format, original_audio_volume=original_audio_volume, project_id=project_id,
    )
    db.commit()
    dispatch(job.id)
    db.refresh(job)
    return accepted(job, f"/api/v1/dubbing/{job.id}")


@router.get("/{job_id}", response_model=JobOut, summary="Get a dubbing job (progress, segments, sync report, warnings)")
def get_dubbing(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobOut:
    job = get_job(db, user, job_id, "dubbing")
    return JobOut.from_job(job, extra_result={"download_url": f"/api/v1/dubbing/{job.id}/download"})


@router.get("/{job_id}/download", response_class=FileResponse, summary="Download the dubbed video/audio")
def download_dubbing(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
) -> FileResponse:
    job = get_job(db, user, job_id, "dubbing")
    if job.status != "completed" or not job.result:
        raise JobNotReady(f"The job is '{job.status}'.", details={"status": job.status})
    asset = get_owned(db, FileAsset, job.result["file_id"], user.id, "File")
    return file_response(storage, asset)


@router.get("/{job_id}/subtitles", summary="Subtitles for the dubbed track (timing as placed in the dub)")
def dubbing_subtitles(
    job_id: str,
    fmt: Literal["srt", "vtt", "txt"] = Query("srt", alias="format"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    job = get_job(db, user, job_id, "dubbing")
    if job.status != "completed" or not job.result:
        raise JobNotReady(f"The job is '{job.status}'.", details={"status": job.status})
    body = subtitles.export(job.result["translated_segments"], fmt)
    return Response(
        content=body,
        media_type=subtitles.EXPORT_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="dub-{job.id[-8:]}.{fmt}"'},
    )
