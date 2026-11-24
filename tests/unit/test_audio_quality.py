import numpy as np

from app.utils.audio import analyze_voice_sample, read_wav_mono, wav_duration, write_wav_mono

SR = 16000


def _speechlike(seconds, amp=0.3, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    env = 0.5 * (1 + np.sin(2 * np.pi * 3 * t))  # syllable-rate envelope
    return (amp * env * np.sin(2 * np.pi * 180 * t) + 0.002 * rng.standard_normal(len(t))).astype(np.float32)


def test_roundtrip(tmp_path):
    x = _speechlike(1.0)
    write_wav_mono(tmp_path / "a.wav", x, SR)
    y, sr = read_wav_mono(tmp_path / "a.wav")
    assert sr == SR and len(y) == len(x)
    assert abs(wav_duration(tmp_path / "a.wav") - 1.0) < 1e-3
    assert np.max(np.abs(x - y)) < 1e-3


def test_good_sample_passes(tmp_path):
    write_wav_mono(tmp_path / "ok.wav", _speechlike(10), SR)
    rep = analyze_voice_sample(tmp_path / "ok.wav")
    assert rep.ok, rep.issues
    assert rep.duration_seconds > 9.9


def test_silence_rejected(tmp_path):
    write_wav_mono(tmp_path / "s.wav", np.zeros(SR * 10, dtype=np.float32), SR)
    rep = analyze_voice_sample(tmp_path / "s.wav")
    assert not rep.ok


def test_too_short_speech_rejected(tmp_path):
    x = np.concatenate([_speechlike(2), np.zeros(SR * 8, dtype=np.float32)])
    write_wav_mono(tmp_path / "short.wav", x, SR)
    rep = analyze_voice_sample(tmp_path / "short.wav", min_speech_seconds=5)
    assert not rep.ok
    assert any("clear speech" in i or "silence" in i for i in rep.issues)


def test_too_quiet_rejected(tmp_path):
    write_wav_mono(tmp_path / "q.wav", _speechlike(10, amp=0.0008), SR)
    rep = analyze_voice_sample(tmp_path / "q.wav")
    assert any("quiet" in i for i in rep.issues)


def test_clipping_rejected(tmp_path):
    x = np.clip(_speechlike(10, amp=5.0), -1, 1)
    write_wav_mono(tmp_path / "c.wav", x, SR)
    rep = analyze_voice_sample(tmp_path / "c.wav")
    assert any("clipped" in i for i in rep.issues)


def test_empty_file(tmp_path):
    write_wav_mono(tmp_path / "e.wav", np.zeros(0, dtype=np.float32), SR)
    assert not analyze_voice_sample(tmp_path / "e.wav").ok
