from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_id(prefix: str) -> str:
    """Unguessable, prefixed identifier, e.g. ``voc_3f2a...`` (128 bits of randomness)."""
    return f"{prefix}_{uuid.uuid4().hex}"


def utcnow() -> datetime:
    return datetime.now(UTC)
