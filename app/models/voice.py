from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.types import UTCDateTime
from app.utils.ids import new_id, utcnow


class Voice(Base):
    __tablename__ = "voices"

    id: Mapped[str] = mapped_column(String(48), primary_key=True, default=lambda: new_id("voc"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), index=True, default="processing")  # processing|ready|failed
    source: Mapped[str] = mapped_column(String(16), default="uploaded")  # recorded | uploaded
    engine: Mapped[str | None] = mapped_column(String(48), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    profile_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    requires_reference_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    reference_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    profile_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    consent: Mapped[dict[str, Any]] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
