"""Public transparency page per shop and monthly report (F36).

`/shop/{code}` (no login): level, live status with source and freshness, today's best
times, this month's short-ration complaints and how many were resolved within 7 days,
the number of cardholder reports, and the "Fair shop" badge if earned.
`/shop/{code}/report/{yyyy-mm}.csv` and a printable HTML page serve shop-level vigilance
committees (NFSA Section 29) and social audits (Section 28).

Privacy: no names, phones or card numbers anywhere; any count below 5 is shown as
"fewer than 5".
"""

from __future__ import annotations

import csv
import html
import io
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import besttime, levels, shopstate
from app.clock import ist_to_utc, ist_today, now_utc, to_ist
from app.models import Complaint, Report, Shop, Token

MIN_COUNT = 5
SMALL = "fewer than 5"


def shown(count: int) -> str:
    return SMALL if 0 < count < MIN_COUNT else str(count)


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """'2026-11' → [start, end) in naive UTC (IST month boundaries)."""
    year, mon = (int(x) for x in month.split("-"))
    start = date(year, mon, 1)
    end = date(year + (mon == 12), mon % 12 + 1, 1)
    return ist_to_utc(start, time(0, 0)), ist_to_utc(end, time(0, 0))


def _count(db: Session, model: Any, *where: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def monthly(db: Session, shop: Shop, month: str) -> dict[str, int]:
    start, end = month_bounds(month)
    complaints = db.scalars(
        select(Complaint).where(
            Complaint.shop_id == shop.id, Complaint.created_at >= start, Complaint.created_at < end
        )
    ).all()
    quick = sum(
        1 for c in complaints if c.resolved_at and c.resolved_at - c.created_at <= timedelta(days=7)
    )
    later = sum(
        1 for c in complaints if c.resolved_at and c.resolved_at - c.created_at > timedelta(days=7)
    )
    reports = db.scalars(
        select(Report).where(
            Report.shop_id == shop.id,
            Report.source == "caller",
            Report.created_at >= start,
            Report.created_at < end,
            Report.kind != "queue_size",
        )
    ).all()
    return {
        "short_ration_complaints": len(complaints),
        "resolved_within_7_days": quick,
        "resolved_later": later,
        "still_open": sum(1 for c in complaints if c.status == "open"),
        "cardholder_reports": len(reports),
        "reports_rice_arrived": sum(1 for r in reports if r.kind == "stock_in"),
        "reports_no_rice": sum(1 for r in reports if r.kind == "stock_out"),
        "reports_machine_down": sum(1 for r in reports if r.kind == "machine_down"),
        "check_ins": sum(1 for r in reports if r.kind == "checkin"),
        "families_served": _count(
            db,
            Token,
            Token.shop_id == shop.id,
            Token.status == "served",
            Token.served_at >= start,
            Token.served_at < end,
        ),
        "bookings": _count(
            db,
            Token,
            Token.shop_id == shop.id,
            Token.kind == "booked",
            Token.issued_at >= start,
            Token.issued_at < end,
        ),
    }


def resolved_share(m: dict[str, int]) -> str:
    total = m["short_ration_complaints"]
    if total < MIN_COUNT:
        return "not shown (fewer than 5 complaints)"
    return f"{round(100 * m['resolved_within_7_days'] / total)}%"


def fair_shop(db: Session, shop: Shop, now: datetime | None = None) -> bool:
    """Filled in by F37 (dealer incentives); False until then."""
    from app import incentives

    return incentives.fair_shop(db, shop, now)


def status_lines(db: Session, shop: Shop, now: datetime) -> list[str]:
    view = shopstate.view(db, shop, now)
    lines: list[str] = []
    words = {
        "in_stock": "rice in stock",
        "out": "no rice",
        "working": "machine working",
        "down": "machine down",
    }
    for signal in (view.stock, view.machine):
        if signal is None:
            continue
        if signal.source == "dealer":
            lines.append(f"{words[signal.value].capitalize()} (dealer update)")
        elif signal.source == "reports":
            who = (
                f"confirmed by {shown(signal.count)} cardholders"
                if signal.confirmed
                else "one cardholder report, not yet confirmed"
            )
            lines.append(
                f"{words[signal.value].capitalize()} — {who}, latest "
                f"{signal.age_minutes} minutes ago"
            )
    if view.public is not None and view.public.available and view.public.first_sale:
        lines.append(
            f"Public sales data: selling since "
            f"{to_ist(view.public.first_sale):%H:%M}, "
            f"{view.public.sales_last_hour} sales in the last hour"
        )
    elif view.public is not None and not view.public.available:
        lines.append("Public sales data: unavailable right now")
    lines.extend(f"Sources disagree: {d}" for d in view.disagreements)
    return lines or ["No recent reports for this shop."]


def best_times(db: Session, shop: Shop, now: datetime) -> list[str]:
    waits, known = besttime.expected_waits(db, shop, ist_today(now), now)
    quiet = sorted(waits, key=lambda h: (waits[h], h))[:3]
    label = "usually under {m} minutes" if known else "usually quiet"
    return [
        f"{h:02d}:00–{h + 1:02d}:00 · " + label.format(m=besttime.spoken_minutes(waits[h]))
        for h in sorted(quiet)
    ]


def page_data(db: Session, shop: Shop, now: datetime | None = None) -> dict[str, Any]:
    now = now or now_utc()
    month = to_ist(now).strftime("%Y-%m")
    m = monthly(db, shop, month)
    return {
        "code": shop.code,
        "name": shop.name,
        "area": shop.area,
        "level": levels.label(db, shop, now),
        "month": month,
        "status": status_lines(db, shop, now),
        "best_times": best_times(db, shop, now),
        "monthly": {k: shown(v) for k, v in m.items()},
        "resolved_within_7_days_share": resolved_share(m),
        "fair_shop": fair_shop(db, shop, now),
    }


LABELS = {
    "short_ration_complaints": "Short-ration complaints",
    "resolved_within_7_days": "Resolved within 7 days",
    "resolved_later": "Resolved after 7 days",
    "still_open": "Still open",
    "cardholder_reports": "Cardholder reports (stock, machine, check-ins)",
    "reports_rice_arrived": "· rice arrived",
    "reports_no_rice": "· no rice",
    "reports_machine_down": "· machine down",
    "check_ins": "· check-ins at the shop",
    "families_served": "Families served (recorded sales)",
    "bookings": "Bookings made",
}


def report_csv(db: Session, shop: Shop, month: str) -> str:
    m = monthly(db, shop, month)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["shop_code", "month", "metric", "value"])
    for key, label in LABELS.items():
        writer.writerow([shop.code, month, label.strip("· "), shown(m[key])])
    writer.writerow([shop.code, month, "Share resolved within 7 days", resolved_share(m)])
    writer.writerow(
        [shop.code, month, "Note", "Counts below 5 are shown as 'fewer than 5'. Demo data."]
    )
    return buf.getvalue()


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><link rel="stylesheet" href="/static/css/app.css">
<style>@media print {{ header.top, footer.foot, .noprint {{ display: none; }} }}</style>
</head><body>
<header class="top"><h1>Ration Bolo <span class="badge demo">Demo data</span></h1>
<nav aria-label="Pages"><a href="/simulator">Call simulator</a>
<a href="/dealer">Dealer dashboard</a><a href="/metrics">Impact metrics</a>
<a href="/admin">Admin</a></nav></header>
<main>{body}</main>
<footer class="foot">Public page · no names, phone numbers or card numbers · counts below 5 are
shown as "fewer than 5" · demo data</footer><script src="/static/js/build.js"></script>
</body></html>"""


def render_page(data: dict[str, Any]) -> str:
    e = html.escape
    badge = '<span class="badge ok">Fair shop</span>' if data["fair_shop"] else ""
    status = "".join(f"<li>{e(s)}</li>" for s in data["status"])
    times = "".join(f"<li>{e(t)}</li>" for t in data["best_times"])
    rows = "".join(
        f'<tr><th scope="row">{e(LABELS[k])}</th><td>{e(v)}</td></tr>'
        for k, v in data["monthly"].items()
    )
    body = f"""
