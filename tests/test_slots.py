from datetime import datetime, time

from app import slots
from app.slots import WindowLoad


def test_pilot_windows() -> None:
    specs = slots.build_windows([["08:00", "12:00"], ["16:00", "20:00"]], 30, 0.5)
    assert len(specs) == 24
    assert specs[0].start == time(8, 0) and specs[0].end == time(8, 20)
    assert specs[-1].start == time(19, 40)
    assert all(s.booked_capacity == 5 and s.walkin_capacity == 5 for s in specs)


def test_capacity_odd_place_goes_to_walkins() -> None:
    assert slots.split_capacity(33, 0.5) == (5, 6)
    assert slots.split_capacity(30, 0.3) == (3, 7)


def test_wait_estimate() -> None:
    assert slots.wait_minutes(18, 30) == 36
    assert slots.wait_minutes(0, 30) == 0
    assert slots.wait_minutes(3, 20) == 9


def test_late_rule() -> None:
    start = datetime(2026, 11, 28, 4, 50)
    assert not slots.is_late(datetime(2026, 11, 28, 5, 0), start)  # exactly 10 minutes
    assert slots.is_late(datetime(2026, 11, 28, 5, 1), start)  # 11 minutes


def test_no_show() -> None:
    end = datetime(2026, 11, 28, 5, 10)
    assert slots.is_no_show("booked", end, end)
    assert not slots.is_no_show("arrived", end, end)
    assert not slots.is_no_show("booked", end, datetime(2026, 11, 28, 5, 9))


def _loads() -> list[WindowLoad]:
    out = []
    for i, spec in enumerate(
        slots.build_windows([["08:00", "12:00"], ["16:00", "20:00"]], 30, 0.5)
    ):
        booked = 5 if spec.start <= time(10, 0) else (2 if spec.start == time(16, 0) else 0)
        out.append(WindowLoad(i + 1, spec.start, booked, 5))
    return out


def test_free_windows_by_session() -> None:
    loads = _loads()
    assert slots.free_windows(loads, "morning")[0].start == time(10, 20)
    assert slots.free_windows(loads, "evening")[0].start == time(16, 0)
    assert slots.free_windows(loads, None, not_before=time(11, 0))[0].start == time(11, 20)
    first = slots.free_windows(loads, "morning")[0]
    assert slots.free_windows(loads, "morning", exclude={first.id})[0].start == time(10, 40)


def test_quietest_window_ties_go_earliest() -> None:
    assert slots.quietest_window(_loads()).start == time(10, 20)  # type: ignore[union-attr]
    full = [WindowLoad(1, time(8, 0), 5, 5)]
    assert slots.quietest_window(full) is None


def test_booking_block_reason() -> None:
    assert slots.booking_block_reason(True, True) == "paused"
    assert slots.booking_block_reason(False, True) == "month"
    assert slots.booking_block_reason(False, False) is None


def test_serving_alternates() -> None:
    assert slots.interleave([1, 2, 3], [10, 11], None) == [1, 10, 2, 11, 3]
    assert slots.interleave([1, 2], [10, 11], "booked") == [10, 1, 11, 2]
    assert slots.interleave([], [10, 11], "walkin") == [10, 11]
    assert slots.next_kind(None, 0, 0) is None


def test_ahead_for_booking() -> None:
    assert slots.ahead_for_booking(1, 18) == 3
    assert slots.ahead_for_booking(0, 0) == 0
