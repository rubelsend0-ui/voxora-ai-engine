# VOXORA AI Engine

Self-hosted AI voice platform with its own REST API: **voice cloning, voice library, text-to-speech,
speech-to-text, translation, AI dubbing, projects and file management**. Backend only - build the Android/web
client separately against the OpenAPI spec (`/docs`, `/redoc`, `/openapi.json`).

* No third-party voice APIs. Open models run on your hardware: **XTTS-v2** (cloning + TTS), **Whisper** via
  faster-whisper (STT), **OPUS-MT/MarianMT** (translation), **FFmpeg** (media).
* **No fake output.** If a model is not installed the API answers `503 AI_ENGINE_NOT_CONFIGURED` with a setup hint.
* Replaceable models through adapters (`app/ai_engine/adapters`) - routes never import a model.
* Async jobs (`queued -> processing -> completed | failed`, progress 0-100) on Celery+Redis, or an in-process
  thread pool for simple setups.

> **Read first:** [docs/STATUS.md](docs/STATUS.md) (what has and has not been verified) and
> [docs/LICENSES.md](docs/LICENSES.md) - **XTTS-v2 weights are non-commercial (CPML)**.

## Quick start (local, CPU)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
sudo apt install ffmpeg libsndfile1                     # or: brew install ffmpeg
pip install -r requirements.txt
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-ai.txt
cp .env.example .env
python -m scripts.download_models --whisper small --translation en-es,es-en --xtts --accept-coqui-cpml
python -m scripts.doctor                                # every engine should say OK
python -m scripts.create_api_key --email you@example.com --name android
uvicorn app.main:app --reload                           # http://localhost:8000/docs
```

NVIDIA GPU: install torch from the `cu124` index instead, set `VOXORA_DEVICE=auto` (default). Docker, Linux
server and Celery setups: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Without any ML packages the API still
starts (useful for client development) and AI endpoints return `AI_ENGINE_NOT_CONFIGURED`.

## Endpoints (all under `/api/v1`, header `X-API-Key`)

| Area | Endpoints |
|---|---|
| Voice cloning | `POST /voices/clone` (alias `POST /voices`) |
| Voice library | `GET /voices`, `GET/PATCH/DELETE /voices/{voice_id}` |
| Text to speech | `POST /speech/generate`, `GET /speech/{job_id}`, `GET /speech/{job_id}/download` |
| Speech to text | `POST /transcription`, `GET /transcription/{job_id}`, `GET /transcription/{job_id}/export?format=txt\|srt\|vtt` |
| Translation | `POST /translation/text`, `POST /translation/audio`, `GET /translation/{job_id}[/export]` |
| Dubbing | `POST /dubbing`, `GET /dubbing/{job_id}`, `.../download`, `.../subtitles` |
| Jobs | `GET /jobs`, `GET /jobs/{job_id}` |
| Projects / files | `/projects[/{id}[/jobs]]`, `/files[/{id}[/download]]` |
| System | `GET /auth/me`, `GET /engines`; unauthenticated `GET /health/live`, `GET /health/ready` |

Full walkthrough with curl and Kotlin: [docs/API_GUIDE.md](docs/API_GUIDE.md).

## Project layout

```
app/api  core  database  models  schemas  services  ai_engine(+adapters)  workers  storage  utils
alembic/ tests/(unit api integration) scripts/ docs/ docker/ .github/workflows/
```
Design notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/unit tests/api                 # needs ffmpeg; models are NOT needed
VOXORA_RUN_MODEL_TESTS=1 pytest tests/integration -s   # real models, opt-in (see the file's docstring)
```

## Responsible use

Cloning requires `consent_confirmed=true` plus the speaker's name; consent metadata is stored with the voice.
That is an **attestation, not verification** - the service cannot prove who is speaking. If you expose this to
the public, add identity/liveness verification, abuse monitoring and, where required, watermarking/disclosure.
