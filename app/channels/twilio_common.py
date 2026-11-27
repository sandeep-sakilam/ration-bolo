"""Shared Twilio webhook helpers: signature check, rate limits, sessions by call."""

from __future__ import annotations

from fastapi import HTTPException, Request
from twilio.request_validator import RequestValidator

from app.config import Settings
from app.ratelimit import RateLimiter

PHONE_LIMIT = RateLimiter(limit=40, window_seconds=60)
IP_LIMIT = RateLimiter(limit=120, window_seconds=60)


async def verified_form(request: Request) -> dict[str, str]:
    """The webhook's form fields. When Twilio keys are set, the X-Twilio-Signature must
    match (computed over PUBLIC_BASE_URL + path); unsigned requests are rejected."""
    form = {k: str(v) for k, v in (await request.form()).items()}
    settings: Settings = request.app.state.settings
    if settings.twilio_auth_token:
        base = settings.public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
        url = base + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        signature = request.headers.get("X-Twilio-Signature", "")
        if not RequestValidator(settings.twilio_auth_token).validate(url, form, signature):
            raise HTTPException(403, "invalid Twilio signature")
    ip = request.client.host if request.client else ""
    IP_LIMIT.check(f"ip:{ip}")
    PHONE_LIMIT.check(f"phone:{form.get('From', '')}")
    return form


def public_url(request: Request, path: str) -> str:
    settings: Settings = request.app.state.settings
    base = settings.public_base_url.rstrip("/") or str(request.base_url).rstrip("/")
    return base + path
