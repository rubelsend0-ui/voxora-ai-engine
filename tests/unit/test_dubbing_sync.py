import pytest

from app.ai_engine.dubbing_sync import plan_sync


def test_clip_that_fits_is_untouched():
    items, summary = plan_sync([(0, 3), (4, 7)], [2.5, 2.0])
    assert [i.tempo for i in items] == [1.0, 1.0]
    assert [i.placed_start for i in items] == [0, 4]
    assert summary["sped_up"] == 0 and summary["overflowing_segments"] == 0


def test_long_clip_uses_gap_before_next_segment_without_speedup():
    # own slot 2s, but 3.5s are available before the next segment starts at 5.0
    items, _ = plan_sync([(0, 2), (5, 7)], [3.5, 1.0])
    assert items[0].tempo == 1.0


def test_long_clip_is_sped_up_but_capped():
    items, summary = plan_sync([(0, 2), (3, 5)], [6.0, 1.0], max_speedup=1.4)
    assert items[0].tempo == pytest.approx(1.4)
    assert items[0].overflow is True
    assert summary["overflowing_segments"] == 1
    # the next clip is pushed later rather than overlapping
    assert items[1].placed_start >= items[0].placed_start + items[0].final_seconds


def test_moderate_overrun_is_fixed_by_speedup_only():
    items, _ = plan_sync([(0, 2), (2.5, 4)], [2.8, 1.0], max_speedup=1.5)
    assert 1.0 < items[0].tempo <= 1.5
    assert items[0].overflow is False
    assert items[1].placed_start == 2.5


def test_never_overlaps():
    slots = [(i * 1.0, i * 1.0 + 0.8) for i in range(20)]
    items, _ = plan_sync(slots, [2.0] * 20)
    for a, b in zip(items, items[1:], strict=False):
        assert b.placed_start >= a.placed_start + a.final_seconds - 1e-9


def test_never_slows_down():
    items, _ = plan_sync([(0, 10)], [1.0])
    assert items[0].tempo == 1.0


def test_length_mismatch():
    with pytest.raises(ValueError):
        plan_sync([(0, 1)], [1.0, 2.0])
