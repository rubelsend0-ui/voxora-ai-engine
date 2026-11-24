# API integration guide

Base URL `http://HOST:8000/api/v1` · interactive docs `/docs`, `/redoc`, schema `/openapi.json`.

## 1. Authenticate
Create a key on the server: `python -m scripts.create_api_key --email you@example.com --name android`
(printed once). Send it on every request: `X-API-Key: vx_...` (or `Authorization: Bearer vx_...`).
Check it: `GET /auth/me`. Check engines: `GET /engines`.

## 2. Conventions
* **Errors**: `{"error": {"code", "message", "details"}, "request_id"}`. Codes include `UNAUTHORIZED`,
  `VALIDATION_ERROR`, `CONSENT_REQUIRED`, `AUDIO_TOO_SHORT`, `AUDIO_TOO_LONG`, `AUDIO_INVALID`,
  `AUDIO_QUALITY_INSUFFICIENT`, `UNSUPPORTED_MEDIA_TYPE`(415), `FILE_TOO_LARGE`(413), `UNSUPPORTED_LANGUAGE`,
  `VOICE_NOT_READY`(409), `JOB_NOT_READY`(409), `RATE_LIMITED`(429, `Retry-After`),
  `AI_ENGINE_NOT_CONFIGURED`(503), `AI_ENGINE_ERROR`, `MEDIA_PROCESSING_ERROR`, `NOT_FOUND`.
* **Jobs**: long operations return `202 {"job_id","type","status","status_url"}`. Poll `GET /jobs/{job_id}`
  every 1-2 s: `status` is `queued|processing|completed|failed`, `progress` 0-100, `stage` text, then `result` or `error`.
* **Lists**: `?limit=20&offset=0` -> `{"items","total","limit","offset"}`.
* **Files** are referenced by id and downloaded through `/files/{id}/download` (or the per-feature download URL).

## 3. Clone a voice (consent required)
```bash
curl -X POST $BASE/voices/clone -H "X-API-Key: $KEY" \
  -F file=@sample.m4a -F name="My voice" -F source=recorded -F language=en \
  -F consent_confirmed=true -F consent_type=self -F consent_holder_name="Jane Doe"
```
Sample: 6-300 s, clear speech (>= 5 s audible), not clipped/too quiet. Formats: wav, mp3, m4a, flac, ogg, opus, aac, webm, 3gp, amr.
Response `202`: `{"voice_id","job_id","status":"processing", "voice":{...}}`. Wait until `GET /voices/{id}` shows `"status":"ready"`.
`consent_type`: `self` or `authorized_third_party`. The profile object states `requires_reference_audio` honestly.

## 4. Text to speech
```bash
curl -X POST $BASE/speech/generate -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"voice_id":"voc_...","text":"Hello world","language":"en","speed":1.0,"output_format":"mp3"}'
# -> {"job_id": "job_..."}; poll GET /speech/{job_id}; then
curl -o out.mp3 -H "X-API-Key: $KEY" $BASE/speech/{job_id}/download
```
`output_format`: wav|mp3|flac|ogg|m4a. `speed` 0.5-2.0. XTTS-v2 languages: en es fr de it pt pl tr ru nl cs ar zh-cn hu ko ja hi.

## 5. Transcription
```bash
curl -X POST $BASE/transcription -H "X-API-Key: $KEY" -F file=@talk.mp4 -F language=auto
curl -H "X-API-Key: $KEY" "$BASE/transcription/{job_id}"                 # text, language, segments[start,end,text]
curl -H "X-API-Key: $KEY" "$BASE/transcription/{job_id}/export?format=srt"  # txt | srt | vtt
```
Accepts WAV, MP3, M4A, FLAC, MP4 (+ ogg, opus, aac, webm, mov, mkv). You may also pass `file_id` of an earlier `POST /files` upload.

## 6. Translation
`POST /translation/text` (JSON `text, source_language, target_language`, synchronous).
`POST /translation/audio` (multipart `file`, `target_language`, optional `source_language`) -> job; result has source and
translated segments; export with `/translation/{job_id}/export?format=srt&track=translated|source`.
Language pairs must be downloaded first (`scripts.download_models --translation en-es`); otherwise `AI_ENGINE_NOT_CONFIGURED`.

## 7. AI dubbing
```bash
curl -X POST $BASE/dubbing -H "X-API-Key: $KEY" \
  -F input_file=@clip.mp4 -F source_language=en -F target_language=es -F voice_id=voc_... \
  -F original_audio_volume=0
```
Pipeline: extract audio -> transcribe -> translate -> synthesize with your voice -> fit timing -> mux -> export.
Result includes `translated_segments`, a `sync` report, `warnings` and **`limitations`** (no lip-sync, single voice,
no background separation). Download: `/dubbing/{job_id}/download`; subtitles: `/dubbing/{job_id}/subtitles?format=srt`.

## 8. Projects & files
`POST/GET /projects`, `GET/PATCH/DELETE /projects/{id}`, `GET /projects/{id}/jobs`; pass `project_id` when creating jobs.
`POST /files` (upload for reuse), `GET /files`, `GET /files/{id}`, `GET /files/{id}/download`, `DELETE /files/{id}`.

## 9. Android (Kotlin / OkHttp) sketch
```kotlin
val client = OkHttpClient.Builder().addInterceptor { c ->
    c.proceed(c.request().newBuilder().header("X-API-Key", BuildConfig.VOXORA_KEY).build())
}.build()

fun cloneVoice(sample: File, name: String, holder: String): Response {
    val body = MultipartBody.Builder().setType(MultipartBody.FORM)
        .addFormDataPart("file", sample.name, sample.asRequestBody("audio/mp4".toMediaType()))
        .addFormDataPart("name", name).addFormDataPart("source", "recorded")
        .addFormDataPart("consent_confirmed", "true").addFormDataPart("consent_type", "self")
        .addFormDataPart("consent_holder_name", holder).build()
    return client.newCall(Request.Builder().url("$BASE/voices/clone").post(body).build()).execute()
}
```
Poll `GET /jobs/{id}` with a delay loop (coroutines) until `completed`/`failed`; stream downloads to a file.
Do not embed a long-lived key in a public app: put your own backend/session layer in front, or issue per-user keys.
