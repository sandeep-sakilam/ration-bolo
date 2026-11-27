"""Impact metrics, matching the Round 1 pilot targets:
wait within 20 minutes of the slot, 30% adoption, half as many wasted trips,
85% of calls by voice alone, every complaint resolved within 7 days."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import ist_to_utc, ist_today, now_utc, to_ist
from app.models import Complaint, DialogueSession, Event, Token, Turn

TARGETS = {
    "booked_within_20_min": 0.9,
    "adoption": 0.30,
    "voice_success": 0.85,
    "complaints_resolved_7_days": 1.0,
}


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _without_partner(db: Session, since: datetime) -> dict[str, Any]:
    """Version 3: how much works with nobody's help (reports, levels, nearby, escalation)."""
    from app import levels
    from app.models import Report, Shop

    by_level = {0: 0, 1: 0, 2: 0}
    for shop in db.scalars(select(Shop)):
        by_level[levels.effective_level(db, shop)] += 1
    reports = db.scalars(
        select(Report).where(Report.created_at >= since, Report.source == "caller")
    ).all()
    live = [r for r in reports if not r.reporter_hash.startswith("hist-")]
    events = Counter(
        e.action
        for e in db.scalars(
            select(Event).where(
                Event.at >= since,
                Event.action.in_(
                    (
                        "nearby_offered",
                        "nearby_accepted",
                        "broadcast_sent",
                        "grievance_filed",
                        "grievance_escalated_district",
                        "grievance_escalated_national",
                        "grievance_reference",
                    )
                ),
            )
        )
    )
    return {
        "shops_by_level": by_level,
        "cardholder_reports": sum(1 for r in live if r.kind != "checkin"),
        "check_ins": sum(1 for r in live if r.kind == "checkin"),
        "reporters": len({r.reporter_hash for r in live}),
        "nearby_offered": events["nearby_offered"],
        "nearby_accepted": events["nearby_accepted"],
        "rice_arrived_messages": events["broadcast_sent"],
        "complaints_routed": events["grievance_filed"],
        "complaints_escalated": events["grievance_escalated_district"]
        + events["grievance_escalated_national"],
        "references_recorded": events["grievance_reference"],
    }


def compute(db: Session, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
    now = now or now_utc()
    first_day = ist_today(now) - timedelta(days=days)
    since = ist_to_utc(first_day, time(0, 0))

    served = db.scalars(
        select(Token).where(Token.status == "served", Token.served_at >= since)
    ).all()
    booked_waits, walkin_waits = [], []
    per_day: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"served": 0, "booked": 0, "waits": []}
    )
    for t in served:
        assert t.served_at is not None
        if t.kind == "booked" and t.window is not None:
            start = ist_to_utc(t.window.date, t.window.start_time)
            wait = (t.served_at - start).total_seconds() / 60
            booked_waits.append(max(0.0, wait))
        elif t.kind == "booked":
            wait = (t.served_at - (t.arrived_at or t.issued_at)).total_seconds() / 60
            booked_waits.append(max(0.0, wait))
        else:
            wait = (t.served_at - t.issued_at).total_seconds() / 60
            walkin_waits.append(max(0.0, wait))
        day = per_day[to_ist(t.served_at).date().isoformat()]
        day["served"] += 1
        day["booked"] += t.kind == "booked"
        day["waits"].append(wait)

    bookings = db.scalars(
        select(Token).where(Token.kind == "booked", Token.issued_at >= since)
    ).all()
    late_or_no_show = sum(
        1
        for t in db.scalars(select(Token).where(Token.date >= first_day))
        if t.status in ("late", "no_show")
    )

    sessions = db.scalars(select(DialogueSession).where(DialogueSession.started_at >= since)).all()
    session_ids = {s.id for s in sessions}
    turns = [
        t
        for t in db.scalars(select(Turn).where(Turn.created_at >= since, Turn.role == "caller"))
        if t.session_id in session_ids
    ]
    talked = {t.session_id for t in turns}
    voice_sessions = [s for s in sessions if s.id in talked]
    by_voice = sum(1 for s in voice_sessions if not s.used_menu)
    engines = Counter(t.engine or "unknown" for t in turns)
    understood = sum(1 for t in turns if t.understood)
    switched = sum(1 for s in voice_sessions if s.engine == "backup")

    complaints = db.scalars(
        select(Complaint).where(Complaint.created_at >= since - timedelta(days=7))
    ).all()
    resolved_in_7 = sum(
        1 for c in complaints if c.resolved_at and c.resolved_at - c.created_at <= timedelta(days=7)
    )
    overdue = sum(
        1 for c in complaints if c.status == "open" and now - c.created_at > timedelta(days=7)
    )
    closed_or_due = sum(
        1 for c in complaints if c.resolved_at or now - c.created_at > timedelta(days=7)
    )

    checks = db.scalars(select(Event).where(Event.action == "intent", Event.at >= since)).all()
    trips_checked = sum(1 for e in checks if e.detail.get("intent") in ("stock", "queue"))

    within_20 = sum(1 for w in booked_waits if w <= 20)
    partner = _without_partner(db, since)
    return {
        "demo_data": True,
        "days": days,
        "targets": TARGETS,
        "wait": {
            "booked_avg_minutes": round(mean(booked_waits), 1) if booked_waits else None,
            "walkin_avg_minutes": round(mean(walkin_waits), 1) if walkin_waits else None,
            "booked_within_20_min": _pct(within_20, len(booked_waits)),
            "served": len(served),
        },
        "bookings": {
            "made": len(bookings),
            "adoption": _pct(sum(1 for t in served if t.kind == "booked"), len(served)),
            "late_or_no_show": late_or_no_show,
            "status_checks_by_phone": trips_checked,
        },
        "voice": {
            "sessions": len(voice_sessions),
            "voice_success": _pct(by_voice, len(voice_sessions)),
            "understood_turns": _pct(understood, len(turns)),
            "backup_engine_sessions": _pct(switched, len(voice_sessions)),
            "engines": dict(engines.most_common()),
        },
        "complaints": {
            "filed": len(complaints),
            "open": sum(1 for c in complaints if c.status == "open"),
            "overdue": overdue,
            "resolved_7_days": _pct(resolved_in_7, closed_or_due),
        },
        "without_partner": partner,
        "daily": [
            {
                "day": d,
                "served": v["served"],
                "booked": v["booked"],
                "avg_wait": round(mean(v["waits"]), 1) if v["waits"] else None,
            }
            for d, v in sorted(per_day.items())
        ],
    }
