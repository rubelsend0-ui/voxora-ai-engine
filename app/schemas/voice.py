from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.voice import Voice
from app.schemas.job import JobError, JobStatus


class VoiceProfile(BaseModel):
    type: str | None = None
    engine: str | None = None
    model: str | None = None
    requires_reference_audio: bool = True
    notes: str


class ConsentOut(BaseModel):
    type: str
    holder_name: str
    confirmed_at: datetime | str
    version: str


class VoiceOut(BaseModel):
    voice_id: str
    name: str
    description: str | None = None
    language: str | None = None
    status: str
    source: str
    profile: VoiceProfile | None = None
    duration_seconds: float | None = None
    quality: dict[str, Any] | None = None
    consent: ConsentOut
    error: JobError | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_voice(cls, v: Voice) -> VoiceOut:
        profile = None
        if v.status == "ready":
            profile = VoiceProfile(
                type=v.profile_type,
                engine=v.engine,
                model=v.model_id,
                requires_reference_audio=v.requires_reference_audio,
                notes=(
                    "Zero-shot voice profile: the stored reference audio is used together with cached "
                    "conditioning data at synthesis time. It is not a fine-tuned model of the speaker."
                    if v.requires_reference_audio
                    else "Self-contained voice profile."
                ),
            )
        c = v.consent or {}
        return cls(
            voice_id=v.id,
            name=v.name,
            description=v.description,
            language=v.language,
            status=v.status,
            source=v.source,
            profile=profile,
            duration_seconds=v.duration_seconds,
            quality=v.quality,
            consent=ConsentOut(
                type=c.get("type", "unknown"),
                holder_name=c.get("holder_name", ""),
                confirmed_at=c.get("confirmed_at", ""),
                version=c.get("version", ""),
            ),
            error=JobError(code=v.error_code or "UNKNOWN", message=v.error_message) if v.status == "failed" else None,
            created_at=v.created_at,
            updated_at=v.updated_at,
        )


class VoiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class VoiceCloneResponse(BaseModel):
    voice_id: str
    job_id: str
    status: str  # voice status: processing | ready | failed
    job_status: JobStatus
    status_url: str
    voice: VoiceOut
