"""TEST DOUBLES ONLY. These live in tests/ and are never imported by the application.

They let the API, database, storage, job runner and the *real* dubbing pipeline + FFmpeg be tested
without downloading multi-GB models. Real-model behaviour is covered by tests/integration (opt-in).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.ai_engine.base import (
    EngineStatus,
    SpeechToTextEngine,
    SynthesisResult,
    TextToSpeechEngine,
    Transcript,
    TranscriptSegment,
    TranslationEngine,
    VoiceCloningEngine,
    VoiceProfileInfo,
)
from app.core.errors import AIEngineError
from app.utils.audio import wav_duration, write_wav_mono

SR = 24000


class FakeCloner(VoiceCloningEngine):
    adapter_name = "fake_cloner"

    def status(self) -> EngineStatus:
        return EngineStatus(available=True, adapter=self.adapter_name, model="fake")

    def prepare_voice(self, reference_wav: Path, profile_path: Path) -> VoiceProfileInfo:
        assert reference_wav.is_file()
        profile_path.write_bytes(b"fake-profile")
        return VoiceProfileInfo(
            engine=self.adapter_name, model="fake", profile_type="test_profile", requires_reference_audio=True
        )


class FakeTTS(TextToSpeechEngine):
    adapter_name = "fake_tts"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    @property
    def supported_languages(self) -> frozenset[str]:
        return frozenset({"en", "es", "fr"})

    def status(self) -> EngineStatus:
        return EngineStatus(available=True, adapter=self.adapter_name, model="fake")

    def synthesize(
        self, *, text: str, language: str, reference_wav: Path, profile_path: Path | None, speed: float, out_wav: Path
    ) -> SynthesisResult:
        assert reference_wav.is_file(), "TTS must receive the stored reference audio"
        self.calls.append({"text": text, "language": language, "speed": speed, "profile": profile_path is not None})
        seconds = max(0.4, 0.06 * len(text)) / speed
        t = np.arange(int(SR * seconds)) / SR
        write_wav_mono(out_wav, (0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32), SR)
        return SynthesisResult(sample_rate=SR, duration_seconds=seconds)


class ExplodingTTS(FakeTTS):
    def synthesize(self, **kwargs) -> SynthesisResult:  # type: ignore[override]
        raise AIEngineError("boom")


class FakeSTT(SpeechToTextEngine):
    adapter_name = "fake_stt"

    def status(self) -> EngineStatus:
        return EngineStatus(available=True, adapter=self.adapter_name, model="fake")

    def transcribe(
        self, audio_wav: Path, language: str | None, progress: Callable[[float], None] | None = None
    ) -> Transcript:
        dur = wav_duration(audio_wav)
        if progress:
            progress(1.0)
        segs = [
            TranscriptSegment(0.5, dur / 2, "Hello world."),
            TranscriptSegment(dur / 2 + 0.5, dur - 0.5, "This is a second sentence."),
        ]
        return Transcript(language=language or "en", language_probability=0.99, duration_seconds=dur, segments=segs)


class FakeTranslator(TranslationEngine):
    adapter_name = "fake_translator"

    def status(self) -> EngineStatus:
        return EngineStatus(available=True, adapter=self.adapter_name, details={"pairs": ["en-es"]})

    def supports_pair(self, source: str, target: str) -> bool:
        return source != "xx" and target != "xx"

    def available_pairs(self) -> list[str]:
        return ["en-es", "en-fr"]

    def translate(self, texts: Sequence[str], source: str, target: str) -> list[str]:
        return [f"[{target}] {t}" for t in texts]


@dataclass
class Installed:
    cloner: FakeCloner = field(default_factory=FakeCloner)
    tts: FakeTTS = field(default_factory=FakeTTS)
    stt: FakeSTT = field(default_factory=FakeSTT)
    translator: FakeTranslator = field(default_factory=FakeTranslator)


def install_fakes(registry) -> Installed:
    inst = Installed()
    registry.override("voice_cloning", inst.cloner)
    registry.override("text_to_speech", inst.tts)
    registry.override("speech_to_text", inst.stt)
    registry.override("translation", inst.translator)
    return inst
