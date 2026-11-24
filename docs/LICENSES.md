# Model & dependency licenses

**Not legal advice.** Re-check each license before shipping.

| Component | Used for | License | Checked |
|---|---|---|---|
| **XTTS-v2 weights** (`coqui/XTTS-v2`) | voice cloning + TTS | **Coqui Public Model License 1.0.0 (CPML) - non-commercial use only** | **Yes - confirmed against the Hugging Face model repository LICENSE during development** |
| `coqui-tts` (idiap fork) | runs XTTS | MPL-2.0 (library code) | from package metadata knowledge - verify |
| Whisper weights / `faster-whisper` / CTranslate2 | speech to text | MIT | from knowledge - verify on the model card |
| Helsinki-NLP OPUS-MT models | translation | CC-BY-4.0 on most pairs (attribution required) | from knowledge - **verify per pair on its model card** |
| `transformers`, `sentencepiece` | translation runtime | Apache-2.0 | from knowledge |
| FFmpeg | media | LGPL/GPL depending on your build (called as a separate process) | verify your build |
| FastAPI, SQLAlchemy, Celery, Redis client, etc. | API | MIT / BSD style | - |

## What this means for you

* **Commercial use of the cloning/TTS output is not permitted with XTTS-v2 weights.** Coqui (the company) shut
  down in 2023, so no commercial license can be obtained from it. For a commercial product, swap the adapter for a
  permissively licensed model - implement `VoiceCloningEngine` + `TextToSpeechEngine` (see `app/ai_engine/base.py`),
  register it in `app/ai_engine/registry.py`, and set `VOXORA_TTS_ADAPTER` / `VOXORA_VOICE_CLONING_ADAPTER`. No route changes.
* `scripts/download_models.py` refuses to fetch XTTS-v2 unless you pass `--accept-coqui-cpml`.
* Weights are downloaded at install time into `VOXORA_MODELS_DIR` and are git-ignored; never commit them.
