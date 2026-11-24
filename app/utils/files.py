"""File name / type helpers. Content types are derived from the validated extension, never from the client."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

AUDIO_EXTENSIONS = frozenset({"wav", "mp3", "m4a", "flac", "ogg", "opus", "aac", "webm", "3gp", "amr"})
VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "mkv", "webm", "avi", "m4v"})
VOICE_SAMPLE_EXTENSIONS = AUDIO_EXTENSIONS
TRANSCRIPTION_EXTENSIONS = frozenset({"wav", "mp3", "m4a", "flac", "mp4", "ogg", "opus", "aac", "webm", "mov", "mkv"})
DUBBING_EXTENSIONS = TRANSCRIPTION_EXTENSIONS | {"avi", "m4v", "3gp"}
OUTPUT_AUDIO_FORMATS = ("wav", "mp3", "flac", "ogg", "m4a")

CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "amr": "audio/amr",
    "3gp": "video/3gpp",
    "webm": "video/webm",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "mkv": "video/x-matroska",
    "avi": "video/x-msvideo",
    "m4v": "video/x-m4v",
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "txt": "text/plain",
}


def sanitize_filename(name: str | None, default: str = "file") -> str:
    """Return a safe display file name (no directories, no control characters)."""
    base = PurePosixPath((name or "").replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ]+", "_", base, flags=re.UNICODE).strip(" .")
    return (base[:120] or default)


def extension_of(name: str | None) -> str:
    base = sanitize_filename(name, "")
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def content_type_for(ext: str) -> str:
    return CONTENT_TYPES.get(ext.lower(), "application/octet-stream")
