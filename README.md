# Ration Bolo — voice-first ration shop assistant

Ration cardholders check stock, hear the live queue, book a time slot and report short
rations at their ration shop **by speaking**, on a phone call or a WhatsApp voice note.
No app, no reading, no typing. Built for Round 2 of the Scaler × Wispr Flow
"Build for Bharat" hackathon (theme: Public infrastructure and civic services).

About 80 crore people collect grain every month from about 5.5 lakh ration shops under
the National Food Security Act. Families arrive early, wait for hours and are often told
"come tomorrow". Ration Bolo turns that into one phone call and a time slot.

## Judge quickstart (no keys needed)

```bash
git clone https://github.com/sandeep-sakilam/ration-bolo
```

```bash
cd ration-bolo && docker compose up
```

Open **http://localhost:8000** — the call simulator. Everything you see is labelled **Demo data**.

1. Caller **Lakshmi**, press **Start call**. The app says *"Namaskaram, Ration Bolo. Card chivari ankelu 0421, sare na?"* (card ending 0421, right?). It never says a name.
2. Tap the mic and speak (Chrome/Edge use the browser's own speech recognition when no
   speech keys are set), or type, or tap an example phrase:
   - *Avunu* (yes) → *"Meeku ela sahayam cheyali?"* (how can I help?)
   - *Maa shop ki biyyam vachaya?* (has rice come?) → *24 kilolu* for her family of 4
   - *Ippudu entha mandi unnaru?* (how many now?) → *18 ahead, about 36 minutes*
   - *Repu poddhuna book cheyyandi* (book tomorrow morning) → *Repu 10:20 ki, sare na?* → *Avunu* → token **B-036**
   - *Naaku 15 kilolu ichharu* (I got 15 kg) → read back → *Avunu* → complaint **C-108-0003**
3. Try **Salma** for Hindi (*Kitne log hain?*, *Kal subah book karo*, *Mujhe kam mila*),
   **Unknown number** to register a card by digits (*1 0 8 0 4 2 1*), the **Family phone**
   with two cards, the **WhatsApp voice note** mode, the **keypad**, and saying nonsense
   three times to see the engine switch and the fallback menu. **Meena** uses the draft
   Tamil Nadu pack (*Arisi vanthucha?*, *Naalai kaalai book pannunga*) — a new state is a new file.
4. Open **Dealer dashboard** (PIN **1234**): live queue, *Serve next*, walk-in tokens,
   *Machine down* (booking pauses on every channel), voice updates (*"Biyyam aipoyindi"*),
   complaints, the outbox of every SMS / WhatsApp / reminder call, *Send reminder now*, *Reset demo*.
5. Open **Impact metrics** for wait times, adoption, voice success rate, engine usage and complaints.

A banner on the simulator lists which services are live and which keys are **not set**
(the same data is at `/api/status`). Every outside service falls back: no speech keys →
browser speech; no Twilio keys → messages go to the dashboard's outbox.

## How it works

- **Voice is the product.** Phone call (any basic phone), WhatsApp voice notes, or the
  web simulator — all three are thin wrappers around one dialogue engine.
- **Speech engines hear, rules decide.** Wispr Flow (primary) or Sarvam AI (backup) only
  turn audio into text. Intent, booking, wait time and complaints are deterministic,
  tested code using keyword and fuzzy matching. No LLM makes decisions.
- **Never strand the caller.** Ask again → switch speech engine after two failures →
  keypad / numbered menu after a third → end politely with a text summary.
- **Confirm before saving.** Card digits, kilos and times are read back; nothing is saved without a yes.
- **Walk-ins are never turned away.** Each 20-minute window keeps half its places for walk-ins;
  the dealer serves booked and walk-in families alternately.
- **Private by default.** Names are never spoken; cards are confirmed by last digits; phones are masked;
  caller audio is deleted after transcription.
- **Every state is configuration.** Languages, phrases, keywords and entitlements live in
  `packs/<state>.json`, validated at startup.

