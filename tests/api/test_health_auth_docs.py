from __future__ import annotations

REQUIRED_OPERATIONS = {
    ("post", "/api/v1/voices/clone"),
    ("post", "/api/v1/voices"),
    ("get", "/api/v1/voices"),
    ("get", "/api/v1/voices/{voice_id}"),
    ("patch", "/api/v1/voices/{voice_id}"),
    ("delete", "/api/v1/voices/{voice_id}"),
    ("post", "/api/v1/speech/generate"),
    ("get", "/api/v1/speech/{job_id}"),
    ("get", "/api/v1/speech/{job_id}/download"),
    ("post", "/api/v1/transcription"),
    ("get", "/api/v1/transcription/{job_id}"),
    ("get", "/api/v1/transcription/{job_id}/export"),
    ("post", "/api/v1/translation/text"),
    ("post", "/api/v1/translation/audio"),
    ("post", "/api/v1/dubbing"),
    ("get", "/api/v1/dubbing/{job_id}"),
    ("get", "/api/v1/dubbing/{job_id}/download"),
    ("get", "/api/v1/jobs/{job_id}"),
    ("get", "/api/v1/jobs"),
    ("post", "/api/v1/projects"),
    ("post", "/api/v1/files"),
}


def test_health_is_public(client):
    assert client.get("/health/live").json() == {"status": "ok"}
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["checks"] == {"database": True, "storage": True}
    assert set(body["engines"]) >= {"audio_processing", "speech_to_text", "text_to_speech", "voice_cloning"}


def test_docs_endpoints_exist_and_cover_the_spec(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    spec = client.get("/openapi.json").json()
    ops = {(m, p) for p, item in spec["paths"].items() for m in item}
    missing = REQUIRED_OPERATIONS - ops
    assert not missing, f"missing from OpenAPI: {missing}"


def test_missing_key_is_401_with_error_envelope(client):
    r = client.get("/api/v1/voices")
    assert r.status_code == 401
    err = r.json()["error"]
    assert err["code"] == "UNAUTHORIZED"
    assert r.json()["request_id"]


def test_invalid_key_is_401(client):
    r = client.get("/api/v1/voices", headers={"X-API-Key": "vx_not-a-real-key"})
    assert r.status_code == 401


def test_valid_key_via_header_and_bearer(client, alice):
    assert client.get("/api/v1/auth/me", headers=alice.headers).json()["email"] == "alice@example.com"
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {alice.key}"})
    assert r.status_code == 200


def test_request_id_is_echoed(client, alice):
    r = client.get("/api/v1/auth/me", headers={**alice.headers, "X-Request-ID": "abc-123"})
    assert r.headers["X-Request-ID"] == "abc-123"


def test_unknown_route_uses_envelope(client, alice):
    r = client.get("/api/v1/nope", headers=alice.headers)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_validation_errors_use_envelope(client, alice):
    r = client.post("/api/v1/speech/generate", headers=alice.headers, json={"text": ""})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
