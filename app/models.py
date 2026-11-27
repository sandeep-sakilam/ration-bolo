"""Database models (SQLAlchemy 2). Times are naive UTC; weights are integer grams."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.clock import now_utc
from app.db import Base


class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    area: Mapped[str] = mapped_column(String(120))
    state_pack: Mapped[str] = mapped_column(String(40))
    sessions: Mapped[list[list[str]]] = mapped_column(JSON)  # [["08:00","12:00"], ...] IST
    families_per_hour: Mapped[int] = mapped_column(Integer, default=30)
    booked_share: Mapped[float] = mapped_column(default=0.5)
    status_stock: Mapped[str] = mapped_column(String(16), default="in_stock")  # in_stock|out
    status_machine: Mapped[str] = mapped_column(String(16), default="working")  # working|down


class Card(Base):
    __tablename__ = "cards"
    id: Mapped[int] = mapped_column(primary_key=True)
    card_no: Mapped[str] = mapped_column(String(40), unique=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    members: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(8))
    state_pack: Mapped[str] = mapped_column(String(40))
    shop: Mapped[Shop] = relationship()

    @property
    def digits(self) -> str:
        return "".join(c for c in self.card_no if c.isdigit())

    @property
    def last4(self) -> str:
        return self.digits[-4:]


class CardHolder(Base):
    """Demo labels only. Never spoken or sent in messages."""

    __tablename__ = "card_holders"
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(80))


class PhoneLink(Base):
    __tablename__ = "phone_links"
    __table_args__ = (UniqueConstraint("phone_e164", "card_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    phone_e164: Mapped[str] = mapped_column(String(20), index=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"))
    source: Mapped[str] = mapped_column(String(20))  # seed|self_registered|verified
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    card: Mapped[Card] = relationship()


class Window(Base):
    """A 20-minute serving window. ``date`` and ``start_time`` are shop-local (IST)."""

    __tablename__ = "windows"
    __table_args__ = (UniqueConstraint("shop_id", "date", "start_time"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[time] = mapped_column(Time)
    booked_capacity: Mapped[int] = mapped_column(Integer)
    walkin_capacity: Mapped[int] = mapped_column(Integer)


class Token(Base):
    __tablename__ = "tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    date: Mapped[date] = mapped_column(Date, index=True)
    token_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))  # booked|walkin
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"), nullable=True)
    window_id: Mapped[int | None] = mapped_column(ForeignKey("windows.id"), nullable=True)
    # booked|arrived|served|late|no_show|cancelled|waiting
    status: Mapped[str] = mapped_column(String(12))
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    served_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="dealer")
    card: Mapped[Card | None] = relationship()
    window: Mapped[Window | None] = relationship()

    @property
    def label(self) -> str:
        return f"{'B' if self.kind == 'booked' else 'W'}-{self.token_no:03d}"


class Distribution(Base):
    __tablename__ = "distributions"
    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"), nullable=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    grams_given: Mapped[int] = mapped_column(Integer)
    served_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    token_id: Mapped[int | None] = mapped_column(ForeignKey("tokens.id"), nullable=True)


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_no: Mapped[str] = mapped_column(String(20), unique=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"))
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"))
    grams_due: Mapped[int] = mapped_column(Integer)
    grams_received: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|resolved
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    card: Mapped[Card] = relationship()


class DialogueSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(16))  # call|whatsapp|simulator
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phone_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone_masked: Mapped[str] = mapped_column(String(24), default="")
    card_id: Mapped[int | None] = mapped_column(ForeignKey("cards.id"), nullable=True)
    state_pack: Mapped[str] = mapped_column(String(40), default="telangana")
    language: Mapped[str] = mapped_column(String(8), default="te")
    state: Mapped[str] = mapped_column(String(32), default="start")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    silences: Mapped[int] = mapped_column(Integer, default=0)
    used_menu: Mapped[bool] = mapped_column(default=False)
    engine: Mapped[str] = mapped_column(String(16), default="primary")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    card: Mapped[Card | None] = relationship()


class Turn(Base):
    """Transcript text only; caller audio is never stored."""

    __tablename__ = "turns"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # caller|app
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="")
    engine: Mapped[str] = mapped_column(String(16), default="")
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    understood: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"))
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(12), default="pending"
    )  # pending|sent|failed|cancelled
    token: Mapped[Token] = relationship()


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(12))  # sms|whatsapp|call
    to_masked: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12))  # mock|sent|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)


class Event(Base):
    """Append-only log for metrics and audit."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)
    actor: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(40))
    object: Mapped[str] = mapped_column(String(60), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def mask_phone(phone: str | None) -> str:
    """+919000004401 → +91 •••• ••4401"""
    if not phone:
        return "unknown"
    digits = phone.removeprefix("whatsapp:")
    if digits.startswith("+91") and len(digits) == 13:
        return f"+91 •••• ••{digits[-4:]}"
    return f"•••• {digits[-4:]}" if len(digits) >= 4 else "••••"


class DemoCard(Base):
    """Marks a card as seeded demo data and remembers its seeded language (F23)."""

    __tablename__ = "demo_cards"
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id"), primary_key=True)
    language: Mapped[str] = mapped_column(String(8))


class StatusTimer(Base):
    """When a shop's stock or machine status went abnormal (for demo auto-restore)."""

    __tablename__ = "status_timers"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)  # stock|machine
    set_at: Mapped[datetime] = mapped_column(DateTime)


class ShopProfile(Base):
    """Version 3 shop fields in a new table (no new columns on `shops`): level 0/1/2,
    location for nearby-shop suggestions, portability and the dealer's phone hash."""

    __tablename__ = "shop_profiles"
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    lat: Mapped[float | None] = mapped_column(nullable=True)
    lon: Mapped[float | None] = mapped_column(nullable=True)
    ward: Mapped[str] = mapped_column(String(80), default="")
    landmark: Mapped[str] = mapped_column(String(120), default="")
    portability: Mapped[bool] = mapped_column(default=True)
    dealer_phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Report(Base):
    """A cardholder (or dealer/volunteer/public-data) report about a shop (F31).

    Only a salted hash of the reporter's phone is stored, never the number."""

    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    # stock_in | stock_out | machine_down | machine_ok | queue_size | checkin
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reporter_hash: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16))  # caller | dealer | volunteer | public_pds
    weight: Mapped[float] = mapped_column(default=1.0)
    scored: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, index=True)


class ReporterScore(Base):
    """Reliability of a reporter (0.2–2.0), by phone hash (F31)."""

    __tablename__ = "reporter_scores"
    reporter_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    weight: Mapped[float] = mapped_column(default=1.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