```
Phone call ─► Twilio Voice ─┐
WhatsApp ───► Twilio WA ────┼─► Speech pipeline (Wispr → Sarvam → fallback) ─► Dialogue engine (rules)
Simulator ──► Web + API ────┘                                                   ├─ Slot & queue engine
Dealer ─────► Dashboard ──────────────────────────────────────────────────────── ├─ Complaints
                                                                                 └─ Reminders (scheduler)
                        SQLite locally · PostgreSQL on Railway
```

## Tech stack (and why)

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.12 | Strong libraries for Twilio, audio and APIs |
| Web | FastAPI, Uvicorn, Pydantic v2 | Webhooks, JSON API and pages from one typed app |
| Pages | Plain HTML, CSS, JavaScript | No build step for judges; light on cheap phones |
| Database | SQLAlchemy 2; SQLite default, PostgreSQL via `DATABASE_URL` | Zero-setup local start; production database by one setting |
| Speech-to-text | Wispr Flow API, Sarvam AI backup, browser Web Speech API with no keys | Hackathon partner's engine; Indian-language backup; keyless demo |
| Reply voice | Sarvam Bulbul (cached), Twilio `<Say>`, browser speech synthesis | Natural Indian voices with free fallbacks |
| Audio | ffmpeg | WebM, OGG/Opus and 8 kHz calls → 16 kHz WAV |
| Understanding | rapidfuzz keyword matching | Accent and spelling variation, fully deterministic |
| Phone & WhatsApp | Twilio Voice, WhatsApp sandbox, SMS | Working phone line and WhatsApp in days; Indian provider later |
| Scheduling | APScheduler in-process, reminders in the database | No separate worker; survives restarts |
| Quality | ruff, mypy, pytest, Playwright; GitHub Actions | Lint, types, 147 unit tests, browser flows, PostgreSQL and fresh-clone CI |
| Hosting | Docker, Railway | One command locally; always-on HTTPS for Twilio |

## Configuration

Copy `.env.example` to `.env` and fill in only what you have. All keys are optional.
`docs/DEPLOY.md` covers Railway, the Twilio console and local tunnelling.

## Development

```bash
make install        # dev dependencies into the current Python
make check          # ruff lint + format check, mypy, pytest
make e2e            # Playwright browser flows
make test-pg        # unit tests on PostgreSQL
make fresh-clone-check   # keyless docker compose start from a fresh clone
```

`docs/ACCEPTANCE.md` maps every "Done when" check to the tests that prove it.
`SPEC.md` is the specification; `PROGRESS.md` the build status; `DECISIONS.md` the decision log.

## Repository layout

```
app/            FastAPI app: dialogue.py, understanding.py, slots.py, queue.py, reminders.py,
                metrics.py, seed.py, packs.py, speech/ (stt, tts, audio, pipeline),
                channels/ (simulator, dealer, voice, whatsapp, messaging), static/ (pages)
packs/          telangana.json, schema.json
tests/          unit tests; tests/e2e/ Playwright flows
scripts/        check_fresh_clone.sh, build_deck.py, smoke_deploy.sh, generate_prompts.py, count_loc.py
docs/           DEPLOY.md, DEMO_SCRIPT.md, ACCEPTANCE.md, deck.html, Ration-Bolo-Deck.pdf
```

## Limits we state honestly

Production needs each state's Civil Supplies Department for card data and ePoS feeds
(the prototype simulates both and says so). The pilot number is a Twilio US number, not
yet an Indian toll-free number. SMS to India from a foreign number may not be delivered
without DLT registration. Speech accuracy for elderly callers, strong dialects and noisy
shops is unproven until piloted. The Telugu and Hindi phrases need checking by native speakers.

## What Sandeep must provide

- API keys: Wispr Flow API, Sarvam AI.
- Twilio: account top-up (leave trial mode), buy a US local voice number, enable India in voice geographic permissions, join the WhatsApp sandbox, set the webhook URLs.
- Railway: account, project from the GitHub repo, PostgreSQL service, environment variables, public domain.
- GitHub settings: keep the repo public, allow direct pushes to `main`, turn off the email-privacy push block, verify the email on the account.
- Checking the Telugu and Hindi phrases in the state pack with native speakers.
- Recording and uploading the demo video, exporting the final deck PDF, and the hackathon submission itself.
