"""Real-adapter smoke check (F26). For Sandeep to run by hand with real keys.

Never runs in CI or tests. Reads `.env` like the app does and, for each service whose
keys are set:
  * Wispr Flow  – transcribes tests/fixtures/biyyam_vachaya_te.wav and prints the text
  * Sarvam STT  – transcribes the same clip
  * Sarvam TTS  – asks for one Telugu reply and saves it to data/smoke_reply_te.wav
  * Twilio      – checks the credentials and that the voice / SMS / WhatsApp numbers exist
                  on the account. It never places a call and never sends a message.
Prints a PASS / FAIL / SKIP table with the exact error for each failure.

Usage:  python scripts/smoke_real.py            (all services with keys)
        python scripts/smoke_real.py --clip my_recording.wav
Each speech request costs a tiny amount on your provider accounts.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.packs import get_pack  # noqa: E402
from app.speech.audio import to_wav16k  # noqa: E402
from app.speech.stt import SarvamSTT, WisprSTT  # noqa: E402
from app.speech.tts import SarvamTTS  # noqa: E402

DEFAULT_CLIP = ROOT / "tests" / "fixtures" / "biyyam_vachaya_te.wav"
SANDBOX_WHATSAPP = "+14155238886"

Row = tuple[str, str, str]  # (check, PASS|FAIL|SKIP, detail)


def check_wispr(s: Settings, wav: bytes) -> Row:
    if not s.wispr_api_key:
        return ("Wispr Flow speech-to-text", "SKIP", "WISPR_API_KEY not set")
    stt = WisprSTT(s.wispr_api_key, s.wispr_base_url, timeout=max(15.0, s.speech_timeout_seconds))
    hints = get_pack(s.default_state_pack).speech_hints("wispr")
    out = stt.transcribe(wav, hints)
    if out.ok:
        return ("Wispr Flow speech-to-text", "PASS", f"heard: {out.text!r} ({out.language})")
    return (
        "Wispr Flow speech-to-text",
        "FAIL",
        f"{out.error or 'empty transcript'} · URL {s.wispr_base_url}/api",
    )


def check_sarvam_stt(s: Settings, wav: bytes) -> Row:
    if not s.sarvam_api_key:
        return ("Sarvam speech-to-text", "SKIP", "SARVAM_API_KEY not set")
    stt = SarvamSTT(
        s.sarvam_api_key,
        s.sarvam_base_url,
        s.sarvam_stt_model,
        timeout=max(15.0, s.speech_timeout_seconds),
    )
    out = stt.transcribe(wav, ["te-IN"])
    if out.ok:
        return ("Sarvam speech-to-text", "PASS", f"heard: {out.text!r} ({out.language})")
    return (
        "Sarvam speech-to-text",
        "FAIL",
        f"{out.error or 'empty transcript'} · model {s.sarvam_stt_model}",
    )


def check_sarvam_tts(s: Settings) -> Row:
    if not s.sarvam_api_key:
        return ("Sarvam reply voice (Bulbul)", "SKIP", "SARVAM_API_KEY not set")
    tts = SarvamTTS(
        s.sarvam_api_key,
        s.sarvam_base_url,
        s.sarvam_tts_model,
        s.sarvam_tts_speaker,
        timeout=max(15.0, s.speech_timeout_seconds),
    )
    text = get_pack("telangana").phrase("how_help", "te")
    audio = tts.synthesize(text, "te-IN")
    if not audio:
        return (
            "Sarvam reply voice (Bulbul)",
            "FAIL",
            f"{tts.last_error or 'no audio'} · model {s.sarvam_tts_model}, "
            f"speaker {s.sarvam_tts_speaker}",
        )
    out = ROOT / "data" / "smoke_reply_te.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    return ("Sarvam reply voice (Bulbul)", "PASS", f"{len(audio)} bytes → {out.relative_to(ROOT)}")


def check_twilio(s: Settings) -> list[Row]:
    if not (s.twilio_account_sid and s.twilio_auth_token):
        return [("Twilio credentials", "SKIP", "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set")]
    from twilio.base.exceptions import TwilioException
    from twilio.rest import Client

    client = Client(s.twilio_account_sid, s.twilio_auth_token)
    rows: list[Row] = []
    try:
        account = client.api.v2010.accounts(s.twilio_account_sid).fetch()
        detail = f"account status {account.status}, type {account.type}"
        state = "PASS" if account.status == "active" else "FAIL"
        if account.type == "Trial":
            detail += " (trial: calls only reach verified numbers; top up to leave trial)"
        rows.append(("Twilio credentials", state, detail))
    except TwilioException as exc:
        return [("Twilio credentials", "FAIL", str(exc)[:300])]

    def owned(number: str) -> Row | None:
        try:
            found = client.incoming_phone_numbers.list(phone_number=number, limit=1)
        except TwilioException as exc:
            return ("", "FAIL", str(exc)[:300])
        if not found:
            return ("", "FAIL", f"{number} is not a number on this account")
        caps = found[0].capabilities or {}
        return ("", "PASS", f"{number} owned · voice={caps.get('voice')} sms={caps.get('sms')}")

    for label, number in [
        ("Twilio voice number", s.twilio_voice_number),
        ("Twilio SMS number", s.twilio_sms_number),
    ]:
        if not number:
            rows.append((label, "SKIP", "not set"))
            continue
        row = owned(number)
        assert row is not None
        rows.append((label, row[1], row[2]))
    wa = s.twilio_whatsapp_number.removeprefix("whatsapp:")
    if not wa:
        rows.append(("Twilio WhatsApp sender", "SKIP", "TWILIO_WHATSAPP_NUMBER not set"))
    elif wa == SANDBOX_WHATSAPP:
        rows.append(
            (
                "Twilio WhatsApp sender",
                "PASS",
                "sandbox sender; join it from each test phone (join <code>)",
            )
        )
    else:
        row = owned(wa)
        assert row is not None
        rows.append(("Twilio WhatsApp sender", row[1], row[2]))
    if s.public_base_url:
        rows.append(
            (
                "PUBLIC_BASE_URL",
                "PASS",
                f"webhooks: {s.public_base_url.rstrip('/')}/twilio/voice and /twilio/whatsapp",
            )
        )
    else:
        rows.append(
            ("PUBLIC_BASE_URL", "FAIL", "not set: phone and WhatsApp need a public HTTPS URL")
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clip", type=Path, default=DEFAULT_CLIP, help="audio clip to transcribe")
    args = parser.parse_args(argv)
    settings = Settings()  # reads .env
    try:
        wav = to_wav16k(args.clip.read_bytes())
    except Exception as exc:
        print(f"Cannot read clip {args.clip}: {exc}")
        return 2
    checks: list[Callable[[], list[Row]]] = [
        lambda: [check_wispr(settings, wav)],
        lambda: [check_sarvam_stt(settings, wav)],
        lambda: [check_sarvam_tts(settings)],
        lambda: check_twilio(settings),
    ]
    rows: list[Row] = []
    for check in checks:
        try:
            rows.extend(check())
        except Exception as exc:  # never crash the table
            rows.append(("(unexpected error)", "FAIL", f"{type(exc).__name__}: {exc}"[:300]))
    width = max(len(r[0]) for r in rows)
    print(f"\nRation Bolo real-adapter smoke check · clip {args.clip.name}\n")
    for name, state, detail in rows:
        print(f"{state:<5} {name:<{width}}  {detail}")
    failed = [r for r in rows if r[1] == "FAIL"]
    print(f"\n{len(rows) - len(failed)} ok/skipped, {len(failed)} failed.")
    if failed:
        print(
            "Fix the key, URL or model named above (see .env.example and docs/DEPLOY.md), "
            "then run this again."
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
