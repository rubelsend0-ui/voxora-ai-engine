"""Voice library + voice cloning pipeline.

What "cloning" means here (be honest in the API and docs): with the default XTTS-v2 adapter a
voice profile is the processed reference recording plus cached conditioning latents. It is a
zero-shot profile, not a fine-tuned model, and the reference audio is needed at synthesis time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_engine.base import AudioProcessingEngine, VoiceCloningEngine
from app.ai_engine.registry import EngineRegistry
from app.core.config import Settings
from app.core.errors import (
    AudioQualityInsufficient,
    AudioTooShort,
    ConsentRequired,
    NotFound,
    ValidationFailed,
    VoiceNotReady,
)
from app.core.security import hash_identifier
from app.models.job import Job
from app.models.user import User
from app.models.voice import Voice
from app.services.common import get_owned, paginate
from app.services.file_service import probe_upload, validate_extension
from app.services.job_service import create_job
from app.storage.base import StorageBackend
from app.utils.audio import analyze_voice_sample, wav_duration
from app.utils.files import VOICE_SAMPLE_EXTENSIONS
from app.utils.ids import new_id, utcnow
from app.utils.languages import normalize_language
from app.workers.runner import JobContext

REFERENCE_SAMPLE_RATE = 24000
CONSENT_VERSION = "2026-11-v1"
CONSENT_TYPES = ("self", "authorized_third_party")
MIN_REFERENCE_SECONDS = 3.0


# ------------------------------------------------------------------ cloning
def create_voice(
    db: Session,
    storage: StorageBackend,
    settings: Settings,
    registry: EngineRegistry,
    user: User,
    upload: UploadFile,
    *,
    name: str,
    description: str | None,
    language: str | None,
    source: str,
    consent_confirmed: bool,
    consent_type: str,
    consent_holder_name: str,
    client_ip: str | None,
) -> tuple[Voice, Job]:
    """Validate consent + sample synchronously (fast 4xx), then queue the profile-building job."""
    if not consent_confirmed:
        raise ConsentRequired(
            "Set consent_confirmed=true to confirm that the speaker has given explicit permission "
            "for their voice to be cloned.",
            details={"field": "consent_confirmed"},
        )
    if consent_type not in CONSENT_TYPES:
        raise ValidationFailed(
            f"consent_type must be one of: {', '.join(CONSENT_TYPES)}.", details={"field": "consent_type"}
        )
    holder = (consent_holder_name or "").strip()
    if not holder or len(holder) > 120:
        raise ValidationFailed(
            "consent_holder_name (the name of the person whose voice this is) is required.",
            details={"field": "consent_holder_name"},
        )
    name = (name or "").strip()
    if not name or len(name) > 120:
        raise ValidationFailed("name is required (max 120 characters).", details={"field": "name"})
    if source not in ("recorded", "uploaded"):
        raise ValidationFailed("source must be 'recorded' or 'uploaded'.", details={"field": "source"})
    lang = normalize_language(language, allow_auto=True, field="language")

    audio = registry.require("audio_processing")
    registry.require("voice_cloning")
    assert isinstance(audio, AudioProcessingEngine)

    _, ext = validate_extension(upload, VOICE_SAMPLE_EXTENSIONS)
    voice_id = new_id("voc")
    tmp_key = storage.new_key("tmp", user.id, ext)
    storage.save_stream(tmp_key, upload.file, max_bytes=settings.max_voice_sample_bytes)
    settings.tmp_root.mkdir(parents=True, exist_ok=True)
    wav_local = settings.tmp_root / f"{voice_id}.wav"
    source_key = storage.build_key("voices", user.id, voice_id, "source.wav")
    try:
        info = probe_upload(
            storage, tmp_key, min_seconds=settings.voice_min_seconds, max_seconds=settings.voice_max_seconds
        )
        audio.to_wav(storage.local_path(tmp_key), wav_local, sample_rate=REFERENCE_SAMPLE_RATE)
        report = analyze_voice_sample(wav_local, min_speech_seconds=settings.voice_min_speech_seconds)
        if not report.ok:
            raise AudioQualityInsufficient(" ".join(report.issues), details={"quality": report.to_dict()})
        storage.put_file(source_key, wav_local, move=True)
    finally:
        storage.delete(tmp_key)
        wav_local.unlink(missing_ok=True)

    now = utcnow()
    voice = Voice(
        id=voice_id,
        user_id=user.id,
        name=name,
        description=(description or "").strip() or None,
        language=lang,
        status="processing",
        source=source,
        requires_reference_audio=True,
        duration_seconds=info.duration_seconds,
        quality=report.to_dict(),
        consent={
            "confirmed": True,
            "type": consent_type,
            "holder_name": holder,
            "statement": (
                f"I confirm that this recording is of {holder} and that the speaker has given explicit "
                "permission for their voice to be cloned and used by this service."
            ),
            "confirmed_at": now.isoformat(),
            "version": CONSENT_VERSION,
            "client_ip_hash": hash_identifier(client_ip, settings.api_key_pepper) if client_ip else None,
        },
    )
    db.add(voice)
    db.flush()
    job = create_job(db, user, "voice_clone", {"voice_id": voice_id})
    return voice, job


def handle_voice_clone(ctx: JobContext) -> dict[str, Any]:
    voice_id = ctx.params["voice_id"]
    with ctx.db() as db:
        voice = db.get(Voice, voice_id)
        if voice is None or voice.user_id != ctx.user_id:
            raise NotFound("Voice not found.")
    audio = ctx.registry.require("audio_processing")
    cloner = ctx.registry.require("voice_cloning")
    assert isinstance(audio, AudioProcessingEngine) and isinstance(cloner, VoiceCloningEngine)

    storage = ctx.storage
    source_key = storage.build_key("voices", ctx.user_id, voice_id, "source.wav")
    reference_key = storage.build_key("voices", ctx.user_id, voice_id, "reference.wav")
    profile_key = storage.build_key("voices", ctx.user_id, voice_id, "profile.pt")

    ctx.progress(10, "Preparing reference audio")
    reference = ctx.workdir / "reference.wav"
    audio.prepare_voice_reference(
        storage.local_path(source_key),
        reference,
        sample_rate=REFERENCE_SAMPLE_RATE,
        max_seconds=ctx.settings.voice_reference_max_seconds,
    )
    ref_seconds = wav_duration(reference)
    if ref_seconds < MIN_REFERENCE_SECONDS:
        raise AudioTooShort(
            f"Only {ref_seconds:.1f}s of usable audio remained after trimming silence.",
            details={"min_seconds": MIN_REFERENCE_SECONDS},
        )

    ctx.progress(35, "Computing voice profile")
    profile = ctx.workdir / "profile.pt"
    info = cloner.prepare_voice(reference, profile)

    ctx.progress(90, "Saving voice")
    storage.put_file(reference_key, reference)
    has_profile = profile.is_file()
    if has_profile:
        storage.put_file(profile_key, profile)
    with ctx.db() as db:
        voice = db.get(Voice, voice_id)
        if voice is None:  # deleted while processing
            storage.delete_prefix(f"voices/{ctx.user_id}/{voice_id}")
            raise NotFound("Voice was deleted during processing.")
        voice.status = "ready"
        voice.engine = info.engine
        voice.model_id = info.model
        voice.profile_type = info.profile_type
        voice.requires_reference_audio = info.requires_reference_audio
        voice.reference_key = reference_key
        voice.profile_key = profile_key if has_profile else None
        voice.error_code = None
        voice.error_message = None
    storage.delete(source_key)
    return {"voice_id": voice_id, "profile_type": info.profile_type, "reference_seconds": round(ref_seconds, 2)}


def on_voice_clone_failed(ctx: JobContext, code: str, message: str) -> None:
    voice_id = ctx.params.get("voice_id")
    if not voice_id:
        return
    with ctx.db() as db:
        voice = db.get(Voice, voice_id)
        if voice is not None:
            voice.status = "failed"
            voice.error_code = code
            voice.error_message = message[:2000]
    # Biometric data should not linger after a failed attempt.
    try:
        ctx.storage.delete_prefix(f"voices/{ctx.user_id}/{voice_id}")
    except ValueError:
        pass


# ------------------------------------------------------------------ library
def list_voices(
    db: Session, user: User, status: str | None, limit: int, offset: int
) -> tuple[list[Voice], int]:
    stmt = select(Voice).where(Voice.user_id == user.id)
    if status:
        stmt = stmt.where(Voice.status == status)
    return paginate(db, stmt, Voice.created_at.desc(), limit, offset)


def get_voice(db: Session, user: User, voice_id: str) -> Voice:
    return get_owned(db, Voice, voice_id, user.id, "Voice")


def update_voice(db: Session, user: User, voice_id: str, name: str | None, description: str | None) -> Voice:
    voice = get_voice(db, user, voice_id)
    if name is not None:
        if not name.strip():
            raise ValidationFailed("name must not be empty.", details={"field": "name"})
        voice.name = name.strip()
    if description is not None:
        voice.description = description.strip() or None
    voice.updated_at = utcnow()
    return voice


def delete_voice(db: Session, storage: StorageBackend, user: User, voice_id: str) -> None:
    voice = get_voice(db, user, voice_id)
    storage.delete_prefix(f"voices/{user.id}/{voice.id}")
    db.delete(voice)


def load_ready_voice(db: Session, user_id: str, voice_id: str) -> Voice:
    voice = get_owned(db, Voice, voice_id, user_id, "Voice")
    if voice.status != "ready" or not voice.reference_key:
        raise VoiceNotReady(
            f"The voice is '{voice.status}'; it can be used once its status is 'ready'.",
            details={"status": voice.status},
        )
    return voice


def voice_paths(storage: StorageBackend, voice: Voice) -> tuple[Path, Path | None]:
    assert voice.reference_key
    reference = storage.local_path(voice.reference_key)
    profile = storage.local_path(voice.profile_key) if voice.profile_key else None
    return reference, profile