<h2>Shop {e(data["code"])} · {e(data["name"])} {badge}</h2>
<p class="small">{e(data["area"])} · {e(data["level"])}</p>
<div class="grid two">
<section class="card"><h2>Right now</h2><ul>{status}</ul></section>
<section class="card"><h2>Quietest times today</h2><ul>{times}</ul></section>
<section class="card"><h2>This month ({e(data["month"])})</h2>
<table><tbody>{rows}<tr><th scope="row">Share resolved within 7 days</th>
<td>{e(data["resolved_within_7_days_share"])}</td></tr></tbody></table></section>
<section class="card noprint"><h2>For vigilance committees and social audits</h2>
<p class="small">Monthly report under NFSA Sections 28–29:</p>
<p><a href="/shop/{e(data["code"])}/report/{e(data["month"])}">Printable report</a> ·
<a href="/shop/{e(data["code"])}/report/{e(data["month"])}.csv">CSV</a></p></section>
</div>"""
    return _page(f"Ration Bolo · Shop {data['code']}", body)


def render_report(db: Session, shop: Shop, month: str) -> str:
    e = html.escape
    m = monthly(db, shop, month)
    rows = "".join(
        f'<tr><th scope="row">{e(LABELS[k])}</th><td>{e(shown(v))}</td></tr>' for k, v in m.items()
    )
    body = f"""
<h2>Monthly report · Shop {e(shop.code)} · {e(month)}</h2>
<p class="small">{e(shop.name)}, {e(shop.area)}. For the shop-level vigilance committee (NFSA
Section 29) and social audit (Section 28).</p>
<section class="card"><table><tbody>{rows}
<tr><th scope="row">Share resolved within 7 days</th><td>{e(resolved_share(m))}</td></tr>
</tbody></table></section>
<p class="noprint"><button type="button" onclick="window.print()">Print</button>
<a href="/shop/{e(shop.code)}/report/{e(month)}.csv">Download CSV</a></p>"""
    return _page(f"Ration Bolo · Shop {shop.code} report {month}", body)
