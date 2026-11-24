"""Local-filesystem storage backend."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import uuid
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings
from app.core.errors import PayloadTooLarge, ValidationFailed
from app.storage.base import CATEGORIES, StorageBackend, StoredObject

_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
_EXT = re.compile(r"^[a-z0-9]{1,8}$")
_CHUNK = 1024 * 1024


class LocalStorage(StorageBackend):
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        for cat in CATEGORIES:
            (self.root / cat).mkdir(parents=True, exist_ok=True)

    # ----------------------------------------------------------------- keys
    def build_key(self, category: str, *parts: str) -> str:
        if category not in CATEGORIES:
            raise ValueError(f"Unknown storage category: {category}")
        for p in parts:
            if not _PART.match(p) or ".." in p:
                raise ValueError(f"Illegal storage key component: {p!r}")
        return "/".join([category, *parts])

    def new_key(self, category: str, user_id: str, ext: str) -> str:
        ext = ext.lower().lstrip(".")
        if not _EXT.match(ext):
            raise ValueError("Illegal extension")
        return self.build_key(category, user_id, f"{uuid.uuid4().hex}.{ext}")

    def _resolve(self, key: str) -> Path:
        parts = key.split("/")
        if len(parts) < 2 or parts[0] not in CATEGORIES:
            raise ValueError("Illegal storage key")
        for p in parts[1:]:
            if not _PART.match(p) or ".." in p:
                raise ValueError("Illegal storage key")
        path = (self.root / key).resolve()
        if self.root not in path.parents:  # defence in depth against traversal / symlinks
            raise ValueError("Illegal storage key")
        return path

    # ------------------------------------------------------------- writing
    def save_stream(self, key: str, stream: BinaryIO, max_bytes: int | None = None) -> StoredObject:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256()
        size = 0
        try:
            with open(path, "wb") as out:
                while True:
                    chunk = stream.read(_CHUNK)
                    if not chunk:
                        break
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise PayloadTooLarge(
                            f"The file exceeds the maximum size of {max_bytes // (1024 * 1024)} MB.",
                            details={"max_bytes": max_bytes},
                        )
                    h.update(chunk)
                    out.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        if size == 0:
            path.unlink(missing_ok=True)
            raise ValidationFailed("The uploaded file is empty.")
        return StoredObject(key=key, size_bytes=size, sha256=h.hexdigest())

    def put_file(self, key: str, src: Path, *, move: bool = False) -> StoredObject:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(src), str(path))
        else:
            shutil.copyfile(src, path)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(_CHUNK), b""):
                h.update(chunk)
        return StoredObject(key=key, size_bytes=path.stat().st_size, sha256=h.hexdigest())

    def move(self, src_key: str, dst_key: str) -> None:
        dst = self._resolve(dst_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(self._resolve(src_key)), str(dst))

    # ------------------------------------------------------------- reading
    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def local_path(self, key: str) -> Path:
        return self._resolve(key)

    # ------------------------------------------------------------- deleting
    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        parts = prefix.strip("/").split("/")
        if len(parts) < 3:  # refuse to wipe a whole category or user tree by accident
            raise ValueError("Prefix too broad")
        path = self._resolve(prefix.strip("/"))
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    def healthy(self) -> bool:
        probe = self.root / "tmp" / f".health-{uuid.uuid4().hex}"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
            return True
        except OSError:
            return False


@lru_cache
def get_storage() -> StorageBackend:
    s = get_settings()
    os.makedirs(s.tmp_root, exist_ok=True)
    return LocalStorage(s.storage_root)
