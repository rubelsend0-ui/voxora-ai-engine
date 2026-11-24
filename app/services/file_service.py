"""Upload ingestion and file records."""

from __future__ import annotations

from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_engine.base import AudioProcessingEngine, MediaInfo
from app.ai_engine.registry import get_registry
from app.core.config import Settings
from app.core.errors import (
    AudioInvalid,
    AudioTooLong,
    AudioTooShort,
    MediaProcessingError,
    NotFound,
    UnsupportedMedia,
    ValidationFailed,
)
from app.models.file import FileAsset
from app.models.user import User
from app.services.common import get_owned, paginate
from app.storage.base import StorageBackend
from app.utils.files import content_type_for, extension_of, sanitize_filename


def probe_upload(
    storage: StorageBackend,
    key: str,
    *,
    min_seconds: float | None = None,
    max_seconds: float | None = None,
) -> MediaInfo:
    """Decode-check a stored upload with ffprobe and enforce duration bounds."""
    audio = get_registry().require("audio_processing")
    assert isinstance(audio, AudioProcessingEngine)
    try:
        info = audio.probe(storage.local_path(key))
    except MediaProcessingError as exc:
        raise AudioInvalid("The file is corrupt or is not a supported audio/video file.") from exc
    if not info.has_audio:
        raise AudioInvalid("The file does not contain an audio track.")
    if info.duration_seconds <= 0:
        raise AudioInvalid("The media duration could not be determined.")
    if min_seconds is not None and info.duration_seconds < min_seconds:
        raise AudioTooShort(
            f"The audio is {info.duration_seconds:.1f}s long; at least {min_seconds:.0f}s is required.",
            details={"duration_seconds": round(info.duration_seconds, 2), "min_seconds": min_seconds},
        )
    if max_seconds is not None and info.duration_seconds > max_seconds:
        raise AudioTooLong(
            f"The media is {info.duration_seconds:.0f}s long; the maximum is {max_seconds:.0f}s.",
            details={"duration_seconds": round(info.duration_seconds, 2), "max_seconds": max_seconds},
        )
    return info


def validate_extension(upload: UploadFile, allowed: frozenset[str]) -> tuple[str, str]:
    name = sanitize_filename(upload.filename, "upload")
    ext = extension_of(name)
    if ext not in allowed:
        raise UnsupportedMedia(
            f"Files of type '.{ext or 'unknown'}' are not accepted here.",
            details={"allowed_extensions": sorted(allowed)},
        )
    return name, ext


def ingest_upload(
    db: Session,
    storage: StorageBackend,
    user: User,
    upload: UploadFile,
    *,
    allowed_extensions: frozenset[str],
    max_bytes: int,
    max_seconds: float | None = None,
    kind: str = "upload",
) -> FileAsset:
    """Stream an upload to storage, verify it decodes as media, and record it."""
    name, ext = validate_extension(upload, allowed_extensions)
    key = storage.new_key("uploads", user.id, ext)
    obj = storage.save_stream(key, upload.file, max_bytes=max_bytes)
    try:
        info = probe_upload(storage, key, max_seconds=max_seconds)
    except Exception:
        storage.delete(key)
        raise
    asset = FileAsset(
        user_id=user.id,
        kind=kind,
        original_name=name,
        content_type=content_type_for(ext),
        size_bytes=obj.size_bytes,
        sha256=obj.sha256,
        storage_key=key,
        duration_seconds=info.duration_seconds,
    )
    db.add(asset)
    db.flush()
    return asset


def resolve_input(
    db: Session,
    storage: StorageBackend,
    settings: Settings,
    user: User,
    upload: UploadFile | None,
    file_id: str | None,
    *,
    allowed_extensions: frozenset[str],
    max_seconds: float | None,
) -> FileAsset:
    """Accept either a fresh multipart upload or a previously uploaded ``file_id`` (exactly one)."""
    has_upload = upload is not None and bool(getattr(upload, "filename", None))
    if has_upload == bool(file_id):
        raise ValidationFailed("Provide exactly one of the uploaded file or 'file_id'.")
    if file_id:
        asset = get_owned(db, FileAsset, file_id, user.id, "File")
        if not storage.exists(asset.storage_key):
            raise NotFound("File not found.")
        if max_seconds is not None and (asset.duration_seconds or 0) > max_seconds:
            raise AudioTooLong(
                f"The media is {asset.duration_seconds:.0f}s long; the maximum is {max_seconds:.0f}s.",
                details={"max_seconds": max_seconds},
            )
        return asset
    assert upload is not None
    return ingest_upload(
        db, storage, user, upload, allowed_extensions=allowed_extensions, max_bytes=settings.max_upload_bytes,
        max_seconds=max_seconds,
    )


def list_files(db: Session, user: User, kind: str | None, limit: int, offset: int) -> tuple[list[FileAsset], int]:
    stmt = select(FileAsset).where(FileAsset.user_id == user.id)
    if kind:
        stmt = stmt.where(FileAsset.kind == kind)
    rows, total = paginate(db, stmt, FileAsset.created_at.desc(), limit, offset)
    return rows, total


def delete_file(db: Session, storage: StorageBackend, user: User, file_id: str) -> None:
    asset = get_owned(db, FileAsset, file_id, user.id, "File")
    storage.delete(asset.storage_key)
    db.delete(asset)


def register_generated_file(
    db: Session,
    storage: StorageBackend,
    *,
    user_id: str,
    local_file: Any,
    ext: str,
    display_name: str,
    kind: str,
    duration_seconds: float | None,
) -> FileAsset:
    """Move a locally produced file (TTS output, dubbed video) into storage and record it."""
    category = "generated" if kind == "generated" else "exports"
    key = storage.new_key(category, user_id, ext)
    obj = storage.put_file(key, local_file, move=False)
    asset = FileAsset(
        user_id=user_id,
        kind=kind,
        original_name=sanitize_filename(display_name, f"output.{ext}"),
        content_type=content_type_for(ext),
        size_bytes=obj.size_bytes,
        sha256=obj.sha256,
        storage_key=key,
        duration_seconds=duration_seconds,
    )
    db.add(asset)
    db.flush()
    return asset
