"""XTTS-v2 adapter: voice cloning + text-to-speech.

Licensing: the XTTS-v2 *weights* are under the Coqui Public Model License (CPML),
which permits NON-COMMERCIAL use only. The ``coqui-tts`` library itself is MPL-2.0.
See docs/LICENSES.md. To use a different model, implement ``VoiceCloningEngine`` /
``TextToSpeechEngine`` in a new adapter and register it - no route changes needed.

What a "cloned voice" is here: XTTS-v2 does zero-shot cloning. ``prepare_voice``
pre-computes *conditioning latents* from the reference audio and caches them. This
is NOT a trained/fine-tuned model of the speaker, and it is NOT a standalone
embedding: the reference audio is kept and is still part of the profile.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.ai_engine.base import (
    EngineStatus,
    SynthesisResult,
    TextToSpeechEngine,
    VoiceCloningEngine,
    VoiceProfileInfo,
)
from app.ai_engine.device import has_module, resolve_device
from app.core.config import Settings
from app.core.errors import AIEngineError, AIEngineNotConfigured, UnsupportedLanguage
from app.utils.audio import write_wav_mono

log = logging.getLogger("voxora.xtts")

MODEL_ID = "coqui/XTTS-v2"
REQUIRED_FILES = ("config.json", "model.pth", "vocab.json")
LANGUAGES = frozenset(
    {"en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "hu", "ko", "ja", "hi"}
)
PROFILE_FORMAT = 1


class XTTSv2Adapter(VoiceCloningEngine, TextToSpeechEngine):
    adapter_name = "xtts_v2"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._dir = settings.models_root / "xtts_v2"
        self._lock = threading.RLock()  # model inference is not thread-safe
        self._model: Any = None
        self._device = "cpu"
        self._sample_rate = 24000
        self._latent_cache: dict[str, tuple[float, Any]] = {}

    @property
    def supported_languages(self) -> frozenset[str]:
        return LANGUAGES

    # -------------------------------------------------------------- status
    def status(self) -> EngineStatus:
        if not has_module("torch") or not has_module("TTS"):
            return EngineStatus(
                available=False,
                adapter=self.adapter_name,
                model=MODEL_ID,
                reason="Python packages 'torch' and 'coqui-tts' are not installed.",
                hint="pip install -r requirements-ai.txt (after installing torch for your CPU/CUDA).",
            )
        missing = [f for f in REQUIRED_FILES if not (self._dir / f).is_file()]
        if missing:
            return EngineStatus(
                available=False,
                adapter=self.adapter_name,
                model=MODEL_ID,
                reason=f"Model files are missing: {', '.join(missing)}.",
                hint="Run: python -m scripts.download_models --xtts --accept-coqui-cpml",
            )
        return EngineStatus(
            available=True,
            adapter=self.adapter_name,
            model=MODEL_ID,
            device=resolve_device(self._settings.device),
            details={"loaded": self._model is not None, "license": "CPML (non-commercial)"},
        )

    # ------------------------------------------------------------ internals
    def _require(self) -> None:
        st = self.status()
        if not st.available:
            raise AIEngineNotConfigured("xtts_v2", st.reason or "unavailable", hint=st.hint)

    def _load(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            self._require()
            try:
                from TTS.tts.configs.xtts_config import XttsConfig
                from TTS.tts.models.xtts import Xtts

                self._device = resolve_device(self._settings.device)
                log.info("Loading XTTS-v2 on %s", self._device)
                config = XttsConfig()
                config.load_json(str(self._dir / "config.json"))
                model = Xtts.init_from_config(config)
                model.load_checkpoint(config, checkpoint_dir=str(self._dir), eval=True, use_deepspeed=False)
                model.to(self._device)
                self._sample_rate = int(getattr(config.audio, "output_sample_rate", 24000))
                self._model = model
            except AIEngineNotConfigured:
                raise
            except Exception as exc:
                log.exception("Failed to load XTTS-v2")
                raise AIEngineError("The XTTS-v2 model failed to load. See server logs.") from exc
            return self._model

    def _latents(self, reference_wav: Path, profile_path: Path | None) -> tuple[Any, Any]:
        import torch

        model = self._load()
        if profile_path is not None and profile_path.is_file():
            mtime = profile_path.stat().st_mtime
            key = str(profile_path)
            cached = self._latent_cache.get(key)
            if cached and cached[0] == mtime:
                return cached[1]
            data = torch.load(str(profile_path), map_location=self._device)
            if data.get("format") == PROFILE_FORMAT:
                latents = (data["gpt_cond_latent"].to(self._device), data["speaker_embedding"].to(self._device))
                if len(self._latent_cache) > 32:
                    self._latent_cache.clear()
                self._latent_cache[key] = (mtime, latents)
                return latents
            log.warning("Voice profile format mismatch; recomputing from reference audio")
        gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(audio_path=[str(reference_wav)])
        return gpt_cond_latent, speaker_embedding

    # ---------------------------------------------------------- VoiceCloning
    def prepare_voice(self, reference_wav: Path, profile_path: Path) -> VoiceProfileInfo:
        import torch

        with self._lock:
            model = self._load()
            try:
                gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(audio_path=[str(reference_wav)])
                torch.save(
                    {
                        "format": PROFILE_FORMAT,
                        "gpt_cond_latent": gpt_cond_latent.detach().cpu(),
                        "speaker_embedding": speaker_embedding.detach().cpu(),
                    },
                    str(profile_path),
                )
            except Exception as exc:
                log.exception("XTTS conditioning failed")
                raise AIEngineError("Voice profile creation failed. See server logs.") from exc
        return VoiceProfileInfo(
            engine=self.adapter_name,
            model=MODEL_ID,
            profile_type="xtts_conditioning_latents",
            requires_reference_audio=True,
            notes=(
                "Zero-shot cloning: cached conditioning latents derived from the reference audio. "
                "The reference audio is retained and remains part of the profile; this is not a fine-tuned model."
            ),
        )

    # ------------------------------------------------------------------ TTS
    def synthesize(
        self,
        *,
        text: str,
        language: str,
        reference_wav: Path,
        profile_path: Path | None,
        speed: float,
        out_wav: Path,
    ) -> SynthesisResult:
        lang = "zh-cn" if language == "zh" else language
        if lang not in LANGUAGES:
            raise UnsupportedLanguage(
                f"XTTS-v2 does not support '{language}'.", details={"supported": sorted(LANGUAGES)}
            )
        with self._lock:
            self._load()
            gpt_cond_latent, speaker_embedding = self._latents(reference_wav, profile_path)
            try:
                out = self._model.inference(
                    text,
                    lang,
                    gpt_cond_latent,
                    speaker_embedding,
                    speed=float(speed),
                    enable_text_splitting=True,
                )
            except Exception as exc:
                log.exception("XTTS inference failed")
                raise AIEngineError("Speech synthesis failed. See server logs.") from exc
        wav = out["wav"]
        if hasattr(wav, "detach"):
            wav = wav.detach().cpu().numpy()
        samples = np.asarray(wav, dtype=np.float32).reshape(-1)
        write_wav_mono(out_wav, samples, self._sample_rate)
        return SynthesisResult(sample_rate=self._sample_rate, duration_seconds=len(samples) / self._sample_rate)
