"""Generate real media files for tests (WAV via NumPy, video via FFmpeg)."""

from __future__ import annotations

import io
import subprocess
import wave
from pathlib import Path

import numpy as np


def speechlike_wav(seconds: float = 10.0, sr: int = 16000, amp: float = 0.3) -> bytes:
    rng = np.random.default_rng(1)
    t = np.arange(int(sr * seconds)) / sr
    env = 0.5 * (1 + np.sin(2 * np.pi * 3 * t))
    x = amp * env * np.sin(2 * np.pi * 180 * t) + 0.002 * rng.standard_normal(len(t))
    return _wav_bytes(x, sr)


def silent_wav(seconds: float = 10.0, sr: int = 16000) -> bytes:
    return _wav_bytes(np.zeros(int(sr * seconds)), sr)


def _wav_bytes(x: np.ndarray, sr: int) -> bytes:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def make_video(path: Path, seconds: float = 6.0) -> bytes:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=160x120:rate=10:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(path)],
        check=True,
    )
    return path.read_bytes()


def probe_streams(path: Path) -> dict:
    import json

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    kinds = {s["codec_type"] for s in data["streams"]}
    return {"video": "video" in kinds, "audio": "audio" in kinds, "duration": float(data["format"]["duration"])}
