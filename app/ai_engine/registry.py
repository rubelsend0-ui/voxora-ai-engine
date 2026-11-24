"""Engine registry: resolves configured adapter names to engine instances.

Adapters are imported lazily so the API starts (and reports AI_ENGINE_NOT_CONFIGURED)
even when torch / model packages are not installed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from functools import lru_cache

from app.ai_engine.base import BaseEngine, EngineStatus
from app.core.config import Settings, get_settings
from app.core.errors import AIEngineNotConfigured

KINDS = ("audio_processing", "speech_to_text", "translation", "voice_cloning", "text_to_speech", "dubbing")

_SETTING_FOR_KIND = {
    "audio_processing": "audio_adapter",
    "speech_to_text": "stt_adapter",
    "translation": "translation_adapter",
    "voice_cloning": "voice_cloning_adapter",
    "text_to_speech": "tts_adapter",
    "dubbing": "dubbing_adapter",
}

Factory = Callable[["EngineRegistry"], BaseEngine]


def _xtts(reg: EngineRegistry) -> BaseEngine:
    from app.ai_engine.adapters.xtts_v2 import XTTSv2Adapter

    return XTTSv2Adapter(reg.settings)


def _whisper(reg: EngineRegistry) -> BaseEngine:
    from app.ai_engine.adapters.faster_whisper_stt import FasterWhisperAdapter

    return FasterWhisperAdapter(reg.settings)


def _marian(reg: EngineRegistry) -> BaseEngine:
    from app.ai_engine.adapters.marian_translation import MarianTranslationAdapter

    return MarianTranslationAdapter(reg.settings)


def _ffmpeg(reg: EngineRegistry) -> BaseEngine:
    from app.ai_engine.adapters.ffmpeg_audio import FFmpegAudioEngine

    return FFmpegAudioEngine(reg.settings)


def _pipeline(reg: EngineRegistry) -> BaseEngine:
    from app.ai_engine.adapters.pipeline_dubbing import PipelineDubbingEngine

    return PipelineDubbingEngine(reg.get)


class EngineRegistry:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        # adapter name -> instance. Adapter names are globally unique, which lets one
        # object (XTTS-v2) serve both the voice_cloning and text_to_speech interfaces.
        self._instances: dict[str, BaseEngine] = {}
        self._overrides: dict[str, BaseEngine] = {}
        self._factories: dict[str, dict[str, Factory]] = {
            "audio_processing": {"ffmpeg": _ffmpeg},
            "speech_to_text": {"faster_whisper": _whisper},
            "translation": {"marian": _marian},
            "voice_cloning": {"xtts_v2": _xtts},
            "text_to_speech": {"xtts_v2": _xtts},
            "dubbing": {"pipeline": _pipeline},
        }

    # --------------------------------------------------------------- config
    def register_adapter(self, kind: str, name: str, factory: Factory) -> None:
        """Plug in a custom adapter, then select it with the matching VOXORA_*_ADAPTER setting."""
        self._factories.setdefault(kind, {})[name] = factory

    def override(self, kind: str, engine: BaseEngine) -> None:
        """Force an engine instance for ``kind`` (used by tests and embedding applications)."""
        self._overrides[kind] = engine

    def clear_overrides(self) -> None:
        self._overrides.clear()

    # ----------------------------------------------------------------- lookup
    def get(self, kind: str) -> BaseEngine:
        if kind in self._overrides:
            return self._overrides[kind]
        if kind not in _SETTING_FOR_KIND:
            raise KeyError(kind)
        name = getattr(self.settings, _SETTING_FOR_KIND[kind])
        factory = self._factories.get(kind, {}).get(name)
        if factory is None:
            raise AIEngineNotConfigured(
                kind,
                f"Unknown adapter '{name}'.",
                hint=f"Available adapters: {', '.join(sorted(self._factories.get(kind, {}))) or 'none'}",
            )
        with self._lock:
            if name not in self._instances:
                self._instances[name] = factory(self)
            return self._instances[name]

    def require(self, kind: str) -> BaseEngine:
        engine = self.get(kind)
        engine.ensure_available(kind)
        return engine

    def statuses(self) -> dict[str, EngineStatus]:
        out: dict[str, EngineStatus] = {}
        for kind in KINDS:
            try:
                out[kind] = self.get(kind).status()
            except AIEngineNotConfigured as exc:
                out[kind] = EngineStatus(available=False, adapter="unknown", reason=exc.details.get("reason"))
        return out


@lru_cache
def get_registry() -> EngineRegistry:
    return EngineRegistry(get_settings())
