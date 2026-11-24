"""Speech-to-text via faster-whisper (CTranslate2 build of OpenAI Whisper; MIT licensed)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.ai_engine.base import EngineStatus, SpeechToTextEngine, Transcript, TranscriptSegment
from app.ai_engine.device import has_module, resolve_device
from app.core.config import Settings
from app.core.errors import AIEngineError, AIEngineNotConfigured

log = logging.getLogger("voxora.whisper")


class FasterWhisperAdapter(SpeechToTextEngine):
    adapter_name = "faster_whisper"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._size = settings.whisper_model_size
        self._dir = settings.models_root / "whisper" / self._size
        self._lock = threading.RLock()
        self._model: Any = None

    def status(self) -> EngineStatus:
        if not has_module("faster_whisper"):
            return EngineStatus(
                available=False,
                adapter=self.adapter_name,
                model=f"whisper-{self._size}",
                reason="Python package 'faster-whisper' is not installed.",
                hint="pip install -r requirements-ai.txt",
            )
        if not (self._dir / "model.bin").is_file():
            return EngineStatus(
                available=False,
                adapter=self.adapter_name,
                model=f"whisper-{self._size}",
                reason=f"Whisper model '{self._size}' has not been downloaded.",
                hint=f"Run: python -m scripts.download_models --whisper {self._size}",
            )
        return EngineStatus(
            available=True,
            adapter=self.adapter_name,
            model=f"whisper-{self._size}",
            device=resolve_device(self._settings.device),
            details={"loaded": self._model is not None},
        )

    def _load(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            st = self.status()
            if not st.available:
                raise AIEngineNotConfigured("speech_to_text", st.reason or "unavailable", hint=st.hint)
            try:
                from faster_whisper import WhisperModel

                device = resolve_device(self._settings.device)
                compute = self._settings.whisper_compute_type
                if compute == "auto":
                    compute = "float16" if device == "cuda" else "int8"
                log.info("Loading Whisper '%s' on %s (%s)", self._size, device, compute)
                self._model = WhisperModel(str(self._dir), device=device, compute_type=compute)
            except Exception as exc:
                log.exception("Failed to load Whisper")
                raise AIEngineError("The Whisper model failed to load. See server logs.") from exc
            return self._model

    def transcribe(
        self, audio_wav: Path, language: str | None, progress: Callable[[float], None] | None = None
    ) -> Transcript:
        model = self._load()
        lang = None if language in (None, "auto") else ("zh" if language == "zh-cn" else language)
        try:
            with self._lock:
                seg_iter, info = model.transcribe(
                    str(audio_wav),
                    language=lang,
                    beam_size=5,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                duration = float(getattr(info, "duration", 0.0) or 0.0)
                segments: list[TranscriptSegment] = []
                for seg in seg_iter:  # generator: transcription happens lazily here
                    text = (seg.text or "").strip()
                    if text:
                        segments.append(TranscriptSegment(start=float(seg.start), end=float(seg.end), text=text))
                    if progress and duration > 0:
                        progress(min(1.0, float(seg.end) / duration))
        except AIEngineNotConfigured:
            raise
        except Exception as exc:
            log.exception("Transcription failed")
            raise AIEngineError("Transcription failed. See server logs.") from exc
        if progress:
            progress(1.0)
        return Transcript(
            language=str(info.language),
            language_probability=float(info.language_probability) if info.language_probability is not None else None,
            duration_seconds=duration,
            segments=segments,
        )
