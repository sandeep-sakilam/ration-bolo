# Round 2 submission checklist

Submit **early on 30 Nov 2026** (afternoon), not at 11:59 PM IST: the form can be submitted
only once, automatic checks run about a minute after Submit, a failed check returns it to
draft by email, and an unsubmitted draft is submitted automatically at the deadline.

| # | Rule | How to verify | Done |
| --- | --- | --- | --- |
| 1 | GitHub repo is **public** (and stays public until Round 2 results / Round 3) | Open https://github.com/sandeep-sakilam/ration-bolo in a private browser window | ☐ |
| 2 | One-command start with **no `.env` and no real keys** | `scripts/check_fresh_clone.sh` → `PASS …` (also the `fresh-clone` CI job on `main`) | ☐ |
| 3 | Main screen works keyless; missing keys say "key not set" | Open http://localhost:8000 after `docker compose up`; the banner says "key not set" | ☐ |
| 4 | `.env.example` lists every variable with placeholders | `grep -c '^# [A-Z_]*=' .env.example`; every setting in `app/config.py` appears there | ☐ |
| 5 | No `.env` or secret committed | `git ls-files | grep -E '(^|/)\.env$'` prints nothing; GitHub secret scanning shows no alerts | ☐ |
| 6 | 300+ lines written during the hackathon | `make loc` (about 5,000 lines of application code) | ☐ |
| 7 | CI green on `main` | GitHub → Actions → latest run on `main` is green (check, postgres, fresh-clone) | ☐ |
| 8 | Demo video on **YouTube only**, public or **unlisted**, **≤ 3:00**, shows a **live voice interaction** | Open the link logged out; check the duration; follow `docs/DEMO_SCRIPT.md` | ☐ |
| 9 | Deck PDF **≤ 30 pages and ≤ 10 MB**, key points as text, FAQ headings (Addressable market; Third-party dependencies: cost and availability risks; Go-to-market plan; tech stack and why) | `python scripts/build_deck.py --video <url> --live <url>` prints pages and size and fails if over the limits | ☐ |
| 10 | Live link (optional bonus): public URL, **no login wall**, reachable until at least **2 Dec 2026** | `scripts/smoke_deploy.sh <url>` shows `/api/dealer/overview open (no login wall)`; `DEALER_PIN`/`ADMIN_PIN` unset on Railway | ☐ |
| 11 | Live link shows **the same prototype as the repo** | The footer and `<url>/health` show the same short commit as the latest commit on `main` | ☐ |
| 12 | Demo state is fresh for each judge | `DEMO_MODE` unset or `auto` on Railway (fresh callers, 10-minute status restore, nightly reset); press **Reset demo** after recording the video | ☐ |
| 13 | Voice-first: end users give input by voice, one core flow end to end | Simulator mic (browser speech, or Wispr when keyed) → stock, queue, booking | ☐ |
| 14 | Real speech keys work (if used on the live link) | `python scripts/smoke_real.py` prints PASS for each keyed service | ☐ |
| 15 | Version 3 deck slide "Works without a partner: three levels" present; demo video shows the Level 0 path | `docs/deck.html` slide 12; `docs/DEMO_SCRIPT.md` 1:30–2:22 | ☐ |
| 16 | Optional real-world settings for version 3 (helpline number, district contact, public PDS URL/format, check-in number) filled in only once confirmed | `/api/status` lists the public PDS and check-in lines; with nothing set the app says so and falls back | ☐ |
| 17 | Submit by the afternoon of 30 Nov; watch email for a "returned to draft" message | — | ☐ |
