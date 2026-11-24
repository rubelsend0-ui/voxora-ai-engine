"""Chunked synthesis shared by the speech API and the dubbing pipeline."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from app.ai_engine.base import ProgressFn, SynthesisResult, TextToSpeechEngine, noop_progress
from app.core.errors import ValidationFailed
from app.utils.audio import read_wav_mono, write_wav_mono
from app.utils.text import split_text

_PAUSE_SECONDS = 0.18


def synthesize_text(
    tts: TextToSpeechEngine,
    *,
    text: str,
    language: str,
    reference_wav: Path,
    profile_path: Path | None,
    speed: float,
    out_wav: Path,
    workdir: Path,
    progress: ProgressFn = noop_progress,
    progress_range: tuple[float, float] = (0.0, 100.0),
    stage: str = "Generating speech",
    max_chunk_chars: int = 240,
) -> SynthesisResult:
    """Split ``text`` into sentences, synthesize each and join them into ``out_wav``."""
    chunks = split_text(text, max_chunk_chars)
    if not chunks:
        raise ValidationFailed("The text is empty.")
    lo, hi = progress_range
    parts: list[np.ndarray] = []
    sample_rate = 0
    for i, chunk in enumerate(chunks):
        part = workdir / f"chunk_{i:04d}.wav"
        res = tts.synthesize(
            text=chunk,
            language=language,
            reference_wav=reference_wav,
            profile_path=profile_path,
            speed=speed,
            out_wav=part,
        )
        samples, sr = read_wav_mono(part)
        sample_rate = res.sample_rate or sr
        parts.append(samples)
        if i < len(chunks) - 1:
            parts.append(np.zeros(int(sample_rate * _PAUSE_SECONDS), dtype=np.float32))
        part.unlink(missing_ok=True)
        progress(lo + (hi - lo) * (i + 1) / len(chunks), stage)
    audio = np.concatenate(parts)
    write_wav_mono(out_wav, audio, sample_rate)
    return SynthesisResult(sample_rate=sample_rate, duration_seconds=len(audio) / sample_rate)
