"""Public pages (no login): per-shop transparency page and monthly report (F36)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import transparency
from app.db import get_db
from app.models import Shop

router = APIRouter(tags=["public"])
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _shop(db: Session, code: str) -> Shop:
    shop = db.scalars(select(Shop).where(Shop.code == code)).first()
    if shop is None:
        raise HTTPException(404, "no such shop")
    return shop


@router.get("/shop/{code}", response_class=HTMLResponse)
def shop_page(code: str, db: Session = Depends(get_db)) -> str:
    shop = _shop(db, code)
    return transparency.render_page(transparency.page_data(db, shop))


@router.get("/api/shop/{code}")
def shop_json(code: str, db: Session = Depends(get_db)) -> dict[str, object]:
    return transparency.page_data(db, _shop(db, code))


@router.get("/shop/{code}/report/{month}", response_model=None)
def shop_report(code: str, month: str, db: Session = Depends(get_db)) -> Response:
    as_csv = month.endswith(".csv")
    month = month.removesuffix(".csv")
    if not MONTH_RE.match(month):
        raise HTTPException(400, "month must look like 2026-11")
    shop = _shop(db, code)
    if as_csv:
        return Response(
            transparency.report_csv(db, shop, month),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="shop-{code}-{month}.csv"'},
        )
    return HTMLResponse(transparency.render_report(db, shop, month))
