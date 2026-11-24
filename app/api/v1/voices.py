from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.ai_engine.registry import EngineRegistry
from app.api.deps import (
    client_ip,
    get_current_user,
    get_db,
    get_registry_dep,
    get_settings_dep,
    get_storage_dep,
    heavy_rate_limit,
    pagination,
)
from app.core.config import Settings
from app.models.user import User
from app.schemas.common import Page
from app.schemas.voice import VoiceCloneResponse, VoiceOut, VoiceUpdate
from app.services import voice_service
from app.services.job_service import dispatch
from app.storage.base import StorageBackend

router = APIRouter(prefix="/voices", tags=["Voices"])


@router.post(
    "/clone",
    response_model=VoiceCloneResponse,
    status_code=202,
    summary="Clone a voice from a recorded or uploaded sample",
    dependencies=[Depends(heavy_rate_limit)],
)
@router.post(
    "",
    response_model=VoiceCloneResponse,
    status_code=202,
    summary="Create a voice (alias of /voices/clone)",
    dependencies=[Depends(heavy_rate_limit)],
)
def clone_voice(
    request: Request,
    file: UploadFile = File(..., description="Voice sample: wav, mp3, m4a, flac, ogg, opus, aac, webm, 3gp, amr."),
    name: str = Form(..., max_length=120),
    description: str | None = Form(None, max_length=1000),
    language: str | None = Form(None, description="Language spoken in the sample (optional)."),
    source: Literal["recorded", "uploaded"] = Form("uploaded"),
    consent_confirmed: bool = Form(False, description="Must be true: the speaker explicitly consents to cloning."),
    consent_type: Literal["self", "authorized_third_party"] = Form("self"),
    consent_holder_name: str = Form("", description="Name of the person whose voice this is."),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
    settings: Settings = Depends(get_settings_dep),
    registry: EngineRegistry = Depends(get_registry_dep),
) -> VoiceCloneResponse:
    """Validates consent, format, duration and signal quality immediately (4xx on failure), then builds the
    voice profile in a background job. Poll `GET /api/v1/jobs/{job_id}` or `GET /api/v1/voices/{voice_id}`
    until the voice status is `ready`."""
    voice, job = voice_service.create_voice(
        db, storage, settings, registry, user, file,
        name=name, description=description, language=language, source=source,
        consent_confirmed=consent_confirmed, consent_type=consent_type,
        consent_holder_name=consent_holder_name, client_ip=client_ip(request),
    )
    db.commit()
    dispatch(job.id)
    db.refresh(voice)
    db.refresh(job)
    return VoiceCloneResponse(
        voice_id=voice.id,
        job_id=job.id,
        status=voice.status,
        job_status=job.status,  # type: ignore[arg-type]
        status_url=f"/api/v1/jobs/{job.id}",
        voice=VoiceOut.from_voice(voice),
    )


@router.get("", response_model=Page[VoiceOut], summary="List your voices")
def list_voices(
    status: Literal["processing", "ready", "failed"] | None = None,
    page: tuple[int, int] = Depends(pagination),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[VoiceOut]:
    limit, offset = page
    rows, total = voice_service.list_voices(db, user, status, limit, offset)
    return Page[VoiceOut](items=[VoiceOut.from_voice(v) for v in rows], total=total, limit=limit, offset=offset)


@router.get("/{voice_id}", response_model=VoiceOut, summary="Get a voice")
def get_voice(voice_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> VoiceOut:
    return VoiceOut.from_voice(voice_service.get_voice(db, user, voice_id))


@router.patch("/{voice_id}", response_model=VoiceOut, summary="Rename / re-describe a voice")
def update_voice(
    voice_id: str, body: VoiceUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> VoiceOut:
    voice = voice_service.update_voice(db, user, voice_id, body.name, body.description)
    db.commit()
    return VoiceOut.from_voice(voice)


@router.delete(
    "/{voice_id}",
    status_code=204,
    response_class=Response,
    summary="Delete a voice and its stored reference audio/profile",
)
def delete_voice(
    voice_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
) -> Response:
    voice_service.delete_voice(db, storage, user, voice_id)
    db.commit()
    return Response(status_code=204)
