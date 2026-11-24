from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.file import FileAsset
from app.models.project import Project


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)


class ProjectOut(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_project(cls, p: Project) -> ProjectOut:
        return cls(
            project_id=p.id, name=p.name, description=p.description, created_at=p.created_at, updated_at=p.updated_at
        )


class FileOut(BaseModel):
    file_id: str
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    duration_seconds: float | None = None
    created_at: datetime
    download_url: str

    @classmethod
    def from_file(cls, f: FileAsset) -> FileOut:
        return cls(
            file_id=f.id,
            kind=f.kind,
            filename=f.original_name,
            content_type=f.content_type,
            size_bytes=f.size_bytes,
            sha256=f.sha256,
            duration_seconds=f.duration_seconds,
            created_at=f.created_at,
            download_url=f"/api/v1/files/{f.id}/download",
        )


class TextTranslationRequest(BaseModel):
    text: str = Field(min_length=1)
    source_language: str = Field(min_length=2, max_length=10)
    target_language: str = Field(min_length=2, max_length=10)


class TextTranslationResponse(BaseModel):
    source_language: str
    target_language: str
    translated_text: str


class EngineStatusOut(BaseModel):
    engine: str
    available: bool
    adapter: str
    device: str | None = None
    model: str | None = None
    reason: str | None = None
    hint: str | None = None
    details: dict[str, Any] = {}


class MeOut(BaseModel):
    user_id: str
    email: str
    display_name: str | None = None
