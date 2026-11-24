from __future__ import annotations

from app.ai_engine.registry import get_registry
from tests.api.helpers import clone_voice, ready_voice
from tests.fakes import ExplodingTTS
from tests.media import probe_streams


def _generate(client, account, voice_id, **over):
    body = {"voice_id": voice_id, "text": "Hello there. This is a test.", "language": "en", "speed": 1.0,
            "output_format": "wav", **over}
    return client.post("/api/v1/speech/generate", headers=account.headers, json=body)


def test_generate_and_download_wav(client, alice, fakes, tmp_path):
    vid = ready_voice(client, alice)
    r = _generate(client, alice, vid)
    assert r.status_code == 202, r.text
    accepted = r.json()
    assert accepted["status"] in ("queued", "processing", "completed")
    job_id = accepted["job_id"]

    status = client.get(f"/api/v1/speech/{job_id}", headers=alice.headers).json()
    assert status["status"] == "completed" and status["progress"] == 100
    assert status["result"]["download_url"] == f"/api/v1/speech/{job_id}/download"
    assert status["result"]["duration_seconds"] > 0

    dl = client.get(f"/api/v1/speech/{job_id}/download", headers=alice.headers)
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("audio/wav")
    out = tmp_path / "out.wav"
    out.write_bytes(dl.content)
    info = probe_streams(out)
    assert info["audio"] and abs(info["duration"] - status["result"]["duration_seconds"]) < 0.2
    # the cloned voice's reference audio + profile were actually handed to the engine
    assert fakes.tts.calls and fakes.tts.calls[0]["profile"] is True


def test_output_formats(client, alice, fakes, tmp_path):
    vid = ready_voice(client, alice)
    for fmt, mime in (("mp3", "audio/mpeg"), ("flac", "audio/flac"), ("ogg", "audio/ogg"), ("m4a", "audio/mp4")):
        job_id = _generate(client, alice, vid, output_format=fmt).json()["job_id"]
        dl = client.get(f"/api/v1/speech/{job_id}/download", headers=alice.headers)
        assert dl.status_code == 200 and dl.headers["content-type"].startswith(mime), fmt
        p = tmp_path / f"o.{fmt}"
        p.write_bytes(dl.content)
        assert probe_streams(p)["audio"]


def test_speed_is_passed_to_engine(client, alice, fakes):
    vid = ready_voice(client, alice)
    _generate(client, alice, vid, speed=1.5)
    assert fakes.tts.calls[-1]["speed"] == 1.5


def test_long_text_is_chunked(client, alice, fakes):
    vid = ready_voice(client, alice)
    text = " ".join(f"Sentence number {i} is here." for i in range(40))
    job_id = _generate(client, alice, vid, text=text).json()["job_id"]
    assert len(fakes.tts.calls) > 1
    assert client.get(f"/api/v1/speech/{job_id}", headers=alice.headers).json()["status"] == "completed"


def test_validation(client, alice, fakes):
    vid = ready_voice(client, alice)
    assert _generate(client, alice, vid, language="ja").json()["error"]["code"] == "UNSUPPORTED_LANGUAGE"
    assert _generate(client, alice, vid, text="x" * 6000).status_code == 422
    assert _generate(client, alice, vid, speed=5).status_code == 422
    assert _generate(client, alice, vid, output_format="exe").status_code == 422
    assert _generate(client, alice, "voc_doesnotexist").status_code == 404


def test_voice_must_be_ready_and_owned(client, alice, bob, fakes):
    vid = ready_voice(client, alice)
    assert _generate(client, bob, vid).status_code == 404  # someone else's voice looks nonexistent


def test_speech_job_not_readable_by_other_user_or_other_endpoint(client, alice, bob, fakes):
    vid = ready_voice(client, alice)
    job_id = _generate(client, alice, vid).json()["job_id"]
    assert client.get(f"/api/v1/speech/{job_id}", headers=bob.headers).status_code == 404
    assert client.get(f"/api/v1/speech/{job_id}/download", headers=bob.headers).status_code == 404
    assert client.get(f"/api/v1/jobs/{job_id}", headers=bob.headers).status_code == 404
    assert client.get(f"/api/v1/transcription/{job_id}", headers=alice.headers).status_code == 404


def test_engine_failure_is_reported_on_the_job_not_as_500(client, alice, fakes):
    vid = ready_voice(client, alice)
    get_registry().override("text_to_speech", ExplodingTTS())
    r = _generate(client, alice, vid)
    assert r.status_code == 202
    job = client.get(f"/api/v1/speech/{r.json()['job_id']}", headers=alice.headers).json()
    assert job["status"] == "failed"
    assert job["error"]["code"] == "AI_ENGINE_ERROR"
    assert client.get(f"/api/v1/speech/{job['job_id']}/download", headers=alice.headers).json()["error"]["code"] == "JOB_NOT_READY"


def test_failed_clone_cannot_be_used(client, alice, fakes, monkeypatch):
    def boom(self, reference_wav, profile_path):
        from app.core.errors import AIEngineError

        raise AIEngineError("nope")

    monkeypatch.setattr(type(fakes.cloner), "prepare_voice", boom)
    vid = clone_voice(client, alice).json()["voice_id"]
    r = _generate(client, alice, vid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "VOICE_NOT_READY"
