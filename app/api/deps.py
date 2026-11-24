"""Shared FastAPI dependencies: DB session, authentication, rate limiting, pagination."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

from fastapi import Depends, Query, Request, Security
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_engine.registry import EngineRegistry, get_registry
from app.core.config import Settings, get_settings
from app.core.errors import NotFound, Unauthorized
from app.core.rate_limit import get_rate_limiter
from app.core.security import hash_api_key
from app.database.session import get_session_factory
from app.models.file import FileAsset
from app.models.user import ApiKey, User
from app.storage.base import StorageBackend
from app.storage.local import get_storage
from app.utils.ids import utcnow

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Your VOXORA API key (vx_...).")
bearer_scheme = HTTPBearer(auto_error=False, description="Alternative: Authorization: Bearer <api key>.")


def get_db() -> Iterator[Session]:
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def get_settings_dep() -> Settings:
    return get_settings()


def get_storage_dep() -> StorageBackend:
    return get_storage()


def get_registry_dep() -> EngineRegistry:
    return get_registry()


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _auth_failure(settings: Settings, ip: str | None) -> None:
    # Throttle brute-force guessing per client IP (raises RateLimited when exceeded).
    get_rate_limiter().hit(f"authfail:{ip or 'unknown'}", settings.auth_fail_limit_per_minute)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    x_api_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> User:
    raw = x_api_key or (bearer.credentials if bearer else None)
    ip = client_ip(request)
    if not raw:
        _auth_failure(settings, ip)
        raise Unauthorized("Missing API key. Send it in the X-API-Key header.")
    digest = hash_api_key(raw.strip(), settings.api_key_pepper)
    row = db.execute(
        select(ApiKey, User)
        .join(User, User.id == ApiKey.user_id)
        .where(ApiKey.key_hash == digest, ApiKey.revoked_at.is_(None), User.is_active.is_(True))
    ).first()
    if row is None:
        _auth_failure(settings, ip)
        raise Unauthorized("Invalid or revoked API key.")
    key, user = row
    now = utcnow()
    if key.last_used_at is None or now - key.last_used_at > timedelta(minutes=1):
        key.last_used_at = now
        db.commit()
    return user


def rate_limit(user: User = Depends(get_current_user), settings: Settings = Depends(get_settings_dep)) -> None:
    get_rate_limiter().hit(f"user:{user.id}", settings.rate_limit_per_minute)


def heavy_rate_limit(user: User = Depends(get_current_user), settings: Settings = Depends(get_settings_dep)) -> None:
    """Stricter bucket for endpoints that start expensive AI jobs."""
    get_rate_limiter().hit(f"heavy:{user.id}", settings.rate_limit_heavy_per_minute)


def pagination(
    limit: int = Query(20, ge=1, le=100, description="Page size."),
    offset: int = Query(0, ge=0, description="Items to skip."),
) -> tuple[int, int]:
    return limit, offset


def file_response(storage: StorageBackend, asset: FileAsset) -> FileResponse:
    """Stream a stored file. The client only ever sees ids and names - never storage paths."""
    if not storage.exists(asset.storage_key):
        raise NotFound("File not found.")
    return FileResponse(
        storage.local_path(asset.storage_key),
        media_type=asset.content_type,
        filename=asset.original_name,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
