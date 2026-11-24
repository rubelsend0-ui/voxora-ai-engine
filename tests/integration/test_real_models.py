"""OPT-IN end-to-end test with the REAL models (XTTS-v2, Whisper, MarianMT).

Run on a machine where the models are downloaded:

    VOXORA_RUN_MODEL_TESTS=1 pytest tests/integration -s

Requires a short *consented* reference recording at tests/integration/reference.wav (>= 6 s of clear speech).
It is not shipped with the repository. The test synthesizes speech with the cloned voice, transcribes it with
Whisper and checks the words round-trip - the only meaningful automatic check that the models really work.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REFERENCE = Path(__file__).parent / "reference.wav"
pytestmark = pytest.mark.skipif(
    os.environ.get("VOXORA_RUN_MODEL_TESTS") != "1" or not REFERENCE.is_file(),
    reason="set VOXORA_RUN_MODEL_TESTS=1 and provide tests/integration/reference.wav",
)


def test_clone_tts_transcribe_roundtrip(make_client):
    from tests.conftest import make_account

    client = make_client(VOXORA_JOB_BACKEND="inline", VOXORA_DATA_DIR=os.environ.get("VOXORA_DATA_DIR", "./data"))
    acct = make_account("real@example.com")
    r = client.post(
        "/api/v1/voices/clone", headers=acct.headers,
        data={"name": "real", "consent_confirmed": "true", "consent_holder_name": "Test", "language": "en"},
        files={"file": ("reference.wav", REFERENCE.read_bytes(), "audio/wav")},
    )
    assert r.status_code == 202, r.text
    assert r.json()["voice"]["status"] == "ready", r.json()
    vid = r.json()["voice_id"]

    text = "The quick brown fox jumps over the lazy dog."
    job = client.post("/api/v1/speech/generate", headers=acct.headers,
                      json={"voice_id": vid, "text": text, "language": "en"}).json()["job_id"]
    assert client.get(f"/api/v1/speech/{job}", headers=acct.headers).json()["status"] == "completed"
    audio = client.get(f"/api/v1/speech/{job}/download", headers=acct.headers).content

    tr = client.post("/api/v1/transcription", headers=acct.headers, data={"language": "en"},
                     files={"file": ("out.wav", audio, "audio/wav")}).json()["job_id"]
    result = client.get(f"/api/v1/transcription/{tr}", headers=acct.headers).json()["result"]
    heard = result["text"].lower()
    assert "quick" in heard and "fox" in heard and "lazy" in heard, heard
