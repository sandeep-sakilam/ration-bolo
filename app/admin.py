"""Multi-shop admin: an overview of every shop and CSV import of shops and ration cards.

Imports are all-or-nothing: every row is validated first and any error rejects the
whole file with row numbers, so a half-imported file never reaches callers.
"""

from __future__ import annotations

import csv
import io
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import levels, queue
from app.clock import ist_today
from app.db import get_db
from app.models import Card, Complaint, PhoneLink, Shop, Token
from app.packs import all_packs
from app.ratelimit import RateLimiter

SHOP_FIELDS = [
    "code",
    "name",
    "area",
    "state_pack",
    "sessions",
    "families_per_hour",
    "booked_share",
]
CARD_FIELDS = ["card_no", "shop_code", "members", "language", "phone"]
SHOP_TEMPLATE = (
    ",".join(SHOP_FIELDS) + ",level,lat,lon,ward,landmark,portability\n"
    '120,Fair Price Shop 120,"Saidabad, Hyderabad",telangana,08:00-12:00;16:00-20:00,30,0.5,'
    '0,17.3600,78.5000,Saidabad,"near the bus stop",yes\n'
)
CARD_TEMPLATE = ",".join(CARD_FIELDS) + "\nTS-120-0001,120,4,te,+919000001234\n"
SESSION_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")
PHONE_RE = re.compile(r"^\+[1-9]\d{9,14}$")
MAX_ROWS = 20000


def require_admin(request: Request, x_admin_pin: str = Header(default="")) -> None:
    expected: str = request.app.state.settings.admin_pin
    if expected and not secrets.compare_digest(x_admin_pin.encode(), expected.encode()):
        raise HTTPException(401, "wrong admin PIN")


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


def _rows(upload: UploadFile, fields: list[str]) -> list[dict[str, str]]:
    raw = upload.file.read(5_000_000)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "file must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    missing = [f for f in fields if f not in (reader.fieldnames or []) and f != "phone"]
    if missing:
        raise HTTPException(400, f"missing columns: {', '.join(missing)}")
    rows = [{k: (v or "").strip() for k, v in row.items() if k} for row in reader]
    if len(rows) > MAX_ROWS:
        raise HTTPException(400, f"at most {MAX_ROWS} rows per file")
    return rows


def parse_sessions(value: str) -> list[list[str]]:
    parts = [p.strip() for p in value.split(";") if p.strip()]
    if not parts or not all(SESSION_RE.match(p) for p in parts):
        raise ValueError("sessions must look like 08:00-12:00;16:00-20:00")
    sessions = [p.split("-") for p in parts]
    if any(a >= b for a, b in sessions):
        raise ValueError("each session must end after it starts")
    return sessions


def import_shops(db: Session, rows: list[dict[str, str]]) -> ImportResult:
    result = ImportResult()
    packs = all_packs()
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, row in enumerate(rows, start=2):  # row 1 is the header
        try:
            code = row["code"]
            if not code or code in seen:
                raise ValueError("code is empty or repeated")
            seen.add(code)
            if row["state_pack"] not in packs:
                raise ValueError(f"unknown state_pack '{row['state_pack']}'")
            fph = int(row["families_per_hour"] or 30)
            share = float(row["booked_share"] or 0.5)
            if not 3 <= fph <= 300 or not 0 <= share <= 1:
                raise ValueError("families_per_hour 3–300, booked_share 0–1")
            if not row["name"]:
                raise ValueError("name is empty")
            profile = _profile_fields(row)
            parsed.append(
                {
                    "_profile": profile,
                    "code": code,
                    "name": row["name"],
                    "area": row["area"],
                    "state_pack": row["state_pack"],
                    "sessions": parse_sessions(row["sessions"]),
                    "families_per_hour": fph,
                    "booked_share": share,
                }
            )
        except (KeyError, ValueError) as exc:
            result.errors.append(f"row {n}: {exc}")
    if result.errors:
        return result
    for data in parsed:
        profile = data.pop("_profile")
        shop = db.scalars(select(Shop).where(Shop.code == data["code"])).first()
        if shop is None:
            shop = Shop(**data, status_stock="in_stock", status_machine="working")
            db.add(shop)
            db.flush()
            result.created += 1
        else:
            for key, value in data.items():
                setattr(shop, key, value)
            result.updated += 1
        if profile:
            levels.set_profile(db, shop, **profile)
    queue.log_event(db, "admin", "shops_imported", rows=len(parsed))
    db.commit()
    return result


OPTIONAL_SHOP_FIELDS = ["level", "lat", "lon", "ward", "landmark", "portability"]


def _profile_fields(row: dict[str, str]) -> dict[str, Any]:
    """Optional version 3 columns: level (0/1/2), lat, lon, ward, landmark, portability."""
    out: dict[str, Any] = {}
    if row.get("level", ""):
        level = int(row["level"])
        if level not in (0, 1, 2):
            raise ValueError("level must be 0, 1 or 2")
        out["level"] = level
    for key, limit in (("lat", 90.0), ("lon", 180.0)):
        if row.get(key, ""):
            value = float(row[key])
            if not -limit <= value <= limit:
                raise ValueError(f"{key} out of range")
            out[key] = value
    for key in ("ward", "landmark"):
        if row.get(key, ""):
            out[key] = row[key][:120]
    if row.get("portability", ""):
        out["portability"] = row["portability"].lower() in ("1", "true", "yes", "y")
    return out


class ProfileIn(BaseModel):
    level: int | None = None
    lat: float | None = None
    lon: float | None = None
    ward: str | None = None
    landmark: str | None = None
    portability: bool | None = None


