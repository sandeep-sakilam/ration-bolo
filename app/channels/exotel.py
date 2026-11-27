"""Indian telephony (Exotel) behind the same Messenger interface as Twilio.

Stub for the move to a real Indian toll-free number: outbound reminder calls and SMS
through Exotel's REST API. Off unless TELEPHONY_PROVIDER=exotel and the Exotel keys
are set. Before switching it on, check the current Exotel docs (endpoints, the call
flow ID for spoken reminders, DLT template IDs for SMS) and log the values in
DECISIONS.md. Inbound calls on an ExoPhone need an Exotel call flow (Passthru /
Programmable Connect) pointed at this app; that wiring is not built yet.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from app.channels.messaging import record
from app.models import Outbox

log = logging.getLogger("ration_bolo.exotel")


class ExotelMessenger:
    name = "exotel"

    def __init__(
        self,
        sid: str,
        api_key: str,
        api_token: str,
        caller_id: str,
        subdomain: str = "api.in.exotel.com",
        flow_url: str = "",
        dlt_entity_id: str = "",
        dlt_template_id: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        self.sid, self.caller_id, self.flow_url = sid, caller_id, flow_url
        self.base = f"https://{subdomain}/v1/Accounts/{sid}"
        self.auth = (api_key, api_token)
        self.dlt = {"DltEntityId": dlt_entity_id, "DltTemplateId": dlt_template_id}
        self.client = client or httpx.Client(timeout=10)

    def _post(
        self, db: Session, channel: str, path: str, data: dict[str, str], to: str, body: str
    ) -> Outbox:
        try:
            resp = self.client.post(self.base + path, data=data, auth=self.auth)
            resp.raise_for_status()
            status = "sent"
        except httpx.HTTPError as exc:
            log.warning("exotel %s failed: %s", channel, type(exc).__name__)
            status = "failed"
        return record(db, channel, to, body, status)

    def send_sms(self, db: Session, to: str, body: str) -> Outbox:
        data = {"From": self.caller_id, "To": to, "Body": body}
        data.update({k: v for k, v in self.dlt.items() if v})
        return self._post(db, "sms", "/Sms/send.json", data, to, body)

    def send_whatsapp(
        self, db: Session, to: str, body: str, media_url: str | None = None
    ) -> Outbox:
        # Exotel WhatsApp needs approved templates; fall back to SMS for now.
        return self.send_sms(db, to.removeprefix("whatsapp:"), body)

    def place_call(self, db: Session, to: str, say: str, language: str) -> Outbox:
        if not self.flow_url:
            return record(db, "call", to, say + " [exotel: no call flow configured]", "failed")
        data = {
            "From": to,
            "CallerId": self.caller_id,
            "Url": self.flow_url,
            "CustomField": say[:500],
        }
        return self._post(db, "call", "/Calls/connect.json", data, to, say)
