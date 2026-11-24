"""Text translation (sync) and audio translation (transcribe + translate, async)."""

from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.ai_engine.base import TranslationEngine
from app.ai_engine.registry import EngineRegistry
from app.core.config import Settings
from app.core.errors import AIEngineNotConfigured, ValidationFailed
from app.models.job import Job
from app.models.user import User
from app.schemas.misc import TextTranslationRequest, TextTranslationResponse
from app.services.file_service import resolve_input
from app.services.job_service import create_job, ensure_project
from app.services.transcription_service import transcribe_stored_file
from app.storage.base import StorageBackend
from app.utils.files import TRANSCRIPTION_EXTENSIONS
from app.utils.languages import base_language, normalize_language
from app.utils.text import split_text
from app.workers.runner import JobContext


def _require_pair(translator: TranslationEngine, src: str, tgt: str) -> None:
    if not translator.supports_pair(src, tgt):
        raise AIEngineNotConfigured(
            "translation",
            f"No translation model is installed for {src} -> {tgt}.",
            hint=f"Run: python -m scripts.download_models --translation {base_language(src)}-{base_language(tgt)}",
        )


def translate_text(registry: EngineRegistry, settings: Settings, req: TextTranslationRequest) -> TextTranslationResponse:
    text = req.text.strip()
    if not text:
        raise ValidationFailed("text must not be empty.", details={"field": "text"})
    if len(text) > settings.max_translation_chars:
        raise ValidationFailed(
            f"text is too long (maximum {settings.max_translation_chars} characters).", details={"field": "text"}
        )
    src = normalize_language(req.source_language, field="source_language")
    tgt = normalize_language(req.target_language, field="target_language")
    assert src and tgt
    translator = registry.require("translation")
    assert isinstance(translator, TranslationEngine)
    if base_language(src) == base_language(tgt):
        raise ValidationFailed("source_language and target_language must differ.")
    _require_pair(translator, src, tgt)

    lines = text.split("\n")
    chunks: list[str] = []
    owner: list[int] = []
    for li, line in enumerate(lines):
        for piece in split_text(line, 400):
            chunks.append(piece)
            owner.append(li)
    translated = translator.translate(chunks, src, tgt)
    out_lines = [[] for _ in lines]  # type: list[list[str]]
    for li, tr in zip(owner, translated, strict=True):
        out_lines[li].append(tr)
    return TextTranslationResponse(
        source_language=src,
        target_language=tgt,
        translated_text="\n".join(" ".join(parts) for parts in out_lines),
    )


def submit_audio_translation(
    db: Session,
    storage: StorageBackend,
    settings: Settings,
    registry: EngineRegistry,
    user: User,
    upload: UploadFile | None,
    file_id: str | None,
    source_language: str | None,
    target_language: str,
    project_id: str | None,
) -> Job:
    ensure_project(db, user, project_id)
    registry.require("audio_processing")
    registry.require("speech_to_text")
    translator = registry.require("translation")
    assert isinstance(translator, TranslationEngine)
    src = normalize_language(source_language, allow_auto=True, field="source_language")
    tgt = normalize_language(target_language, field="target_language")
    assert tgt
    if src is not None:
        if base_language(src) == base_language(tgt):
            raise ValidationFailed("source_language and target_language must differ.")
        _require_pair(translator, src, tgt)
    asset = resolve_input(
        db, storage, settings, user, upload, file_id,
        allowed_extensions=TRANSCRIPTION_EXTENSIONS, max_seconds=settings.media_max_seconds,
    )
    return create_job(
        db, user, "translation", {"file_id": asset.id, "source_language": src, "target_language": tgt}, project_id
    )


def handle_audio_translation(ctx: JobContext) -> dict[str, Any]:
    p = ctx.params
    translator = ctx.registry.require("translation")
    assert isinstance(translator, TranslationEngine)
    transcript = transcribe_stored_file(ctx, p["file_id"], p.get("source_language"), progress_range=(3.0, 70.0))
    src = p.get("source_language") or transcript.language
    tgt = p["target_language"]
    if base_language(src) == base_language(tgt):
        raise ValidationFailed(f"The audio is already in '{tgt}'.")
    _require_pair(translator, src, tgt)
    ctx.progress(72, "Translating")
    segments = [s for s in transcript.segments if s.text.strip()]
    translated = translator.translate([s.text.strip() for s in segments], src, tgt)
    source = transcript.to_dict()
    tr_segments = [
        {"id": i, "start": round(s.start, 3), "end": round(s.end, 3), "text": t}
        for i, (s, t) in enumerate(zip(segments, translated, strict=True))
    ]
    return {
        "file_id": p["file_id"],
        "source_language": src,
        "target_language": tgt,
        "source": {"text": source["text"], "segments": source["segments"]},
        "translated": {"text": " ".join(t for t in translated if t), "segments": tr_segments},
        "duration_seconds": source["duration_seconds"],
    }
