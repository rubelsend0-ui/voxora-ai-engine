"""Speech-to-text jobs."""

from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.ai_engine.base import AudioProcessingEngine, SpeechToTextEngine, Transcript
from app.ai_engine.registry import EngineRegistry
from app.core.config import Settings
from app.models.file import FileAsset
from app.models.job import Job
from app.models.user import User
from app.services.common import get_owned
from app.services.file_service import resolve_input
from app.services.job_service import create_job, ensure_project
from app.storage.base import StorageBackend
from app.utils.files import TRANSCRIPTION_EXTENSIONS
from app.utils.languages import normalize_language
from app.workers.runner import JobContext


def submit_transcription(
    db: Session,
    storage: StorageBackend,
    settings: Settings,
    registry: EngineRegistry,
    user: User,
    upload: UploadFile | None,
    file_id: str | None,
    language: str | None,
    project_id: str | None,
) -> Job:
    ensure_project(db, user, project_id)
    registry.require("audio_processing")
    registry.require("speech_to_text")
    lang = normalize_language(language, allow_auto=True, field="language")
    asset = resolve_input(
        db, storage, settings, user, upload, file_id,
        allowed_extensions=TRANSCRIPTION_EXTENSIONS, max_seconds=settings.media_max_seconds,
    )
    return create_job(db, user, "transcription", {"file_id": asset.id, "language": lang}, project_id)


def transcribe_stored_file(
    ctx: JobContext, file_id: str, language: str | None, progress_range: tuple[float, float] = (5.0, 95.0)
) -> Transcript:
    """Decode a stored upload to 16 kHz WAV and transcribe it (shared with audio translation)."""
    audio = ctx.registry.require("audio_processing")
    stt = ctx.registry.require("speech_to_text")
    assert isinstance(audio, AudioProcessingEngine) and isinstance(stt, SpeechToTextEngine)
    with ctx.db() as db:
        key = get_owned(db, FileAsset, file_id, ctx.user_id, "File").storage_key
    lo, hi = progress_range
    wav = ctx.workdir / "audio_16k.wav"
    ctx.progress(lo, "Extracting audio")
    audio.to_wav(ctx.storage.local_path(key), wav, sample_rate=16000)
    ctx.progress(lo + (hi - lo) * 0.1, "Transcribing")
    return stt.transcribe(
        wav, language, progress=lambda f: ctx.progress(lo + (hi - lo) * (0.1 + 0.9 * f), "Transcribing")
    )


def handle_transcription(ctx: JobContext) -> dict[str, Any]:
    transcript = transcribe_stored_file(ctx, ctx.params["file_id"], ctx.params.get("language"))
    result = transcript.to_dict()
    result["file_id"] = ctx.params["file_id"]
    return result
