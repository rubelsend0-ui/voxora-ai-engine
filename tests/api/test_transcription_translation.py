from __future__ import annotations

from tests.media import speechlike_wav


def _transcribe(client, account, **kw):
    return client.post(
        "/api/v1/transcription",
        headers=account.headers,
        data=kw.get("data", {}),
        files=kw.get("files", {"file": ("talk.wav", speechlike_wav(6, sr=16000), "audio/wav")}),
    )


def test_transcription_result_and_exports(client, alice, fakes):
    r = _transcribe(client, alice, data={"language": "en"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    body = client.get(f"/api/v1/transcription/{job_id}", headers=alice.headers).json()
    assert body["status"] == "completed"
    res = body["result"]
    assert res["language"] == "en" and res["text"].startswith("Hello world.")
    assert len(res["segments"]) == 2 and res["segments"][0]["start"] < res["segments"][0]["end"]

    srt = client.get(f"/api/v1/transcription/{job_id}/export?format=srt", headers=alice.headers)
    assert srt.status_code == 200 and "-->" in srt.text and srt.text.startswith("1\n00:00:00,500")
    vtt = client.get(f"/api/v1/transcription/{job_id}/export?format=vtt", headers=alice.headers)
    assert vtt.text.startswith("WEBVTT")
    txt = client.get(f"/api/v1/transcription/{job_id}/export?format=txt", headers=alice.headers)
    assert "Hello world." in txt.text
    assert client.get(f"/api/v1/transcription/{job_id}/export?format=pdf", headers=alice.headers).status_code == 422


def test_transcription_auto_language_and_mp3_upload(client, alice, fakes, tmp_path):
    import subprocess

    wav = tmp_path / "a.wav"
    wav.write_bytes(speechlike_wav(5))
    mp3 = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), str(mp3)], check=True)
    r = _transcribe(client, alice, files={"file": ("a.mp3", mp3.read_bytes(), "audio/mpeg")})
    assert r.status_code == 202
    assert client.get(f"/api/v1/transcription/{r.json()['job_id']}", headers=alice.headers).json()["status"] == "completed"


def test_transcription_via_file_id(client, alice, fakes):
    up = client.post("/api/v1/files", headers=alice.headers, files={"file": ("a.wav", speechlike_wav(5), "audio/wav")})
    assert up.status_code == 201
    fid = up.json()["file_id"]
    r = client.post("/api/v1/transcription", headers=alice.headers, data={"file_id": fid})
    assert r.status_code == 202
    assert r.json()["status"] in ("queued", "processing", "completed")


def test_transcription_input_validation(client, alice, fakes):
    assert _transcribe(client, alice, files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 415
    assert _transcribe(client, alice, files={"file": ("x.wav", b"junk" * 100, "audio/wav")}).status_code == 422
    assert client.post("/api/v1/transcription", headers=alice.headers).status_code == 422  # nothing provided
    both = client.post(
        "/api/v1/transcription", headers=alice.headers, data={"file_id": "fil_x"},
        files={"file": ("a.wav", speechlike_wav(3), "audio/wav")},
    )
    assert both.status_code == 422
    assert _transcribe(client, alice, data={"language": "english!!"}).status_code == 422


def test_other_users_file_id_is_not_usable(client, alice, bob, fakes):
    fid = client.post("/api/v1/files", headers=alice.headers,
                      files={"file": ("a.wav", speechlike_wav(5), "audio/wav")}).json()["file_id"]
    assert client.post("/api/v1/transcription", headers=bob.headers, data={"file_id": fid}).status_code == 404


def test_text_translation(client, alice, fakes):
    r = client.post("/api/v1/translation/text", headers=alice.headers,
                    json={"text": "Hello.\nHow are you?", "source_language": "en", "target_language": "es"})
    assert r.status_code == 200, r.text
    assert r.json()["translated_text"].count("\n") == 1 and "[es]" in r.json()["translated_text"]
    same = client.post("/api/v1/translation/text", headers=alice.headers,
                       json={"text": "x", "source_language": "en", "target_language": "en"})
    assert same.status_code == 422
    nopair = client.post("/api/v1/translation/text", headers=alice.headers,
                         json={"text": "x", "source_language": "xx", "target_language": "en"})
    assert nopair.status_code == 503 and nopair.json()["error"]["code"] == "AI_ENGINE_NOT_CONFIGURED"


def test_audio_translation_job_and_exports(client, alice, fakes):
    r = client.post("/api/v1/translation/audio", headers=alice.headers, data={"target_language": "es"},
                    files={"file": ("a.wav", speechlike_wav(6), "audio/wav")})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    res = client.get(f"/api/v1/translation/{job_id}", headers=alice.headers).json()["result"]
    assert res["target_language"] == "es" and res["translated"]["segments"][0]["text"].startswith("[es]")
    srt = client.get(f"/api/v1/translation/{job_id}/export?format=srt", headers=alice.headers)
    assert "[es] Hello world." in srt.text
    src = client.get(f"/api/v1/translation/{job_id}/export?format=srt&track=source", headers=alice.headers)
    assert "[es]" not in src.text and "Hello world." in src.text
