"""WAV helpers and a signal-level quality analysis for voice samples.

Everything inside the engine is normalised to 16-bit PCM mono WAV by FFmpeg, so
the standard library ``wave`` module plus NumPy is all that is needed here.
"""

from __future__ import annotations

import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


def read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    """Read a 16-bit PCM WAV file as float32 mono in [-1, 1]."""
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"Only 16-bit PCM WAV is supported (got {width * 8}-bit)")
    data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data[: len(data) - len(data) % channels].reshape(-1, channels).mean(axis=1)
    return data, rate


def write_wav_mono(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Write float samples in [-1, 1] as 16-bit PCM mono WAV."""
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def _db(x: np.ndarray | float) -> np.ndarray | float:
    return 20.0 * np.log10(np.maximum(x, 1e-9))


@dataclass
class AudioQualityReport:
    duration_seconds: float
    speech_seconds: float
    speech_ratio: float
    speech_level_dbfs: float
    peak_dbfs: float
    clipping_ratio: float
    noise_floor_dbfs: float | None
    snr_db: float | None
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, float):
                d[k] = round(v, 3)
        d["ok"] = self.ok
        return d


def analyze_voice_sample(
    path: Path,
    *,
    min_speech_seconds: float = 5.0,
    min_level_dbfs: float = -50.0,
    max_clipping_ratio: float = 0.01,
    min_speech_ratio: float = 0.2,
    frame_ms: int = 30,
) -> AudioQualityReport:
    """Signal-level checks (level, clipping, silence, rough SNR).

    This is a heuristic gate, not a speech detector: it cannot prove the audio
    contains a human voice, only that it is loud enough, not clipped, and not
    mostly silence.
    """
    x, sr = read_wav_mono(path)
    duration = len(x) / float(sr) if sr else 0.0
    if len(x) == 0:
        return AudioQualityReport(0.0, 0.0, 0.0, -120.0, -120.0, 0.0, None, None, issues=["The audio is empty."])

    frame = max(1, int(sr * frame_ms / 1000))
    n = len(x) // frame
    if n == 0:
        frames = x.reshape(1, -1)
    else:
        frames = x[: n * frame].reshape(n, frame)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    level = _db(rms)

    loud = float(np.percentile(level, 95))
    threshold = max(-60.0, loud - 25.0)
    speech_mask = level > threshold
    speech_ratio = float(np.mean(speech_mask))
    speech_seconds = float(np.sum(speech_mask)) * frame / sr

    if np.any(speech_mask):
        speech_level = float(_db(np.sqrt(np.mean(rms[speech_mask] ** 2))))
    else:
        speech_level = -120.0
    noise_floor = float(_db(np.sqrt(np.mean(rms[~speech_mask] ** 2)))) if np.any(~speech_mask) else None
    snr = speech_level - noise_floor if noise_floor is not None else None

    peak = float(np.max(np.abs(x)))
    clipping = float(np.mean(np.abs(x) >= 0.999))

    issues: list[str] = []
    warnings: list[str] = []
    if speech_seconds < min_speech_seconds:
        issues.append(
            f"Only {speech_seconds:.1f}s of audible content was found; at least "
            f"{min_speech_seconds:.0f}s of clear speech is required."
        )
    if speech_ratio < min_speech_ratio:
        issues.append("The recording is mostly silence.")
    if speech_level < min_level_dbfs:
        issues.append("The recording is too quiet. Record closer to the microphone.")
    if clipping > max_clipping_ratio:
        issues.append("The recording is clipped/distorted. Lower the input gain and record again.")
    if snr is not None and snr < 15.0:
        warnings.append("Background noise is high relative to the voice; cloning quality may suffer.")
    if speech_level > -6.0 and clipping <= max_clipping_ratio:
        warnings.append("The recording is very loud; it will be normalised.")

    return AudioQualityReport(
        duration_seconds=duration,
        speech_seconds=speech_seconds,
        speech_ratio=speech_ratio,
        speech_level_dbfs=speech_level,
        peak_dbfs=float(_db(peak)),
        clipping_ratio=clipping,
        noise_floor_dbfs=noise_floor,
        snr_db=snr,
        issues=issues,
        warnings=warnings,
    )
