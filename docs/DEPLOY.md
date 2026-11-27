# Deploying Ration Bolo

The app is one Docker container (FastAPI + in-process scheduler) and an optional
PostgreSQL database. It runs on any Docker host; Railway is the documented choice
because Twilio needs an always-on public HTTPS address (calls fail if the server sleeps).

Nothing here is needed for the keyless demo: `docker compose up` on any machine is enough.

## 1. Railway (live link)

1. Create a Railway account and a **New Project → Deploy from GitHub repo →
   `sandeep-sakilam/ration-bolo`**. Railway finds `railway.json` and builds the
   `Dockerfile` (python:3.12-slim + ffmpeg). It sets `PORT`; the container listens on it.
2. In the project, **New → Database → PostgreSQL**. Then in the app service's
   **Variables**, add a reference variable `DATABASE_URL = ${{Postgres.DATABASE_URL}}`.
   (`postgres://` and `postgresql://` URLs are both accepted.) Without it the app uses
   SQLite inside the container, which is lost on every redeploy.
3. **Settings → Networking → Generate Domain**. Copy the `https://….up.railway.app` URL.
4. Add variables (all optional; each one turns a mock into the real service):

   | Variable | Value |
   | --- | --- |
   | `PUBLIC_BASE_URL` | the Railway domain, e.g. `https://ration-bolo.up.railway.app` |
   | `DEALER_PIN`, `ADMIN_PIN` | leave **unset** during evaluation: the live link must have no login wall. Set them only for real production use. |
   | `WISPR_API_KEY` | Wispr Flow API key |
   | `SARVAM_API_KEY` | Sarvam AI key (backup speech-to-text and reply voice) |
   | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Twilio console → Account info |
   | `TWILIO_VOICE_NUMBER` | the number you bought, `+1…` |
   | `TWILIO_SMS_NUMBER` | usually the same number |
   | `TWILIO_WHATSAPP_NUMBER` | sandbox sender, `whatsapp:+14155238886` |

5. Keep **one replica** (`railway.json` sets `numReplicas: 1`): the reminder scheduler
   and rate limits live in the process.
6. Redeploys never wipe data: demo data is seeded only into an empty database.
   "Reset demo" on the dealer dashboard restores it on demand.
7. Check it: `scripts/smoke_deploy.sh https://your-domain` prints each service's state.
8. Optional: with `SARVAM_API_KEY` set, run `python scripts/generate_prompts.py` once
   (Railway → service → **Shell**) to pre-generate the fixed prompts' audio.

## 2. Twilio console

Calls and messages cost money and the trial account can only reach verified numbers.

1. **Leave trial mode**: Billing → upgrade / top up.
2. **Buy a number**: Phone Numbers → Manage → Buy a number → a US local number with
   Voice (and SMS). Indian local numbers are not sold for this use; Indian toll-free
   numbers must be answered outside India and can't call out.
3. **Allow calls to India**: Voice → Settings → Geo permissions → enable **India**
   (needed for outbound reminder calls).
4. **Voice webhooks**: Phone Numbers → your number → Voice configuration:
   - *A call comes in*: Webhook, `https://<domain>/twilio/voice`, HTTP POST
   - *Call status changes*: `https://<domain>/twilio/voice/status`, HTTP POST
5. **WhatsApp sandbox**: Messaging → Try it out → Send a WhatsApp message. Join it from
   each test phone by sending the shown `join <code>` message to +1 415 523 8886.
   In **Sandbox settings**, set *When a message comes in* to
   `https://<domain>/twilio/whatsapp`, HTTP POST.
6. Webhook signatures are checked whenever `TWILIO_AUTH_TOKEN` is set, using
   `PUBLIC_BASE_URL`, so the URL configured in Twilio must start with exactly that value.
7. **SMS to India** from a foreign number may not be delivered without DLT
   registration. Booking confirmations go on WhatsApp to WhatsApp users; every send,
   delivered or not, is listed in the dealer dashboard's outbox.

To have your own phone recognised as a demo caller, open the dealer dashboard →
*Tester tools* → *Link my phone to a demo card*.

## 3. Local tunnelling (test Twilio without deploying)

```bash
docker compose up
```

In a second terminal, expose port 8000 with any HTTPS tunnel, for example:

```bash
cloudflared tunnel --url http://localhost:8000
```

or

```bash
ngrok http 8000
```

Put the tunnel's `https://…` URL in `.env` as `PUBLIC_BASE_URL` (with your Twilio
keys), restart with `docker compose up`, and point the Twilio webhooks above at the
tunnel URL. Tunnel URLs change on every start; update `PUBLIC_BASE_URL` and the
Twilio console together.

## 4. PostgreSQL locally (optional)

```bash
docker compose --profile postgres up -d postgres
```

Then set `DATABASE_URL=postgresql+psycopg://ration:ration@postgres:5432/ration_bolo`
in `.env` and run `docker compose up`.

## 5. Costs and limits

- One speech-to-text request per caller sentence; rules run on our own server.
- Reply audio is cached by text, so repeated prompts cost nothing after the first time.
- Every provider sits behind an interface and an environment variable; removing a key
  falls back to the next option (Wispr → Sarvam → keypad/menu; Sarvam voice → Twilio `<Say>`).

## 6. Moving to an Indian toll-free number (Exotel stub)

`app/channels/exotel.py` implements the same messaging interface as Twilio for outbound
reminder calls and SMS. To try it: set `TELEPHONY_PROVIDER=exotel` and the `EXOTEL_*`
variables listed in `.env.example` (an ExoPhone as caller ID, a call-flow URL for spoken
reminders, and DLT entity/template IDs for SMS to India). Check Exotel's current API
docs first. Inbound calls on the ExoPhone still need an Exotel call flow pointed at this
app; until then keep Twilio for inbound.
