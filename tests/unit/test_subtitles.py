from app.utils import subtitles

SEGS = [
    {"start": 0.0, "end": 1.5, "text": "Hello   world."},
    {"start": 3661.5, "end": 3662.0, "text": "  Second\nline "},
    {"start": 5.0, "end": 6.0, "text": "   "},
]


def test_srt_format_and_skips_empty():
    out = subtitles.to_srt(SEGS)
    assert out.startswith("1\n00:00:00,000 --> 00:00:01,500\nHello world.\n")
    assert "2\n01:01:01,500 --> 01:01:02,000\nSecond line\n" in out
    assert "3\n" not in out


def test_vtt_format():
    out = subtitles.to_vtt(SEGS)
    assert out.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:01.500" in out


def test_txt_format():
    assert subtitles.to_txt(SEGS) == "Hello world.\nSecond line\n"


def test_rounding_never_produces_60_seconds():
    assert subtitles.format_timestamp(59.9996, sep=",") == "00:01:00,000"


def test_unknown_format_raises():
    import pytest

    with pytest.raises(ValueError):
        subtitles.export(SEGS, "pdf")
