"""Time helpers. Times are stored as naive UTC and shown in IST (no DST in India)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")

_frozen: datetime | None = None


def freeze(at: datetime | None) -> None:
    """Freeze the clock (tests and demos). ``at`` is naive UTC or aware."""
    global _frozen
    if at is not None and at.tzinfo is not None:
        at = at.astimezone(UTC).replace(tzinfo=None)
    _frozen = at


def now_utc() -> datetime:
    if _frozen is not None:
        return _frozen
    env = os.environ.get("RATION_BOLO_NOW")
    if env:
        parsed = datetime.fromisoformat(env)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed
    return datetime.now(UTC).replace(tzinfo=None)


def to_ist(dt: datetime) -> datetime:
    """Naive UTC → aware IST."""
    return dt.replace(tzinfo=UTC).astimezone(IST)


def ist_today(now: datetime | None = None) -> date:
    return to_ist(now or now_utc()).date()


def ist_to_utc(day: date, at: time) -> datetime:
    """IST wall-clock date and time → naive UTC."""
    return datetime.combine(day, at, tzinfo=IST).astimezone(UTC).replace(tzinfo=None)


def fmt_time(at: time) -> str:
    return at.strftime("%H:%M")