@router.post("/shops/{code}/profile")
def update_profile(code: str, body: ProfileIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    shop = db.scalars(select(Shop).where(Shop.code == code)).first()
    if shop is None:
        raise HTTPException(404, "no such shop")
    try:
        levels.set_profile(db, shop, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    queue.log_event(
        db,
        "admin",
        "shop_profile",
        f"shop:{code}",
        **{k: v for k, v in body.model_dump().items() if v is not None},
    )
    db.commit()
    return {"code": code, "level": levels.base_level(db, shop), "message": f"Shop {code} updated"}


def import_cards(db: Session, rows: list[dict[str, str]]) -> ImportResult:
    result = ImportResult()
    shops = {s.code: s for s in db.scalars(select(Shop))}
    packs = all_packs()
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, row in enumerate(rows, start=2):
        try:
            card_no = row["card_no"].upper()
            if not re.search(r"\d{4}", card_no) or card_no in seen:
                raise ValueError("card_no needs at least 4 digits and must be unique")
            seen.add(card_no)
            shop = shops.get(row["shop_code"])
            if shop is None:
                raise ValueError(f"unknown shop_code '{row['shop_code']}'")
            members = int(row["members"])
            if not 1 <= members <= 30:
                raise ValueError("members must be 1–30")
            pack = packs[shop.state_pack]
            language = row["language"] or pack.default_language
            if language not in pack.languages:
                raise ValueError(f"language '{language}' is not in the {pack.name} pack")
            phone = row.get("phone", "").replace(" ", "")
            if phone and not PHONE_RE.match(phone):
                raise ValueError("phone must be E.164, e.g. +919812345678")
            parsed.append(
                {
                    "card_no": card_no,
                    "shop": shop,
                    "members": members,
                    "language": language,
                    "phone": phone,
                }
            )
        except (KeyError, ValueError) as exc:
            result.errors.append(f"row {n}: {exc}")
    if result.errors:
        return result
    for data in parsed:
        shop = data["shop"]
        card = db.scalars(select(Card).where(Card.card_no == data["card_no"])).first()
        if card is None:
            card = Card(
                card_no=data["card_no"],
                shop_id=shop.id,
                members=data["members"],
                language=data["language"],
                state_pack=shop.state_pack,
            )
            db.add(card)
            db.flush()
            result.created += 1
        else:
            card.shop_id, card.members = shop.id, data["members"]
            card.language, card.state_pack = data["language"], shop.state_pack
            result.updated += 1
        if data["phone"]:
            exists = db.scalars(
                select(PhoneLink).where(
                    PhoneLink.phone_e164 == data["phone"], PhoneLink.card_id == card.id
                )
            ).first()
            if exists is None:
                db.add(PhoneLink(phone_e164=data["phone"], card_id=card.id, source="verified"))
    queue.log_event(db, "admin", "cards_imported", rows=len(parsed))
    db.commit()
    return result


def _response(result: ImportResult) -> dict[str, Any]:
    if result.errors:
        raise HTTPException(422, {"message": "nothing imported", "errors": result.errors[:50]})
    return {
        "created": result.created,
        "updated": result.updated,
        "message": f"Imported: {result.created} new, {result.updated} updated",
    }


IMPORT_LIMIT = RateLimiter(limit=20, window_seconds=60)


def _limit(request: Request) -> None:
    IMPORT_LIMIT.check(f"import:{request.client.host if request.client else ''}")


@router.post("/import/shops")
def upload_shops(
    request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _limit(request)
    return _response(import_shops(db, _rows(file, SHOP_FIELDS)))


@router.post("/import/cards")
def upload_cards(
    request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict[str, Any]:
    _limit(request)
    return _response(import_cards(db, _rows(file, CARD_FIELDS)))


@router.get("/templates/{kind}.csv", response_class=PlainTextResponse)
def template(kind: str) -> str:
    if kind == "shops":
        return SHOP_TEMPLATE
    if kind == "cards":
        return CARD_TEMPLATE
    raise HTTPException(404)


@router.get("/shops")
def shops(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    today = ist_today()
    out = []
    for shop in db.scalars(select(Shop).order_by(Shop.code)):
        cards = db.scalar(select(func.count()).select_from(Card).where(Card.shop_id == shop.id))
        waiting = queue.people_ahead_now(db, shop).ahead
        booked = db.scalar(
            select(func.count())
            .select_from(Token)
            .where(
                Token.shop_id == shop.id,
                Token.kind == "booked",
                Token.date >= today,
                Token.status == "booked",
            )
        )
        complaints = db.scalar(
            select(func.count())
            .select_from(Complaint)
            .where(Complaint.shop_id == shop.id, Complaint.status == "open")
        )
        prof = levels.profile(db, shop)
        out.append(
            {
                "code": shop.code,
                "name": shop.name,
                "area": shop.area,
                "level": levels.effective_level(db, shop),
                "base_level": prof.level,
                "level_label": levels.label(db, shop),
                "ward": prof.ward,
                "landmark": prof.landmark,
                "lat": prof.lat,
                "lon": prof.lon,
                "portability": prof.portability,
                "state_pack": shop.state_pack,
                "stock": shop.status_stock,
                "machine": shop.status_machine,
                "cards": cards or 0,
                "waiting": waiting,
                "upcoming_bookings": booked or 0,
                "open_complaints": complaints or 0,
                "sessions": ";".join("-".join(s) for s in shop.sessions),
            }
        )
    return out
