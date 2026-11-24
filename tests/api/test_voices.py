from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from tests.api.helpers import clone_voice, ready_voice
from tests.media import silent_wav, speechlike_wav


def test_clone_creates_ready_voice_with_honest_profile(client, alice, fakes):
    r = clone_voice(client, alice)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["voice_id"].startswith("voc_") and body["job_id"].startswith("job_")
    voice = body["voice"]
    assert voice["status"] == "ready"
    assert voice["profile"]["requires_reference_audio"] is True
    assert "not a fine-tuned model" in voice["profile"]["notes"]
    assert voice["consent"]["holder_name"] == "Alice Example"
    assert voice["quality"]["ok"] is True
    # internal storage paths are never exposed
    assert "storage" not in r.text and "reference.wav" not in r.text and "/tmp" not in r.text


def test_clone_alias_post_voices(client, alice, fakes):
    r = client.post(
        "/api/v1/voices",
        headers=alice.headers,
        data={"name": "x", "consent_confirmed": "true", "consent_holder_name": "A"},
        files={"file": ("s.wav", speechlike_wav(10), "audio/wav")},
    )
    assert r.status_code == 202


def test_job_status_is_pollable(client, alice, fakes):
    body = clone_voice(client, alice).json()
    job = client.get(f"/api/v1/jobs/{body['job_id']}", headers=alice.headers).json()
    assert job["status"] == "completed" and job["progress"] == 100
    assert job["type"] == "voice_clone"


def test_consent_is_mandatory(client, alice, fakes):
    r = clone_voice(client, alice, data={"consent_confirmed": "false"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONSENT_REQUIRED"
    r = clone_voice(client, alice, data={"consent_holder_name": ""})
    assert r.status_code == 422


def test_too_short_sample_rejected(client, alice, fakes):
    r = clone_voice(client, alice, wav=speechlike_wav(2))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "AUDIO_TOO_SHORT"


def test_silent_sample_rejected_by_quality_check(client, alice, fakes):
    r = clone_voice(client, alice, wav=silent_wav(10))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "AUDIO_QUALITY_INSUFFICIENT"


def test_quiet_and_clipped_samples_rejected(client, alice, fakes):
    assert clone_voice(client, alice, wav=speechlike_wav(10, amp=0.0005)).status_code == 422
    assert clone_voice(client, alice, wav=speechlike_wav(10, amp=6.0)).status_code == 422


def test_wrong_extension_rejected(client, alice, fakes):
    r = clone_voice(client, alice, filename="sample.exe")
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_garbage_with_audio_extension_rejected(client, alice, fakes):
    r = clone_voice(client, alice, wav=b"this is definitely not audio" * 50)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "AUDIO_INVALID"


def test_library_crud(client, alice, fakes):
    vid = ready_voice(client, alice)
    assert client.get(f"/api/v1/voices/{vid}", headers=alice.headers).json()["name"] == "Alice voice"
    page = client.get("/api/v1/voices", headers=alice.headers).json()
    assert page["total"] == 1 and page["items"][0]["voice_id"] == vid
    assert client.get("/api/v1/voices?status=failed", headers=alice.headers).json()["total"] == 0

    r = client.patch(f"/api/v1/voices/{vid}", headers=alice.headers, json={"name": "Renamed", "description": "d"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["description"] == "d"

    assert client.delete(f"/api/v1/voices/{vid}", headers=alice.headers).status_code == 204
    assert client.get(f"/api/v1/voices/{vid}", headers=alice.headers).status_code == 404


def test_delete_removes_stored_biometric_files(client, alice, fakes):
    vid = ready_voice(client, alice)
    voice_dir = Path(get_settings().storage_root) / "voices" / alice.id / vid
    assert (voice_dir / "reference.wav").is_file() and (voice_dir / "profile.pt").is_file()
    assert not (voice_dir / "source.wav").exists()  # raw sample is not retained
    client.delete(f"/api/v1/voices/{vid}", headers=alice.headers)
    assert not voice_dir.exists()


def test_users_cannot_see_or_change_each_others_voices(client, alice, bob, fakes):
    vid = ready_voice(client, alice)
    assert client.get(f"/api/v1/voices/{vid}", headers=bob.headers).status_code == 404
    assert client.patch(f"/api/v1/voices/{vid}", headers=bob.headers, json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/voices/{vid}", headers=bob.headers).status_code == 404
    assert client.get("/api/v1/voices", headers=bob.headers).json()["total"] == 0


def test_engine_failure_marks_voice_and_job_failed(client, alice, fakes, monkeypatch):
    def boom(self, reference_wav, profile_path):
        from app.core.errors import AIEngineError

        raise AIEngineError("profile failed")

    monkeypatch.setattr(type(fakes.cloner), "prepare_voice", boom)
    r = clone_voice(client, alice)
    assert r.status_code == 202
    body = r.json()
    assert body["voice"]["status"] == "failed"
    assert body["voice"]["error"]["code"] == "AI_ENGINE_ERROR"
    job = client.get(f"/api/v1/jobs/{body['job_id']}", headers=alice.headers).json()
    assert job["status"] == "failed" and job["error"]["code"] == "AI_ENGINE_ERROR"
    voice_dir = Path(get_settings().storage_root) / "voices" / alice.id / body["voice_id"]
    assert not voice_dir.exists()  # nothing biometric left behind after a failure
