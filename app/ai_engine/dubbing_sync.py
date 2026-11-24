"""Timing planner used by the dubbing pipeline.

Translated speech is rarely the same length as the original. For each segment this
decides whether to speed the generated clip up (never slow it down) and where to
place it so clips never overlap. It reports what it had to do instead of hiding it:
this is *timing fitting*, not lip synchronisation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class SyncItem:
    index: int
    original_start: float
    original_end: float
    generated_seconds: float
    tempo: float
    placed_start: float
    final_seconds: float
    shifted_seconds: float
    overflow: bool


def plan_sync(
    slots: list[tuple[float, float]],
    generated: list[float],
    *,
    max_speedup: float = 1.4,
    min_gap: float = 0.05,
    shift_tolerance: float = 0.25,
) -> tuple[list[SyncItem], dict[str, Any]]:
    """Return per-segment placement and a summary.

    ``slots``     original (start, end) of each segment, in order.
    ``generated`` natural duration of each synthesized clip, in seconds.
    """
    if len(slots) != len(generated):
        raise ValueError("slots and generated must have the same length")
    items: list[SyncItem] = []
    cursor = 0.0
    for i, ((start, end), gen) in enumerate(zip(slots, generated, strict=True)):
        placed = max(start, cursor)
        has_next = i + 1 < len(slots)
        budget_end = (slots[i + 1][0] - min_gap) if has_next else max(end, placed + gen)
        own_end = max(end, placed)  # the original speech span
        tempo = 1.0
        if gen > (own_end - placed) and gen > (budget_end - placed):
            budget = max(budget_end - placed, 0.0)
            needed = gen / budget if budget > 0.05 else max_speedup
            tempo = min(max(needed, 1.0), max_speedup)
        final = gen / tempo
        shifted = placed - start
        overflow = (placed + final) > (budget_end + 1e-6) and has_next
        items.append(
            SyncItem(
                index=i,
                original_start=start,
                original_end=end,
                generated_seconds=gen,
                tempo=round(tempo, 4),
                placed_start=placed,
                final_seconds=final,
                shifted_seconds=max(shifted, 0.0),
                overflow=overflow,
            )
        )
        cursor = placed + final + min_gap
    summary = {
        "segments": len(items),
        "sped_up": sum(1 for it in items if it.tempo > 1.0),
        "max_tempo": max((it.tempo for it in items), default=1.0),
        "delayed_segments": sum(1 for it in items if it.shifted_seconds > shift_tolerance),
        "max_delay_seconds": round(max((it.shifted_seconds for it in items), default=0.0), 3),
        "overflowing_segments": sum(1 for it in items if it.overflow),
    }
    return items, summary


def item_dicts(items: list[SyncItem]) -> list[dict[str, Any]]:
    return [asdict(i) for i in items]
