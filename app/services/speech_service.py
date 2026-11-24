"""Text-to-speech jobs."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai_engine.base import AudioProcessingEngine, TextToSpeechEngine
from app.ai_engine.registry import EngineRegistry
from app.ai_engine.tts_runner import synthesize_text
from app.core.config import Settings
from app.core.errors import UnsupportedLanguage, ValidationFailed
from app.models.job import Job
from app.models.user import User
from app.schemas.speech import SpeechRequest
from app.services.file_service import register_generated_file
from app.services.job_service import create_job
from app.services.voice_service import load_ready_voice, voice_paths
from app.utils.languages import normalize_language
from app.workers.runner import JobContext


def submit_speech(db: Session, settings: Settings, registry: EngineRegistry, user: User, req: SpeechRequest) -> Job:
    text = req.text.strip()
    if not text:
        raise ValidationFailed("text must not be empty.", details={"field": "text"})
    if len(text) > settings.max_text_chars:
        raise ValidationFailed(
            f"text is too long ({len(text)} characters; maximum {settings.max_text_chars}).",
            details={"field": "text", "max_characters": settings.max_text_chars},
        )
    language = normalize_language(req.language, field="language")
    assert language is not None

    registry.require("audio_processing")
    tts = registry.require("text_to_speech")
    assert isinstance(tts, TextToSpeechEngine)
    if language not in tts.supported_languages:
        raise UnsupportedLanguage(
            f"The configured TTS engine does not support '{language}'.",
            details={"supported": sorted(tts.supported_languages)},
        )
    load_ready_voice(db, user.id, req.voice_id)  # ownership + readiness, fails fast

    return create_job(
        db,
        user,
        "speech",
        {
            "voice_id": req.voice_id,
            "text": text,
            "language": language,
            "speed": req.speed,
            "output_format": req.output_format,
        },
        project_id=req.project_id,
    )


def handle_speech(ctx: JobContext) -> dict[str, Any]:
    p = ctx.params
    tts = ctx.registry.require("text_to_speech")
    audio = ctx.registry.require("audio_processing")
    assert isinstance(tts, TextToSpeechEngine) and isinstance(audio, AudioProcessingEngine)

    with ctx.db() as db:
        voice = load_ready_voice(db, ctx.user_id, p["voice_id"])
        reference, profile = voice_paths(ctx.storage, voice)

    wav = ctx.workdir / "speech.wav"
    ctx.progress(3, "Generating speech")
    res = synthesize_text(
        tts,
        text=p["text"],
        language=p["language"],
        reference_wav=reference,
        profile_path=profile,
        speed=p["speed"],
        out_wav=wav,
        workdir=ctx.workdir,
        progress=ctx.progress,
        progress_range=(3, 85),
    )

    fmt = p["output_format"]
    ctx.progress(88, "Encoding audio")
    out = wav
    if fmt != "wav":
        out = ctx.workdir / f"speech.{fmt}"
        audio.encode(wav, out, fmt)

    with ctx.db() as db:
        asset = register_generated_file(
            db,
            ctx.storage,
            user_id=ctx.user_id,
            local_file=out,
            ext=fmt,
            display_name=f"speech-{ctx.job_id[-8:]}.{fmt}",
            kind="generated",
            duration_seconds=res.duration_seconds,
        )
        file_id = asset.id
    return {
        "file_id": file_id,
        "format": fmt,
        "duration_seconds": round(res.duration_seconds, 2),
        "characters": len(p["text"]),
        "language": p["language"],
        "voice_id": p["voice_id"],
    }
