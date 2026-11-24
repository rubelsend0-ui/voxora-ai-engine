"""AI dubbing jobs (orchestrated by the DubbingEngine)."""

from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.ai_engine.base import AudioProcessingEngine, DubbingEngine, DubRequest, TextToSpeechEngine, TranslationEngine
from app.ai_engine.registry import EngineRegistry
from app.core.config import Settings
from app.core.errors import AIEngineNotConfigured, UnsupportedLanguage, ValidationFailed
from app.models.file import FileAsset
from app.models.job import Job
from app.models.user import User
from app.services.common import get_owned
from app.services.file_service import register_generated_file, resolve_input
from app.services.job_service import create_job, ensure_project
from app.services.voice_service import load_ready_voice, voice_paths
from app.storage.base import StorageBackend
from app.utils.files import DUBBING_EXTENSIONS, OUTPUT_AUDIO_FORMATS, sanitize_filename
from app.utils.languages import base_language, normalize_language
from app.workers.runner import JobContext

OUTPUT_FORMATS = ("mp4", *OUTPUT_AUDIO_FORMATS)


def submit_dubbing(
    db: Session,
    storage: StorageBackend,
    settings: Settings,
    registry: EngineRegistry,
    user: User,
    upload: UploadFile | None,
    file_id: str | None,
    *,
    source_language: str | None,
    target_language: str,
    voice_id: str,
    output_format: str | None,
    original_audio_volume: float,
    project_id: str | None,
) -> Job:
    ensure_project(db, user, project_id)
    src = normalize_language(source_language, allow_auto=True, field="source_language")
    tgt = normalize_language(target_language, field="target_language")
    assert tgt
    if output_format is not None and output_format not in OUTPUT_FORMATS:
        raise ValidationFailed(
            f"output_format must be one of: {', '.join(OUTPUT_FORMATS)}.", details={"field": "output_format"}
        )
    if not 0.0 <= original_audio_volume <= 1.0:
        raise ValidationFailed("original_audio_volume must be between 0 and 1.", details={"field": "original_audio_volume"})

    registry.require("dubbing")  # needs audio, STT, translation and TTS engines
    tts = registry.require("text_to_speech")
    translator = registry.require("translation")
    audio = registry.require("audio_processing")
    assert isinstance(tts, TextToSpeechEngine) and isinstance(translator, TranslationEngine)
    assert isinstance(audio, AudioProcessingEngine)
    if tgt not in tts.supported_languages:
        raise UnsupportedLanguage(
            f"The TTS engine cannot speak '{tgt}'.", details={"supported": sorted(tts.supported_languages)}
        )
    if src is not None and base_language(src) != base_language(tgt) and not translator.supports_pair(src, tgt):
        raise AIEngineNotConfigured(
            "translation",
            f"No translation model is installed for {src} -> {tgt}.",
            hint=f"Run: python -m scripts.download_models --translation {base_language(src)}-{base_language(tgt)}",
        )
    load_ready_voice(db, user.id, voice_id)

    asset = resolve_input(
        db, storage, settings, user, upload, file_id,
        allowed_extensions=DUBBING_EXTENSIONS, max_seconds=settings.dubbing_max_seconds,
    )
    info = audio.probe(storage.local_path(asset.storage_key))
    fmt = output_format or ("mp4" if info.has_video else "mp3")
    if fmt == "mp4" and not info.has_video:
        raise ValidationFailed("output_format 'mp4' needs a video input; choose an audio format.")
    return create_job(
        db,
        user,
        "dubbing",
        {
            "file_id": asset.id,
            "voice_id": voice_id,
            "source_language": src,
            "target_language": tgt,
            "output_format": fmt,
            "original_audio_volume": original_audio_volume,
        },
        project_id,
    )


def handle_dubbing(ctx: JobContext) -> dict[str, Any]:
    p = ctx.params
    engine = ctx.registry.require("dubbing")
    assert isinstance(engine, DubbingEngine)
    with ctx.db() as db:
        asset = get_owned(db, FileAsset, p["file_id"], ctx.user_id, "File")
        input_path = ctx.storage.local_path(asset.storage_key)
        source_name = asset.original_name
        voice = load_ready_voice(db, ctx.user_id, p["voice_id"])
        reference, profile = voice_paths(ctx.storage, voice)

    request = DubRequest(
        input_path=input_path,
        workdir=ctx.workdir / "dub",
        reference_wav=reference,
        profile_path=profile,
        source_language=p.get("source_language"),
        target_language=p["target_language"],
        output_format=p["output_format"],
        original_audio_volume=float(p.get("original_audio_volume", 0.0)),
        max_speedup=ctx.settings.dubbing_max_speedup,
        max_seconds=ctx.settings.dubbing_max_seconds,
    )
    result = engine.dub(request, progress=ctx.progress)

    stem = sanitize_filename(source_name, "media").rsplit(".", 1)[0]
    with ctx.db() as db:
        out = register_generated_file(
            db,
            ctx.storage,
            user_id=ctx.user_id,
            local_file=result.output_path,
            ext=p["output_format"],
            display_name=f"{stem}-dubbed-{p['target_language']}.{p['output_format']}",
            kind="export",
            duration_seconds=result.duration_seconds,
        )
        out_id = out.id
    return {
        "file_id": out_id,
        "format": p["output_format"],
        "duration_seconds": round(result.duration_seconds, 2),
        "source_language": result.detected_language,
        "target_language": p["target_language"],
        "source_segments": result.source_segments,
        "translated_segments": result.translated_segments,
        "sync": result.sync,
        "warnings": result.warnings,
        "limitations": result.limitations,
    }
