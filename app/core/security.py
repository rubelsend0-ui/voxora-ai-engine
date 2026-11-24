"""API key generation / hashing. Keys are never stored in clear text."""

from __future__ import annotations

import hashlib
import hmac
import secrets

KEY_PREFIX = "vx_"


def generate_api_key() -> tuple[str, str]:
    """Return ``(raw_key, display_prefix)``. The raw key is shown to the user exactly once."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:10]


def hash_api_key(raw_key: str, pepper: str) -> str:
    """Keyed hash (HMAC-SHA256) so a leaked database alone cannot be used to verify guesses."""
    return hmac.new(pepper.encode(), raw_key.encode(), hashlib.sha256).hexdigest()


def hash_identifier(value: str, pepper: str) -> str:
    """Short keyed hash used for privacy-preserving audit data (e.g. client IP in consent logs)."""
    return hmac.new(pepper.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]
