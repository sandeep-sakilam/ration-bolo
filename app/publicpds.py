"""Public PDS data (F32).

NFSA Section 27 requires PDS records in the public domain, and many states publish
shop-wise ePoS sales on their public PDS portals. This module reads them.

- ``PublicPdsSource`` interface: ``sales_today(shop_code, day) -> list[SaleEvent]``.
- ``MockPublicPds`` reads fixtures (``tests/fixtures/public_pds/<shop>.json``, times IST).
- ``HttpPublicPds`` reads a state portal page from the pack's ``public_pds.url_template``
  (``{shop_code}``, ``{date}`` = YYYY-MM-DD, ``{date_dmy}`` = DD/MM/YYYY) in ``csv`` or
  ``html_table`` format. **Assumed format** (no portal could be checked from the build
  session; Sandeep must confirm it): a header row with a time column (header containing
  "time") and a count column (header containing "transaction", "txn", "count", "sales" or
  "cards"); times like "09:10" or "4:05 PM". Off unless the pack enables it.
- ``PublicPdsService`` caches per shop for 10 minutes, backs off after errors, never
  raises into a call, reports "unavailable" on the status page, and turns sales into
  signals: first sale today (stock arrived, machine works), no sale for 45 minutes during
  open hours ("possibly stopped"), and sales per hour (wait estimates when ≥ 6 an hour).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import ist_to_utc, ist_today, now_utc, to_ist
from app.models import PublicSale, Shop
from app.packs import get_pack

log = logging.getLogger("ration_bolo.public_pds")
ROOT = Path(__file__).resolve().parent.parent
CACHE_MINUTES = 10
STOPPED_AFTER_MIN = 45
MIN_RATE_FOR_WAIT = 6
USER_AGENT = "RationBolo/0.3 (public PDS reader; +https://github.com/sandeep-sakilam/ration-bolo)"


class PublicPdsError(RuntimeError):
    pass


@dataclass(frozen=True)
class SaleEvent:
    time: datetime  # naive UTC
    count: int


class PublicPdsSource(Protocol):
    name: str

    def sales_today(self, shop_code: str, day: date) -> list[SaleEvent]: ...


# --- parsing (pure) ------------------------------------------------------------

TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})(?::\d{2})?\s*([ap]\.?m\.?)?\s*$", re.I)
TIME_HEADERS = ("time",)
COUNT_HEADERS = ("transaction", "txn", "count", "sales", "cards")


def parse_time(text: str) -> time | None:
    m = TIME_RE.match(text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    ampm = (m.group(3) or "").lower().replace(".", "")
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def _columns(header: list[str]) -> tuple[int, int]:
    low = [h.strip().lower() for h in header]
    t_idx = next((i for i, h in enumerate(low) if any(k in h for k in TIME_HEADERS)), -1)
    c_idx = next(
        (i for i, h in enumerate(low) if i != t_idx and any(k in h for k in COUNT_HEADERS)), -1
    )
    if t_idx < 0 or c_idx < 0:
        raise PublicPdsError(f"no time/count columns in header {header}")
    return t_idx, c_idx


def rows_to_events(rows: list[list[str]], day: date) -> list[SaleEvent]:
    if not rows:
        return []
    t_idx, c_idx = _columns(rows[0])
    events: list[SaleEvent] = []
    for row in rows[1:]:
        if len(row) <= max(t_idx, c_idx):
            continue
        at = parse_time(row[t_idx])
        count_text = re.sub(r"[^\d]", "", row[c_idx])
        if at is None or not count_text:
            continue
        events.append(SaleEvent(ist_to_utc(day, at), int(count_text)))
    return sorted(events, key=lambda e: e.time)


def parse_csv(text: str, day: date) -> list[SaleEvent]:
    return rows_to_events([r for r in csv.reader(io.StringIO(text)) if r], day)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.tables = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.tables += 1
        elif tag == "tr" and self.tables == 1:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_html_table(text: str, day: date) -> list[SaleEvent]:
    parser = _TableParser()
    parser.feed(text)
    return rows_to_events(parser.rows, day)


# --- adapters -------------------------------------------------------------------


DEMO_PATTERN = (4, 4, 5, 4, 4, 4)  # every 10 minutes: 25 an hour


def generate_demo_sales(
    day: date, sessions: list[list[str]], now: datetime, first: str = "09:10", stopped: bool = False
) -> list[SaleEvent]:
    """Version 3.1 demo sales, relative to now: first sale at 09:10 IST, then a sale batch
    every 10 minutes (about 25 an hour, small deterministic variation by day) during open
    sessions only, up to now. Each session after the first sale starts selling at its
    opening minute, so a gap of 45 minutes never happens while open. ``stopped`` (tests
    only) ends sales an hour before now."""
    first_at = parse_time(first) or time(9, 10)
    cutoff = now - timedelta(hours=1) if stopped else now
    shift = day.toordinal() % len(DEMO_PATTERN)
    events: list[SaleEvent] = []
    i = 0
    for start_s, end_s in sessions:
        start, end = time.fromisoformat(start_s), time.fromisoformat(end_s)
        if end <= first_at:
            continue
        t = datetime.combine(day, max(start, first_at))
        end_dt = datetime.combine(day, end)
        while t < end_dt:
            when = ist_to_utc(day, t.time())
            if when > cutoff:
                return events
            events.append(SaleEvent(when, DEMO_PATTERN[(i + shift) % len(DEMO_PATTERN)]))
            t += timedelta(minutes=10)
            i += 1
    return events


class MockPublicPds:
    """Fixture-backed: ``<dir>/<shop_code>.json`` with {"sales": [{"time": "09:10",
    "count": 4}, ...]} as IST times today; only sales up to now are returned.

    In demo mode (``demo=True``) a fixture with a ``"demo"`` block is generated relative to
    now instead (see ``generate_demo_sales``), so the demo never goes stale."""

    name = "mock"

    def __init__(
        self, fixture_dir: str | Path, fail: bool = False, demo: bool = False, stopped: bool = False
    ) -> None:
        self.dir = Path(fixture_dir)
        self.fail = fail
        self.demo = demo
        self.stopped = stopped

    def generated(self, shop_code: str) -> bool:
        path = self.dir / f"{shop_code}.json"
        if not self.demo or not path.exists():
            return False
        return "demo" in json.loads(path.read_text(encoding="utf-8"))

    def has(self, shop_code: str) -> bool:
        return (self.dir / f"{shop_code}.json").exists()

    def sales_today(self, shop_code: str, day: date) -> list[SaleEvent]:
        if self.fail:
            raise PublicPdsError("mock source set to fail")
        path = self.dir / f"{shop_code}.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        now = now_utc()
        if self.demo and "demo" in data:
            spec = data["demo"]
            return generate_demo_sales(
                day,
                spec.get("sessions", [["08:00", "12:00"], ["16:00", "20:00"]]),
                now,
                spec.get("first_sale", "09:10"),
                self.stopped,
            )
        events = []
        for sale in data.get("sales", []):
            at = parse_time(str(sale["time"]))
            if at is None:
                continue
            when = ist_to_utc(day, at)
            if when <= now:
                events.append(SaleEvent(when, int(sale["count"])))
        return events


class HttpPublicPds:
    name = "http"

    def __init__(
        self, url_template: str, fmt: str, client: httpx.Client | None = None, timeout: float = 10.0
    ) -> None:
        self.url_template, self.fmt, self.timeout = url_template, fmt, timeout
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT})

    def url(self, shop_code: str, day: date) -> str:
        return self.url_template.format(
            shop_code=shop_code, date=day.isoformat(), date_dmy=day.strftime("%d/%m/%Y")
        )

    def sales_today(self, shop_code: str, day: date) -> list[SaleEvent]:
        try:
            resp = self.client.get(
                self.url(shop_code, day), timeout=self.timeout, follow_redirects=True
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise PublicPdsError(f"{type(exc).__name__}") from exc
        if self.fmt == "html_table":
            return parse_html_table(resp.text, day)
        return parse_csv(resp.text, day)


# --- signals (pure) ----------------------------------------------------------------


@dataclass
class PublicSignals:
    available: bool
    first_sale: datetime | None = None
    last_sale: datetime | None = None
    sales_last_hour: int = 0
    possibly_stopped: bool = False
    stopped_minutes: int = 0
    error: str | None = None
    total_today: int = 0
    open_now: bool = False
    not_started: bool = False  # open hours but no sale yet today
    closed_now: bool = False  # outside open hours (between sessions or after closing)
    opens_at: datetime | None = None  # next opening (naive UTC)

    @property
    def minutes_per_family(self) -> float | None:
        if self.sales_last_hour >= MIN_RATE_FOR_WAIT:
            return 60 / self.sales_last_hour
        return None


def signals(
    events: list[SaleEvent], now: datetime, open_now: bool, opens_at: datetime | None = None
) -> PublicSignals:
    if not events:
        return PublicSignals(
            available=True,
            open_now=open_now,
            not_started=True,
            closed_now=not open_now,
            opens_at=opens_at,
        )
    first, last = events[0].time, events[-1].time
    last_hour = sum(e.count for e in events if now - timedelta(hours=1) < e.time <= now)
    gap = int((now - last).total_seconds() // 60)
    return PublicSignals(
        available=True,
        first_sale=first,
        last_sale=last,
        sales_last_hour=last_hour,
        possibly_stopped=open_now and gap >= STOPPED_AFTER_MIN,
        stopped_minutes=gap,
        total_today=sum(e.count for e in events),
        open_now=open_now,
        closed_now=not open_now,
        opens_at=None if open_now else opens_at,
    )


def next_opening(shop: Shop, now: datetime) -> datetime:
    """The next session start after now (today or tomorrow), naive UTC."""
    local = to_ist(now)
    for day in (local.date(), local.date() + timedelta(days=1)):
        for start, _end in sorted(shop.sessions):
            at = ist_to_utc(day, time.fromisoformat(start))
            if at > now:
                return at
    return ist_to_utc(local.date() + timedelta(days=1), time.fromisoformat(shop.sessions[0][0]))


def last_session(shop: Shop, now: datetime) -> tuple[str, int] | None:
    """The most recent session that has ended, as (today | yesterday, its start hour IST);
    None while a session is running or the shop has no sessions (F46)."""
    if is_open(shop, now) or not shop.sessions:
        return None
    local = to_ist(now)
    ended = [s for s in sorted(shop.sessions) if time.fromisoformat(s[1]) <= local.time()]
    if ended:
        return "today", time.fromisoformat(ended[-1][0]).hour
    return "yesterday", time.fromisoformat(sorted(shop.sessions)[-1][0]).hour


def is_open(shop: Shop, now: datetime) -> bool:
    local = to_ist(now).time()
    for start, end in shop.sessions:
        if time.fromisoformat(start) <= local < time.fromisoformat(end):
            return True
    return False


# --- service ------------------------------------------------------------------------


@dataclass
class _Entry:
    fetched_at: datetime
    events: list[SaleEvent]
    error: str | None = None
    failures: int = 0
    retry_after: datetime | None = None


@dataclass
class PublicPdsService:
    mode: str = "auto"  # auto | mock | off
    mock: MockPublicPds = field(
        default_factory=lambda: MockPublicPds(ROOT / "tests" / "fixtures" / "public_pds")
    )
    http_factory: type[HttpPublicPds] = HttpPublicPds
    _cache: dict[str, _Entry] = field(default_factory=dict)
    last_error: str | None = None

    def source_for(self, shop: Shop) -> PublicPdsSource | None:
        if self.mode == "off":
            return None
        cfg = get_pack(shop.state_pack).raw["public_pds"]
        if self.mode == "auto" and cfg.get("enabled") and cfg.get("url_template"):
            return self.http_factory(cfg["url_template"], cfg.get("format", "csv"))
        return self.mock if self.mock.has(shop.code) or self.mock.fail else None

    def events(self, shop: Shop, now: datetime | None = None) -> _Entry | None:
        now = now or now_utc()
        source = self.source_for(shop)
        if source is None:
            return None
        entry = self._cache.get(shop.code)
        if entry and entry.retry_after and now < entry.retry_after:
            return entry
        if (
            entry
            and entry.error is None
            and now - entry.fetched_at < timedelta(minutes=CACHE_MINUTES)
        ):
            return entry
        try:
            fetched = source.sales_today(shop.code, ist_today(now))
            entry = _Entry(now, fetched)
            self.last_error = None
        except Exception as exc:  # never break a call over public data
            failures = (entry.failures if entry else 0) + 1
            backoff = min(120, CACHE_MINUTES * 2 ** (failures - 1))
            entry = _Entry(
                now,
                entry.events if entry else [],
                str(exc)[:200],
                failures,
                now + timedelta(minutes=backoff),
            )
            self.last_error = entry.error
            log.warning("public PDS unavailable for shop %s: %s", shop.code, entry.error)
        self._cache[shop.code] = entry
        return entry

    def signals(self, shop: Shop, now: datetime | None = None) -> PublicSignals | None:
        now = now or now_utc()
        entry = self.events(shop, now)
        if entry is None:
            return None
        if entry.error is not None:
            return PublicSignals(available=False, error=entry.error)
        result = signals(entry.events, now, is_open(shop, now), next_opening(shop, now))
        if self.mode != "off" and self.mock.generated(shop.code) and not self.mock.stopped:
            result.possibly_stopped = False  # demo sales never fake a stoppage
        return result

    def store(self, db: Session, shop: Shop, now: datetime | None = None) -> int:
        """Save new sale events as snapshots (used by the polling job)."""
        entry = self.events(shop, now)
        if entry is None or entry.error is not None:
            return 0
        known = set(
            db.scalars(
                select(PublicSale.sale_time).where(
                    PublicSale.shop_id == shop.id,
                    PublicSale.sale_time >= ist_to_utc(ist_today(now), time(0, 0)),
                )
            )
        )
        added = 0
        for event in entry.events:
            if event.time not in known:
                db.add(
                    PublicSale(
                        shop_id=shop.id,
                        observed_at=now or now_utc(),
                        sale_time=event.time,
                        count=event.count,
                        source_url=type(self.source_for(shop)).__name__,
                    )
                )
                added += 1
        return added

    def status(self) -> dict[str, object]:
        return {
            "service": "public_pds",
            "provider": "State public PDS portal (shop-wise sales)",
            "mode": "off" if self.mode == "off" else ("mock" if self.mode == "mock" else "auto"),
            "ready": self.mode != "off" and self.last_error is None,
            "missing_keys": [],
            "note": "unavailable: " + self.last_error
            if self.last_error
            else (
                "off"
                if self.mode == "off"
                else "using demo fixtures unless a state pack enables its portal (format to "
                "be confirmed)"
            ),
        }


_current: PublicPdsService | None = None


def register(service: PublicPdsService) -> None:
    global _current
    _current = service


def current() -> PublicPdsService:
    global _current
    if _current is None:
        _current = PublicPdsService()
    return _current
