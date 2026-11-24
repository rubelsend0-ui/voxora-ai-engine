from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SpeechRequest(BaseModel):
    voice_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1)
    language: str = Field(min_length=2, max_length=10, description="Language of the text, e.g. 'en', 'es', 'zh-cn'.")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    output_format: Literal["wav", "mp3", "flac", "ogg", "m4a"] = "wav"
    project_id: str | None = Field(default=None, max_length=64)
