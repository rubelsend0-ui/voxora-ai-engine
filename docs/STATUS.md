# Verification status (be aware before relying on this)

The code was written in a sandbox **without internet access**: FastAPI, SQLAlchemy, pytest, Celery, PyTorch and the
model weights could not be installed there. What was and was not verified:

| Item | Status |
|---|---|
| Every Python file compiles; no undefined names / unresolved intra-project imports (static check) | verified |
| 67 unit tests: subtitles, text splitting, storage (incl. traversal/size limits), audio-quality analysis, sync planner, rate limiter, API-key hashing, language/file helpers, engine registry + `AI_ENGINE_NOT_CONFIGURED` | **executed and passing** (with a tiny pytest/pydantic shim) |
| FFmpeg engine against real FFmpeg: probe, mp3/flac/ogg/m4a/wav encode, tempo, timeline assembly, voice-reference trim, video mux, corrupt-file rejection | **executed and passing** |
| FastAPI app, routers, SQLAlchemy models/services, Celery wiring, Alembic migration | **written but NOT executed** |
| API test suite (`tests/api`, ~60 tests), migration-vs-models test | **written but NOT executed** - run them first |
| XTTS-v2 / Whisper / MarianMT adapters | **written against the libraries' documented APIs, NOT executed** |
| Docker images, compose files, GitHub Actions | YAML validated only; images **not built** |
| Dependency version ranges together (`requirements-ai.txt`) | **not install-tested** |

Expect a few small fixes on first run - that is normal for code that has never executed. Suggested order:

1. `pip install -r requirements-dev.txt && pytest tests/unit tests/api` - fix anything red (fast, no models).
2. Install torch + `requirements-ai.txt`, download models, `python -m scripts.doctor`.
3. `VOXORA_RUN_MODEL_TESTS=1 pytest tests/integration -s` with a short consented reference clip: clone -> TTS ->
   Whisper round trip proves the real models work end to end.
4. Build the Docker images.

## Known limitations (by design, also reported by the API)

* Cloning = zero-shot profile (reference audio + cached latents). Not a fine-tuned model; reference audio is required at synthesis.
* Dubbing: no lip-sync, one voice for all speakers (no diarisation), no background-music separation, timing is fitted by tempo/delay only.
* Consent is an attestation, not identity verification.
* Storage backend is local filesystem. API and workers must share it (one host or a shared volume). S3 needs a new `StorageBackend`.
* Local job backend is single-process; use Celery for several API workers. Jobs are not cancellable yet.
* Dubbing timeline is assembled in memory: capped at `VOXORA_DUBBING_MAX_SECONDS` (default 30 min).
