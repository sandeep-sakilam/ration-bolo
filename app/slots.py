"""Slot and queue rules. Pure functions only: no database, no clock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

WINDOW_MINUTES = 20


@dataclass(frozen=True)
class WindowSpec:
    start: time
    end: time
    booked_capacity: int
    walkin_capacity: int


def parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def window_capacity(families_per_hour: int) -> int:
    """Families one 20-minute window holds (pilot: 30 an hour → 10)."""
    return max(1, families_per_hour * WINDOW_MINUTES // 60)


def split_capacity(families_per_hour: int, booked_share: float) -> tuple[int, int]:
    """(booked places, walk-in places) per window. Walk-ins get any odd place."""
    total = window_capacity(families_per_hour)
    booked = int(total * booked_share)
    return booked, total - booked


def build_windows(
    sessions: list[list[str]], families_per_hour: int, booked_share: float
) -> list[WindowSpec]:
    """Split each shop session ("08:00"-"12:00") into 20-minute windows."""
    booked, walkin = split_capacity(families_per_hour, booked_share)
    specs: list[WindowSpec] = []
    anchor = datetime(2000, 1, 1)
    for start_s, end_s in sessions:
        cursor = datetime.combine(anchor, parse_hhmm(start_s))
        end = datetime.combine(anchor, parse_hhmm(end_s))
        step = timedelta(minutes=WINDOW_MINUTES)
        while cursor + step <= end:
            specs.append(WindowSpec(cursor.time(), (cursor + step).time(), booked, walkin))
            cursor += step
    return specs


# --- Rules ---------------------------------------------------------------

LATE_GRACE_MINUTES = 10

# Session words map to fixed parts of the day (IST).
SESSION_RANGES: dict[str, tuple[time, time]] = {
    "morning": (time(8, 0), time(12, 0)),
    "evening": (time(16, 0), time(20, 0)),
}


@dataclass(frozen=True)
class WindowLoad:
    """A window and how many of its booking places are taken."""

    id: int
    start: time
    booked: int
    booked_capacity: int

    @property
    def free(self) -> int:
        return max(0, self.booked_capacity - self.booked)


def minutes_per_family(families_per_hour: int) -> float:
    return 60 / families_per_hour


def wait_minutes(ahead: int, families_per_hour: int) -> int:
    """People ahead × (60 / families_per_hour) minutes (pilot: 2 minutes each)."""
    return round(ahead * minutes_per_family(families_per_hour))


def is_late(arrived_at: datetime, window_start: datetime) -> bool:
    """A booked family more than 10 minutes after its window starts loses the booking."""
    return arrived_at > window_start + timedelta(minutes=LATE_GRACE_MINUTES)


def is_no_show(status: str, window_end: datetime, now: datetime) -> bool:
    """A booking not marked arrived by the end of its window becomes a no-show."""
    return status == "booked" and now >= window_end


def in_session(start: time, session: str | None) -> bool:
    if session is None:
        return True
    lo, hi = SESSION_RANGES[session]
    return lo <= start < hi


def free_windows(
    windows: list[WindowLoad],
    session: str | None = None,
    not_before: time | None = None,
    exclude: set[int] | frozenset[int] = frozenset(),
) -> list[WindowLoad]:
    """Windows with a free booking place, earliest first.

    ``not_before`` skips windows that have already started (bookings for today).
    """
    return sorted(
        (
            w
            for w in windows
            if w.free > 0
            and in_session(w.start, session)
            and (not_before is None or w.start > not_before)
            and w.id not in exclude
        ),
        key=lambda w: w.start,
    )


def quietest_window(windows: list[WindowLoad]) -> WindowLoad | None:
    """The open window with the fewest bookings; ties go to the earliest."""
    open_windows = [w for w in windows if w.free > 0]
    if not open_windows:
        return None
    return min(open_windows, key=lambda w: (w.booked, w.start))


def booking_block_reason(paused: bool, has_booking_this_month: bool) -> str | None:
    """Why a new booking must be refused, or None."""
    if paused:
        return "paused"
    if has_booking_this_month:
        return "month"
    return None


def next_kind(last_kind: str | None, booked_waiting: int, walkin_waiting: int) -> str | None:
    """Serving order alternates booked and walk-in; if one line is empty, serve the other."""
    if booked_waiting == 0 and walkin_waiting == 0:
        return None
    if booked_waiting == 0:
        return "walkin"
    if walkin_waiting == 0:
        return "booked"
    return "walkin" if last_kind == "booked" else "booked"


def interleave(booked: list[int], walkins: list[int], last_kind: str | None) -> list[int]:
    """Full serving order (ids) given both lines and the kind served last."""
    order: list[int] = []
    b, w = list(booked), list(walkins)
    kind = last_kind
    while b or w:
        kind = next_kind(kind, len(b), len(w))
        order.append(b.pop(0) if kind == "booked" else w.pop(0))
    return order


def ahead_for_booking(booked_ahead: int, walkins_waiting: int) -> int:
    """People ahead of a booked family at its window: booked families before it plus,
    because the lines alternate, up to one walk-in for each of them and one more."""
    return booked_ahead + min(walkins_waiting, booked_ahead + 1)
