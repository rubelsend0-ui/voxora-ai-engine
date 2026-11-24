from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    file_response,
    get_current_user,
    get_db,
    get_settings_dep,
    get_storage_dep,
    heavy_rate_limit,
    pagination,
)
from app.core.config import Settings
from app.models.file import FileAsset
from app.models.user import User
from app.schemas.common import Page
from app.schemas.misc import FileOut
from app.services import file_service
from app.services.common import get_owned
from app.storage.base import StorageBackend
from app.utils.files import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

router = APIRouter(prefix="/files", tags=["Files"])


@router.post(
    "",
    response_model=FileOut,
    status_code=201,
    summary="Upload an audio/video file for later use (file_id)",
    dependencies=[Depends(heavy_rate_limit)],
)
def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
    settings: Settings = Depends(get_settings_dep),
) -> FileOut:
    asset = file_service.ingest_upload(
        db, storage, user, file,
        allowed_extensions=AUDIO_EXTENSIONS | VIDEO_EXTENSIONS,
        max_bytes=settings.max_upload_bytes,
        max_seconds=settings.media_max_seconds,
    )
    db.commit()
    return FileOut.from_file(asset)


@router.get("", response_model=Page[FileOut], summary="List your files")
def list_files(
    kind: Literal["upload", "generated", "export"] | None = None,
    page: tuple[int, int] = Depends(pagination),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[FileOut]:
    limit, offset = page
    rows, total = file_service.list_files(db, user, kind, limit, offset)
    return Page[FileOut](items=[FileOut.from_file(f) for f in rows], total=total, limit=limit, offset=offset)


@router.get("/{file_id}", response_model=FileOut, summary="Get file metadata")
def get_file(file_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileOut:
    return FileOut.from_file(get_owned(db, FileAsset, file_id, user.id, "File"))


@router.get("/{file_id}/download", response_class=FileResponse, summary="Download a file")
def download_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
) -> FileResponse:
    return file_response(storage, get_owned(db, FileAsset, file_id, user.id, "File"))


@router.delete("/{file_id}", status_code=204, response_class=Response, summary="Delete a file")
def delete_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage_dep),
) -> Response:
    file_service.delete_file(db, storage, user, file_id)
    db.commit()
    return Response(status_code=204)
