"""Shared fixtures.

The API tests run the *real* application (FastAPI, SQLAlchemy/SQLite, local storage, FFmpeg, the real
dubbing pipeline). Only the four neural models (voice cloning, TTS, STT, translation) are replaced with
the deterministic test doubles in ``tests/fakes.py`` - they are never part of ``app/``.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

# Safe defaults before any ``app`` import (app.main builds an app object at import time).
os.environ.setdefault("VOXORA_ENVIRONMENT", "test")
os.environ.setdefault("VOXORA_DATA_DIR", "/tmp/voxora-test-import")

from fastapi.testclient import TestClient  # noqa: E402

from app.ai_engine.registry import get_registry  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.rate_limit import get_rate_limiter  # noqa: E402
from app.core.security import generate_api_key, hash_api_key  # noqa: E402
from app.database.session import create_all_tables, reset_database_state, session_scope  # noqa: E402
from app.models import ApiKey, User  # noqa: E402
from app.storage.local import get_storage  # noqa: E402
from app.workers.executor import reset_executor  # noqa: E402

PEPPER = "test-pepper-0123456789-0123456789-abcdef"


def reset_caches() -> None:
    reset_executor()
    get_settings.cache_clear()
    reset_database_state()
    get_storage.cache_clear()
    get_registry.cache_clear()
    get_rate_limiter.cache_clear()


def set_env(tmp_path: Path, monkeypatch, **overrides: str) -> None:
    values = {
        "VOXORA_ENVIRONMENT": "test",
        "VOXORA_DATA_DIR": str(tmp_path / "data"),
        "VOXORA_DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}",
        "VOXORA_JOB_BACKEND": "inline",
        "VOXORA_API_KEY_PEPPER": PEPPER,
        "VOXORA_RATE_LIMIT_PER_MINUTE": "1000",
        "VOXORA_RATE_LIMIT_HEAVY_PER_MINUTE": "1000",
        "VOXORA_AUTO_CREATE_TABLES": "true",
    }
    values.update(overrides)
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    reset_caches()


@dataclass
class Account:
    id: str
    email: str
    key: str

    @property
    def headers(self) -> dict[str, str]:
        return {"X-API-Key": self.key}


def make_account(email: str) -> Account:
    raw, prefix = generate_api_key()
    with session_scope() as db:
        user = User(email=email, display_name=email.split("@")[0])
        db.add(user)
        db.flush()
        db.add(ApiKey(user_id=user.id, name="test", key_prefix=prefix, key_hash=hash_api_key(raw, PEPPER)))
        uid = user.id
    return Account(id=uid, email=email, key=raw)


@pytest.fixture()
def make_client(tmp_path, monkeypatch):
    from app.main import create_app

    opened: list[TestClient] = []

    def _make(**overrides: str) -> TestClient:
        set_env(tmp_path, monkeypatch, **overrides)
        client = TestClient(create_app())
        client.__enter__()  # runs lifespan: dirs + tables
        create_all_tables()
        opened.append(client)
        return client

    yield _make
    for c in opened:
        c.__exit__(None, None, None)
    reset_caches()


@pytest.fixture()
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture()
def alice(client) -> Account:
    return make_account("alice@example.com")


@pytest.fixture()
def bob(client) -> Account:
    return make_account("bob@example.com")


@pytest.fixture()
def fakes(client):
    """Install deterministic doubles for the four neural engines."""
    from tests.fakes import install_fakes

    return install_fakes(get_registry())


def poll_job(client: TestClient, account: Account, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while True:
        r = client.get(f"/api/v1/jobs/{job_id}", headers=account.headers)
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in ("completed", "failed") or time.time() > deadline:
            return body
        time.sleep(0.2)
