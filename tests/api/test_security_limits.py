from __future__ import annotations

from tests.conftest import make_account
from tests.media import speechlike_wav


def test_rate_limit_returns_429_with_retry_after(make_client):
    client = make_client(VOXORA_RATE_LIMIT_PER_MINUTE="3")
    acct = make_account("rl@example.com")
    for _ in range(3):
        assert client.get("/api/v1/auth/me", headers=acct.headers).status_code == 200
    r = client.get("/api/v1/auth/me", headers=acct.headers)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert int(r.headers["Retry-After"]) >= 1


def test_heavy_endpoints_have_a_stricter_limit(make_client):
    client = make_client(VOXORA_RATE_LIMIT_HEAVY_PER_MINUTE="2")
    acct = make_account("heavy@example.com")
    body = {"voice_id": "voc_x", "text": "hi", "language": "en"}
    codes = [client.post("/api/v1/speech/generate", headers=acct.headers, json=body).status_code for _ in range(4)]
    assert codes[-1] == 429 and 429 not in codes[:2]


def test_repeated_bad_keys_are_throttled_per_ip(make_client):
    client = make_client(VOXORA_AUTH_FAIL_LIMIT_PER_MINUTE="3")
    codes = [client.get("/api/v1/voices", headers={"X-API-Key": f"vx_bad{i}"}).status_code for i in range(6)]
    assert codes[:3] == [401, 401, 401] and codes[-1] == 429


def test_upload_size_limit_enforced(make_client):
    client = make_client(VOXORA_MAX_UPLOAD_MB="1")
    acct = make_account("big@example.com")
    big = speechlike_wav(60, sr=16000)  # ~1.9 MB
    assert len(big) > 1024 * 1024
    r = client.post("/api/v1/files", headers=acct.headers, files={"file": ("big.wav", big, "audio/wav")})
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_cors_disabled_by_default_and_configurable(make_client):
    c1 = make_client()
    r = c1.options("/api/v1/voices", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers
    c2 = make_client(VOXORA_CORS_ORIGINS="https://app.example")
    r = c2.options("/api/v1/voices", headers={"Origin": "https://app.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "https://app.example"


def test_revoked_key_stops_working(client, alice):
    from app.database.session import session_scope
    from app.models import ApiKey
    from app.utils.ids import utcnow

    assert client.get("/api/v1/auth/me", headers=alice.headers).status_code == 200
    with session_scope() as db:
        for k in db.query(ApiKey).all():
            k.revoked_at = utcnow()
    assert client.get("/api/v1/auth/me", headers=alice.headers).status_code == 401


def test_production_requires_a_real_pepper(monkeypatch, tmp_path):
    import pytest

    from app.core.config import Settings

    monkeypatch.setenv("VOXORA_ENVIRONMENT", "production")
    monkeypatch.delenv("VOXORA_API_KEY_PEPPER", raising=False)
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path)
