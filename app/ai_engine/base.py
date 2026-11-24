"""Engine interfaces (ports).

API routes and services only ever talk to these abstract classes. Concrete
models live in ``app/ai_engine/adapters`` and are selected via configuration, so a
model can be swapped without touching any route or service code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import AIEngineNotConfigured

# (percent 0-100, human readable stage)
ProgressFn = Callable[[float, str], None]


def noop_progress(_pct: float, _stage: str) -> None:
    return None


@dataclass(frozen=True)
class EngineStatus:
    available: bool
    adapter: str
    reason: str | None = None
    hint: str | None = None
    device: str | None = None
    model: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, kind: str | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "available": self.available,
            "adapter": self.adapter,
            "device": self.device,
            "model": self.model,
            "reason": self.reason,
            "hint": self.hint,
            "details": self.details,
        }
        if kind:
            d["engine"] = kind
        return d


class BaseEngine(ABC):
    adapter_name: str = "unknown"

    @abstractmethod
    def status(self) -> EngineStatus:
        """Cheap availability check. Must NOT load model weights."""

    def ensure_available(self, kind: str | None = None) -> None:
        st = self.status()
        if not st.available:
            raise AIEngineNotConfigured(kind or self.adapter_name, st.reason or "unavailable", hint=st.hint)


# --------------------------------------------------------------------- audio
@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    has_audio: bool
    has_video: bool
    audio_codec: str | None = None
    video_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    format_name: str | None = None


@dataclass(frozen=True)
class TimelineItem:
    wav_path: Path
    start_seconds: float


class AudioProcessingEngine(BaseEngine):
    """Container/format conversion, normalisation, tempo change, timeline assembly, muxing."""

    @abstractmethod
    def probe(self, path: Path) -> MediaInfo: ...

    @abstractmethod
    def to_wav(self, src: Path, dst: Path, *, sample_rate: int = 16000, channels: int = 1) -> None:
        """Decode the first audio stream of any supported file to 16-bit PCM WAV."""

    @abstractmethod
    def prepare_voice_reference(self, src_wav: Path, dst_wav: Path, *, sample_rate: int, max_seconds: float) -> None:
        """Trim silence, normalise loudness, cap length."""

    @abstractmethod
    def encode(self, src_wav: Path, dst: Path, fmt: str) -> None:
        """Encode a WAV into ``wav|mp3|flac|ogg|m4a``."""

    @abstractmethod
    def change_tempo(self, src_wav: Path, dst_wav: Path, factor: float) -> None:
        """Pitch-preserving tempo change (factor > 1 is faster)."""

    @abstractmethod
    def assemble_timeline(
        self,
        items: Sequence[TimelineItem],
        dst_wav: Path,
        *,
        sample_rate: int,
        total_seconds: float,
        background_wav: Path | None = None,
        background_gain: float = 0.0,
    ) -> float:
        """Place clips on a silent timeline. Returns the final duration in seconds."""

    @abstractmethod
    def mux(self, video: Path, audio_wav: Path, dst: Path) -> None:
        """Replace the audio track of ``video`` with ``audio_wav``."""


# ---------------------------------------------------------------------- voice
@dataclass(frozen=True)
class VoiceProfileInfo:
    engine: str
    model: str
    profile_type: str
    requires_reference_audio: bool
    notes: str | None = None


class VoiceCloningEngine(BaseEngine):
    @abstractmethod
    def prepare_voice(self, reference_wav: Path, profile_path: Path) -> VoiceProfileInfo:
        """Compute the reusable voice profile for ``reference_wav`` and write it to ``profile_path``.

        The returned :class:`VoiceProfileInfo` states honestly whether the profile is
        sufficient on its own or whether the reference audio is still needed at synthesis time.
        """


# ------------------------------------------------------------------------ TTS
@dataclass(frozen=True)
class SynthesisResult:
    sample_rate: int
    duration_seconds: float


class TextToSpeechEngine(BaseEngine):
    @property
    @abstractmethod
    def supported_languages(self) -> frozenset[str]: ...

    @abstractmethod
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
        """Synthesise one short chunk of text (callers split long text) to a mono WAV."""


# ------------------------------------------------------------------------ STT
@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    language: str
    language_probability: float | None
    duration_seconds: float
    segments: list[TranscriptSegment]

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "language_probability": self.language_probability,
            "duration_seconds": round(self.duration_seconds, 3),
            "text": self.text,
            "segments": [
                {"id": i, "start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
                for i, s in enumerate(self.segments)
            ],
        }


class SpeechToTextEngine(BaseEngine):
    @abstractmethod
    def transcribe(
        self, audio_wav: Path, language: str | None, progress: Callable[[float], None] | None = None
    ) -> Transcript:
        """Transcribe a 16 kHz mono WAV. ``language=None`` means auto-detect."""


# ---------------------------------------------------------------- translation
class TranslationEngine(BaseEngine):
    @abstractmethod
    def supports_pair(self, source: str, target: str) -> bool: ...

    @abstractmethod
    def available_pairs(self) -> list[str]: ...

    @abstractmethod
    def translate(self, texts: Sequence[str], source: str, target: str) -> list[str]: ...


# -------------------------------------------------------------------- dubbing
@dataclass
class DubRequest:
    input_path: Path
    workdir: Path
    reference_wav: Path
    profile_path: Path | None
    source_language: str | None
    target_language: str
    output_format: str  # mp4 (video input) or an audio format
    original_audio_volume: float = 0.0
    max_speedup: float = 1.4
    max_seconds: float = 1800.0


@dataclass
class DubResult:
    output_path: Path
    detected_language: str
    duration_seconds: float
    source_segments: list[dict[str, Any]]
    translated_segments: list[dict[str, Any]]
    sync: dict[str, Any]
    warnings: list[str]
    limitations: list[str]


class DubbingEngine(BaseEngine):
    @abstractmethod
    def dub(self, request: DubRequest, progress: ProgressFn = noop_progress) -> DubResult: ...
