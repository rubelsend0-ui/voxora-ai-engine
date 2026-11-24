"""No fakes installed: with no models downloaded the API must say so - never fake a result."""

from __future__ import annotations

import pytest

from app.ai_engine.registry import get_registry
from tests.api.helpers import clone_voice
from tests.media import speechlike_wav


@pytest.fixture()
def no_models(client):
    st = get_registry().statuses()
    if any(st[k].available for k in ("voice_cloning", "text_to_speech", "speech_to_text", "translation")):
        pytest.skip("AI models are installed on this machine; this test needs a machine without them")


def test_engines_endpoint_reports_reasons(client, alice, no_models):
    rows = {r["engine"]: r for r in client.get("/api/v1/engines", headers=alice.headers).json()}
    assert rows["audio_processing"]["available"] is True  # FFmpeg is required by CI
    for kind in ("voice_cloning", "text_to_speech", "speech_to_text", "translation", "dubbing"):
        assert rows[kind]["available"] is False
        assert rows[kind]["reason"]


def _assert_not_configured(r, engine=None):
    assert r.status_code == 503, r.text
    err = r.json()["error"]
    assert err["code"] == "AI_ENGINE_NOT_CONFIGURED"
    assert err["details"]["reason"]
    if engine:
        assert err["details"]["engine"] == engine


def test_clone_without_engine(client, alice, no_models):
    _assert_not_configured(clone_voice(client, alice), "voice_cloning")


def test_speech_without_engine(client, alice, no_models):
    r = client.post(
        "/api/v1/speech/generate",
        headers=alice.headers,
        json={"voice_id": "voc_x", "text": "hello", "language": "en"},
    )
    _assert_not_configured(r, "text_to_speech")


def test_transcription_without_engine(client, alice, no_models):
    r = client.post(
        "/api/v1/transcription", headers=alice.headers, files={"file": ("a.wav", speechlike_wav(3), "audio/wav")}
    )
    _assert_not_configured(r, "speech_to_text")


def test_translation_without_engine(client, alice, no_models):
    r = client.post(
        "/api/v1/translation/text",
        headers=alice.headers,
        json={"text": "hi", "source_language": "en", "target_language": "es"},
    )
    _assert_not_configured(r, "translation")


def test_dubbing_without_engine(client, alice, no_models):
    r = client.post(
        "/api/v1/dubbing",
        headers=alice.headers,
        data={"target_language": "es", "voice_id": "voc_x"},
        files={"input_file": ("a.wav", speechlike_wav(3), "audio/wav")},
    )
    _assert_not_configured(r)
