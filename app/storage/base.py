"""Storage abstraction.

Callers use opaque *storage keys* (``uploads/<user>/<id>.mp4``). Filesystem paths are an
implementation detail of a backend and are never returned to API clients. A remote
backend (S3, MinIO...) only has to implement this interface; ``local_path`` is where it
would materialise an object to a temporary file for FFmpeg/model use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

CATEGORIES = ("tmp", "uploads", "voices", "generated", "exports")


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    sha256: str


class StorageBackend(ABC):
    @abstractmethod
    def new_key(self, category: str, user_id: str, ext: str) -> str: ...

    @abstractmethod
    def build_key(self, category: str, *parts: str) -> str:
        """Deterministic key, e.g. ``voices/<user>/<voice_id>/reference.wav``."""

    @abstractmethod
    def save_stream(self, key: str, stream: BinaryIO, max_bytes: int | None = None) -> StoredObject:
        """Stream into storage, enforcing ``max_bytes`` while reading (raises PayloadTooLarge)."""

    @abstractmethod
    def put_file(self, key: str, src: Path, *, move: bool = False) -> StoredObject: ...

    @abstractmethod
    def move(self, src_key: str, dst_key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None: ...

    @abstractmethod
    def local_path(self, key: str) -> Path:
        """A real local file for the object (internal use only; never expose to clients)."""

    @abstractmethod
    def healthy(self) -> bool: ...
