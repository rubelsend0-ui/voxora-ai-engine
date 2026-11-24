"""Transcript exports: TXT, SRT and WebVTT."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

Segment = Mapping[str, Any]


def _ms(seconds: float) -> int:
    return max(0, int(round(float(seconds) * 1000)))


def format_timestamp(seconds: float, *, sep: str) -> str:
    total_ms = _ms(seconds)
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _clean(text: str) -> str:
    return " ".join(str(text).split())


def to_srt(segments: Iterable[Segment]) -> str:
    out: list[str] = []
    idx = 0
    for seg in segments:
        text = _clean(seg.get("text", ""))
        if not text:
            continue
        idx += 1
        out.append(
            f"{idx}\n{format_timestamp(seg['start'], sep=',')} --> {format_timestamp(seg['end'], sep=',')}\n{text}\n"
        )
    return "\n".join(out)


def to_vtt(segments: Iterable[Segment]) -> str:
    out: list[str] = ["WEBVTT\n"]
    for seg in segments:
        text = _clean(seg.get("text", ""))
        if not text:
            continue
        out.append(f"{format_timestamp(seg['start'], sep='.')} --> {format_timestamp(seg['end'], sep='.')}\n{text}\n")
    return "\n".join(out)


def to_txt(segments: Iterable[Segment]) -> str:
    lines = [_clean(seg.get("text", "")) for seg in segments]
    return "\n".join(line for line in lines if line) + "\n"


EXPORTERS = {"srt": to_srt, "vtt": to_vtt, "txt": to_txt}
EXPORT_MEDIA_TYPES = {
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}


def export(segments: Iterable[Segment], fmt: str) -> str:
    try:
        return EXPORTERS[fmt](segments)
    except KeyError as exc:
        raise ValueError(f"Unsupported export format: {fmt}") from exc
