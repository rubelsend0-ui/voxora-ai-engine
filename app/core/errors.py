"""Error types and the uniform JSON error envelope.

Every error returned by the API looks like::

    {"error": {"code": "AI_ENGINE_NOT_CONFIGURED", "message": "...", "details": {...}},
     "request_id": "..."}

This module intentionally has no FastAPI import at module level so that the AI
engines and worker code can raise these errors without the web stack.
"""

from __future__ import annotations

from typing import Any


class VoxoraError(Exception):
    status_code: int = 400
    code: str = "BAD_REQUEST"
    default_message: str = "Bad request."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        self.headers = headers or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationFailed(VoxoraError):
    status_code = 422
    code = "VALIDATION_ERROR"
    default_message = "The request is invalid."


class Unauthorized(VoxoraError):
    status_code = 401
    code = "UNAUTHORIZED"
    default_message = "A valid API key is required."


class Forbidden(VoxoraError):
    status_code = 403
    code = "FORBIDDEN"
    default_message = "You do not have access to this resource."


class NotFound(VoxoraError):
    status_code = 404
    code = "NOT_FOUND"
    default_message = "Resource not found."


class Conflict(VoxoraError):
    status_code = 409
    code = "CONFLICT"
    default_message = "The request conflicts with the current state."


class PayloadTooLarge(VoxoraError):
    status_code = 413
    code = "FILE_TOO_LARGE"
    default_message = "The uploaded file is too large."


class UnsupportedMedia(VoxoraError):
    status_code = 415
    code = "UNSUPPORTED_MEDIA_TYPE"
    default_message = "This file type is not supported."


class RateLimited(VoxoraError):
    status_code = 429
    code = "RATE_LIMITED"
    default_message = "Too many requests."


class ConsentRequired(VoxoraError):
    status_code = 422
    code = "CONSENT_REQUIRED"
    default_message = "Voice cloning requires explicit consent from the voice owner."


class AudioInvalid(VoxoraError):
    status_code = 422
    code = "AUDIO_INVALID"
    default_message = "The file could not be read as audio."


class AudioTooShort(VoxoraError):
    status_code = 422
    code = "AUDIO_TOO_SHORT"
    default_message = "The audio is too short."


class AudioTooLong(VoxoraError):
    status_code = 422
    code = "AUDIO_TOO_LONG"
    default_message = "The audio is too long."


class AudioQualityInsufficient(VoxoraError):
    status_code = 422
    code = "AUDIO_QUALITY_INSUFFICIENT"
    default_message = "The audio quality is not sufficient."


class VoiceNotReady(VoxoraError):
    status_code = 409
    code = "VOICE_NOT_READY"
    default_message = "The voice profile is not ready yet."


class JobNotReady(VoxoraError):
    status_code = 409
    code = "JOB_NOT_READY"
    default_message = "The job has not completed yet."


class AIEngineNotConfigured(VoxoraError):
    """Raised when a model/engine is missing, not installed or not downloaded."""

    status_code = 503
    code = "AI_ENGINE_NOT_CONFIGURED"
    default_message = "The required AI engine is not configured."

    def __init__(self, engine: str, reason: str, *, hint: str | None = None) -> None:
        details: dict[str, Any] = {"engine": engine, "reason": reason}
        if hint:
            details["hint"] = hint
        super().__init__(f"AI engine '{engine}' is not configured: {reason}", details=details)


class AIEngineError(VoxoraError):
    status_code = 500
    code = "AI_ENGINE_ERROR"
    default_message = "The AI engine failed to process the request."


class MediaProcessingError(VoxoraError):
    status_code = 500
    code = "MEDIA_PROCESSING_ERROR"
    default_message = "Media processing failed."


class UnsupportedLanguage(VoxoraError):
    status_code = 422
    code = "UNSUPPORTED_LANGUAGE"
    default_message = "The requested language is not supported by the configured engine."


def register_exception_handlers(app: Any) -> None:
    """Attach handlers that render every error in the uniform envelope."""
    import logging

    from fastapi import Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    log = logging.getLogger("voxora.errors")

    def _envelope(request: Request, payload: dict[str, Any], status: int, headers: dict[str, str] | None = None):
        body = {"error": payload, "request_id": getattr(request.state, "request_id", None)}
        return JSONResponse(status_code=status, content=body, headers=headers)

    @app.exception_handler(VoxoraError)
    async def _voxora(request: Request, exc: VoxoraError):
        return _envelope(request, exc.to_dict(), exc.status_code, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [
            {"loc": [str(p) for p in e.get("loc", [])], "message": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        payload = {"code": "VALIDATION_ERROR", "message": "The request is invalid.", "details": {"errors": errors}}
        return _envelope(request, payload, 422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        payload = {"code": code, "message": str(exc.detail), "details": {}}
        return _envelope(request, payload, exc.status_code, getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        payload = {"code": "INTERNAL_ERROR", "message": "An internal error occurred.", "details": {}}
        return _envelope(request, payload, 500)
