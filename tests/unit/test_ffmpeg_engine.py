import shutil
import subprocess

import numpy as np
import pytest

from app.ai_engine.adapters.ffmpeg_audio import FFmpegAudioEngine
from app.ai_engine.base import TimelineItem
from app.core.config import Settings
from app.core.errors import MediaProcessingError
from app.utils.audio import read_wav_mono, write_wav_mono

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
SR = 24000


@pytest.fixture()
def engine():
    return FFmpegAudioEngine(Settings())


@pytest.fixture()
def tone(tmp_path):
    t = np.arange(SR * 3) / SR
    p = tmp_path / "tone.wav"
    write_wav_mono(p, (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), SR)
    return p


def test_status_available(engine):
    assert engine.status().available


def test_probe(engine, tone):
    info = engine.probe(tone)
    assert info.has_audio and not info.has_video
    assert info.duration_seconds == pytest.approx(3.0, abs=0.05)
    assert info.sample_rate == SR


def test_probe_rejects_garbage(engine, tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"this is not audio" * 20)
    with pytest.raises(MediaProcessingError):
        engine.probe(bad)


@pytest.mark.parametrize("fmt", ["wav", "mp3", "flac", "ogg", "m4a"])
def test_encode_formats(engine, tone, tmp_path, fmt):
    out = tmp_path / f"out.{fmt}"
    engine.encode(tone, out, fmt)
    assert engine.probe(out).duration_seconds == pytest.approx(3.0, abs=0.15)


def test_to_wav_resamples(engine, tone, tmp_path):
    out = tmp_path / "o.wav"
    engine.to_wav(tone, out, sample_rate=16000)
    assert read_wav_mono(out)[1] == 16000


def test_tempo(engine, tone, tmp_path):
    out = tmp_path / "fast.wav"
    engine.change_tempo(tone, out, 1.5)
    x, sr = read_wav_mono(out)
    assert len(x) / sr == pytest.approx(2.0, abs=0.05)


def test_timeline_places_clips(engine, tone, tmp_path):
    out = tmp_path / "tl.wav"
    total = engine.assemble_timeline(
        [TimelineItem(tone, 1.0), TimelineItem(tone, 6.0)], out, sample_rate=SR, total_seconds=10.0
    )
    x, sr = read_wav_mono(out)
    assert total == pytest.approx(10.0, abs=0.01)
    assert np.max(np.abs(x[: int(0.9 * sr)])) == 0  # silence before first clip
    assert np.max(np.abs(x[int(1.2 * sr) : int(2.0 * sr)])) > 0.1
    assert np.max(np.abs(x[int(4.5 * sr) : int(5.5 * sr)])) == 0  # gap between clips


def test_timeline_extends_for_overflow(engine, tone, tmp_path):
    out = tmp_path / "tl.wav"
    total = engine.assemble_timeline([TimelineItem(tone, 4.0)], out, sample_rate=SR, total_seconds=5.0)
    assert total == pytest.approx(7.0, abs=0.01)


def test_voice_reference_is_trimmed(engine, tmp_path):
    t = np.arange(SR * 3) / SR
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    raw = np.concatenate([np.zeros(SR, np.float32), tone, np.zeros(SR, np.float32)])
    src, dst = tmp_path / "raw.wav", tmp_path / "ref.wav"
    write_wav_mono(src, raw, SR)
    engine.prepare_voice_reference(src, dst, sample_rate=SR, max_seconds=30)
    assert len(read_wav_mono(dst)[0]) / SR < 4.0


def test_voice_reference_is_capped(engine, tone, tmp_path):
    dst = tmp_path / "ref.wav"
    engine.prepare_voice_reference(tone, dst, sample_rate=SR, max_seconds=1.0)
    assert len(read_wav_mono(dst)[0]) / SR <= 1.05


def test_mux_replaces_audio(engine, tone, tmp_path):
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(video)],
        check=True,
    )
    info = engine.probe(video)
    assert info.has_video and info.has_audio
    out = tmp_path / "out.mp4"
    engine.mux(video, tone, out)
    res = engine.probe(out)
    assert res.has_video and res.has_audio and res.sample_rate == SR
