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
