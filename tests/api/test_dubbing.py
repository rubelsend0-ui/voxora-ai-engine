"""Runs the REAL PipelineDubbingEngine + FFmpeg + storage + DB; only the neural models are doubles."""

from __future__ import annotations

from tests.api.helpers import ready_voice
from tests.media import make_video, probe_streams, speechlike_wav


def _dub(client, account, voice_id, files, **data):
    payload = {"target_language": "es", "voice_id": voice_id, "source_language": "en", **data}
    return client.post("/api/v1/dubbing", headers=account.headers, data=payload, files=files)


def test_video_dubbing_end_to_end(client, alice, fakes, tmp_path):
    vid = ready_voice(client, alice)
    video = make_video(tmp_path / "in.mp4", seconds=6)
    r = _dub(client, alice, vid, {"input_file": ("clip.mp4", video, "video/mp4")})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    job = client.get(f"/api/v1/dubbing/{job_id}", headers=alice.headers).json()
    assert job["status"] == "completed", job
    res = job["result"]
    assert res["format"] == "mp4" and res["target_language"] == "es"
    assert [s["text"] for s in res["translated_segments"]][0].startswith("[es] Hello world.")
    assert res["sync"]["segments"] == 2
    assert any("lip" in lim.lower() for lim in res["limitations"])  # limitations are reported honestly
    assert job["result"]["download_url"] == f"/api/v1/dubbing/{job_id}/download"

    dl = client.get(f"/api/v1/dubbing/{job_id}/download", headers=alice.headers)
    assert dl.status_code == 200 and dl.headers["content-type"].startswith("video/mp4")
    out = tmp_path / "out.mp4"
    out.write_bytes(dl.content)
    info = probe_streams(out)
    assert info["video"] and info["audio"] and abs(info["duration"] - 6.0) < 0.6
    # every segment was synthesized with the selected cloned voice in the target language
    assert {c["language"] for c in fakes.tts.calls} == {"es"}

    srt = client.get(f"/api/v1/dubbing/{job_id}/subtitles?format=srt", headers=alice.headers)
    assert srt.status_code == 200 and "-->" in srt.text


def test_audio_only_dubbing_to_mp3(client, alice, fakes, tmp_path):
    vid = ready_voice(client, alice)
    r = _dub(client, alice, vid, {"input_file": ("talk.wav", speechlike_wav(6), "audio/wav")}, output_format="mp3")
    job_id = r.json()["job_id"]
    assert client.get(f"/api/v1/dubbing/{job_id}", headers=alice.headers).json()["status"] == "completed"
    dl = client.get(f"/api/v1/dubbing/{job_id}/download", headers=alice.headers)
    assert dl.headers["content-type"].startswith("audio/mpeg")


def test_mp4_output_requires_video_input(client, alice, fakes):
    vid = ready_voice(client, alice)
    r = _dub(client, alice, vid, {"input_file": ("talk.wav", speechlike_wav(6), "audio/wav")}, output_format="mp4")
    assert r.status_code == 422


def test_dubbing_validation_and_ownership(client, alice, bob, fakes, tmp_path):
    vid = ready_voice(client, alice)
    video = make_video(tmp_path / "in.mp4", seconds=3)
    files = {"input_file": ("clip.mp4", video, "video/mp4")}
    assert _dub(client, bob, vid, files).status_code == 404  # not bob's voice
    assert _dub(client, alice, vid, files, target_language="ja").json()["error"]["code"] == "UNSUPPORTED_LANGUAGE"
    assert _dub(client, alice, vid, files, original_audio_volume="3").status_code == 422
    assert _dub(client, alice, vid, files, output_format="exe").status_code == 422
    assert _dub(client, alice, vid, {"input_file": ("a.txt", b"x", "text/plain")}).status_code == 415


def test_dubbing_with_background_mix(client, alice, fakes, tmp_path):
    vid = ready_voice(client, alice)
    video = make_video(tmp_path / "in.mp4", seconds=6)
    r = _dub(client, alice, vid, {"input_file": ("c.mp4", video, "video/mp4")}, original_audio_volume="0.3")
    assert client.get(f"/api/v1/dubbing/{r.json()['job_id']}", headers=alice.headers).json()["status"] == "completed"
