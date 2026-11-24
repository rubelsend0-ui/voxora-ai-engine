"""Text helpers for TTS."""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?。！？…])\s+")
_CLAUSE_END = re.compile(r"(?<=[,;:，；：])\s+")


def split_text(text: str, max_chars: int = 240) -> list[str]:
    """Split text into chunks of at most ``max_chars`` characters.

    Prefers sentence boundaries, then clause boundaries, then word boundaries.
    XTTS-v2 degrades on long inputs, so synthesis is done chunk by chunk.
    """
    text = " ".join(text.split())
    if not text:
        return []
    chunks: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        chunks.extend(_split_long(sentence, max_chars))
    # Merge tiny neighbours so we do not synthesise one-word clips.
    merged: list[str] = []
    for c in chunks:
        if merged and len(merged[-1]) + 1 + len(c) <= max_chars and (len(merged[-1]) < 40 or len(c) < 15):
            merged[-1] = f"{merged[-1]} {c}"
        else:
            merged.append(c)
    return merged


def _split_long(s: str, max_chars: int) -> list[str]:
    if len(s) <= max_chars:
        return [s]
    out: list[str] = []
    for clause in _CLAUSE_END.split(s):
        if len(clause) <= max_chars:
            out.append(clause)
            continue
        cur = ""
        for word in clause.split(" "):
            while len(word) > max_chars:  # unbroken run (e.g. CJK): hard split
                if cur:
                    out.append(cur)
                    cur = ""
                out.append(word[:max_chars])
                word = word[max_chars:]
            if cur and len(cur) + 1 + len(word) > max_chars:
                out.append(cur)
                cur = word
            else:
                cur = f"{cur} {word}".strip()
        if cur:
            out.append(cur)
    return out
