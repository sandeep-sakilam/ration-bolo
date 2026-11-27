"""Cardholder reports and check-ins (F31): agreement, decay, outliers and reliability.

Rules (pure functions below, database helpers after):
- a status is "confirmed" when at least 2 different phones report it within 45 minutes,
  or 1 dealer or volunteer update arrives;
- each report's weight halves every 30 minutes and is ignored after 3 hours;
- one vote per phone per signal per hour (a new report replaces the phone's last one);
- queue size is the weighted median of recent queue reports (and the check-in count),
  after dropping reports more than 3× the median;
- each reporter's weight starts at 1.0 and moves between 0.2 and 2.0 as later evidence
  agrees or disagrees.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import now_utc
from app.models import Report, ReporterScore, Shop

HALF_LIFE_MIN = 30.0
MAX_AGE_MIN = 180.0
AGREE_WINDOW_MIN = 45.0
VOTE_WINDOW_MIN = 60.0
OUTLIER_FACTOR = 3.0
CHECKIN_WINDOW_MIN = 30.0
WEIGHT_MIN, WEIGHT_MAX = 0.2, 2.0
AGREE_STEP, DISAGREE_STEP = 0.1, 0.2
STRONG_SOURCES = {"dealer", "volunteer"}

# kind -> (signal, value)
SIGNALS = {
    "stock_in": ("stock", "in_stock"),
    "stock_out": ("stock", "out"),
    "machine_down": ("machine", "down"),
    "machine_ok": ("machine", "working"),
    "queue_size": ("queue", None),
    "checkin": ("checkin", None),
}


@dataclass(frozen=True)
class Vote:
    kind: str
    reporter: str
    source: str
    weight: float
    age_min: float
    value: int | None = None


@dataclass(frozen=True)
class Verdict:
    signal: str
    value: str
    confirmed: bool
    count: int  # different phones supporting it within 3 hours
    newest_age_min: float
    oldest_age_min: float  # oldest supporting report (for "in the last N minutes")
    score: float
    sources: frozenset[str]


def decayed(weight: float, age_min: float) -> float:
    """Weight halves every 30 minutes; nothing after 3 hours."""
    if age_min < 0 or age_min > MAX_AGE_MIN:
        return 0.0
    return weight * 0.5 ** (age_min / HALF_LIFE_MIN)


def verdict(votes: list[Vote], signal: str) -> Verdict | None:
    """The winning value for a signal (stock or machine), or None without valid votes."""
    by_value: dict[str, list[Vote]] = {}
    for v in votes:
        sig, value = SIGNALS[v.kind]
        if sig == signal and value is not None and v.age_min <= MAX_AGE_MIN:
            by_value.setdefault(value, []).append(v)
    if not by_value:
        return None
    scores = {val: sum(decayed(v.weight, v.age_min) for v in vs) for val, vs in by_value.items()}
    best = max(scores, key=lambda val: (scores[val], -min(v.age_min for v in by_value[val])))
    support = by_value[best]
    recent = {v.reporter for v in support if v.age_min <= AGREE_WINDOW_MIN}
    strong = any(v.source in STRONG_SOURCES for v in support)
    return Verdict(
        signal=signal,
        value=best,
        confirmed=len(recent) >= 2 or strong,
        count=len({v.reporter for v in support}),
        newest_age_min=min(v.age_min for v in support),
        oldest_age_min=max(v.age_min for v in support),
        score=scores[best],
        sources=frozenset(v.source for v in support),
    )


def weighted_median(pairs: list[tuple[float, float]]) -> float:
    """Median of values with weights (value, weight)."""
    pairs = sorted(p for p in pairs if p[1] > 0)
    total = sum(w for _, w in pairs)
    acc = 0.0
    for value, weight in pairs:
        acc += weight
        if acc >= total / 2:
            return value
    return pairs[-1][0]


def queue_estimate(votes: list[Vote]) -> int | None:
    """People at the shop: weighted median of recent queue reports and the check-in count,
    after dropping reports more than 3× the plain median."""
    points = [
        (float(v.value), decayed(v.weight, v.age_min))
        for v in votes
        if v.kind == "queue_size" and v.value is not None and v.age_min <= MAX_AGE_MIN
    ]
    checkins = [v for v in votes if v.kind == "checkin" and v.age_min <= CHECKIN_WINDOW_MIN]
    if checkins:
        points.append((float(len(checkins)), 1.0))
    points = [p for p in points if p[1] > 0]
    if not points:
        return None
    mid = median(v for v, _ in points)
    kept = [p for p in points if mid == 0 or p[0] <= OUTLIER_FACTOR * mid]
    return round(weighted_median(kept))


def adjust(weight: float, agrees: bool) -> float:
    step = AGREE_STEP if agrees else -DISAGREE_STEP
    return min(WEIGHT_MAX, max(WEIGHT_MIN, round(weight + step, 3)))


# --- database helpers ------------------------------------------------------


def reporter_hash(phone: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{phone.removeprefix('whatsapp:')}".encode()).hexdigest()


def _weight_of(db: Session, reporter: str) -> float:
    row = db.get(ReporterScore, reporter)
    return float(row.weight) if row else 1.0


def save(
    db: Session,
    shop: Shop,
    kind: str,
    reporter: str,
    source: str = "caller",
    value: int | None = None,
    now: datetime | None = None,
) -> Report:
    """Store a report. One vote per phone per signal per hour: a repeat replaces it."""
    now = now or now_utc()
    signal = SIGNALS[kind][0]
    same_signal = [k for k, (s, _) in SIGNALS.items() if s == signal]
    previous = None
    if kind != "checkin":
        previous = db.scalars(
            select(Report)
            .where(
                Report.shop_id == shop.id,
                Report.reporter_hash == reporter,
                Report.kind.in_(same_signal),
                Report.created_at >= now - timedelta(minutes=VOTE_WINDOW_MIN),
            )
            .order_by(Report.created_at.desc())
        ).first()
    weight = _weight_of(db, reporter) * (2.0 if source in STRONG_SOURCES else 1.0)
    if previous is not None:
        previous.kind, previous.value, previous.created_at = kind, value, now
        previous.weight, previous.source, previous.scored = weight, source, False
        report = previous
    else:
        report = Report(
            shop_id=shop.id,
            kind=kind,
            value=value,
            reporter_hash=reporter,
            source=source,
            weight=weight,
            created_at=now,
        )
        db.add(report)
    db.flush()
    if signal in ("stock", "machine"):
        _score(db, shop, signal, now)
    return report


def votes(db: Session, shop: Shop, now: datetime | None = None) -> list[Vote]:
    now = now or now_utc()
    rows = db.scalars(
        select(Report).where(
            Report.shop_id == shop.id, Report.created_at >= now - timedelta(minutes=MAX_AGE_MIN)
        )
    ).all()
    return [
        Vote(
            r.kind,
            r.reporter_hash,
            r.source,
            r.weight,
            max(0.0, (now - r.created_at).total_seconds() / 60),
            r.value,
        )
        for r in rows
    ]


def _score(db: Session, shop: Shop, signal: str, now: datetime) -> None:
    """When a signal is confirmed, reporters who agreed gain weight and those who
    disagreed lose it (each report is scored once)."""
    current = votes(db, shop, now)
    result = verdict(current, signal)
    if result is None or not result.confirmed:
        return
    rows = db.scalars(
        select(Report).where(
            Report.shop_id == shop.id,
            Report.scored.is_(False),
            Report.source == "caller",
            Report.created_at >= now - timedelta(minutes=AGREE_WINDOW_MIN),
        )
    ).all()
    for row in rows:
        sig, value = SIGNALS[row.kind]
        if sig != signal:
            continue
        score = db.get(ReporterScore, row.reporter_hash)
        if score is None:
            score = ReporterScore(reporter_hash=row.reporter_hash, weight=1.0, updated_at=now)
            db.add(score)
        score.weight = adjust(score.weight, value == result.value)
        score.updated_at = now
        row.scored = True
    db.flush()


def checkins_recent(
    db: Session, shop: Shop, now: datetime | None = None, minutes: float = 60.0
) -> int:
    now = now or now_utc()
    return len([v for v in votes(db, shop, now) if v.kind == "checkin" and v.age_min <= minutes])


def rounded_minutes(age_min: float) -> int:
    """Ages are spoken rounded up to 5 minutes ("in the last 30 minutes")."""
    return max(5, int(math.ceil(age_min / 5.0) * 5))
