# Architecture

```
Android / web client
        |  HTTPS + X-API-Key
   FastAPI  (app/api)  --- validation, auth, rate limits, error envelope
        |
   services (app/services) --- business rules, ownership checks, consent, job creation
        |                \
   database (SQLAlchemy)   workers (app/workers): executor -> run_job -> handler(ctx)
   SQLite | PostgreSQL        local thread pool | Celery+Redis | inline (tests)
        |                          |
   storage (app/storage)     ai_engine (ports + adapters + registry)
   local FS, key-based       VoiceCloning / TextToSpeech / SpeechToText / Translation /
                             AudioProcessing / Dubbing
```

## Rules that keep it replaceable
* Routes call **services**; services call **engine interfaces** from `app/ai_engine/base.py`; only
  `registry.py` knows adapter class names. Swap a model = new adapter + one setting.
* One adapter may serve two interfaces (XTTS-v2 does cloning and TTS and shares one loaded model).
* `PipelineDubbingEngine` composes the other engines; it works on local paths and knows nothing of the DB.
* Every job type is `submit_*` (sync validation, fast 4xx, fail-fast `AI_ENGINE_NOT_CONFIGURED`) + `handle_*`
  (runs in the worker, reports progress, returns a JSON result containing file ids only).

## Storage
Metadata (users, keys, voices, files, jobs, projects) in SQL. Bytes on a `StorageBackend` addressed by opaque keys
(`uploads/`, `voices/`, `generated/`, `exports/`, `tmp/`). Model weights live in a separate `VOXORA_MODELS_DIR`.
Storage paths are never returned to clients; downloads go through authenticated endpoints.
Voice raw samples are deleted after profile creation and all voice files are deleted with the voice or on failure.

## Security
API keys (HMAC-SHA256 with a server pepper, shown once) - per-user ownership checks on every read/write (foreign ids
are 404) - extension allow-list + FFmpeg decode check + streaming size cap - per-user and heavy-endpoint rate limits,
per-IP throttle on failed auth (Redis-shared when configured) - CORS off unless configured - consent attestation stored
with each voice (version, holder, time, keyed-hash of client IP) - production refuses to start with a weak pepper.

## Voice cloning, honestly
XTTS-v2 is zero-shot: `prepare_voice` caches conditioning latents next to the processed reference audio. The profile
reports `requires_reference_audio: true`. A fine-tuning adapter could report `false`.

## Extending
Add an adapter class, register it with `EngineRegistry.register_adapter(kind, name, factory)` (or in `registry.py`),
select it via `VOXORA_<KIND>_ADAPTER`. For S3, implement `StorageBackend` (`local_path` must materialise a temp file).
