# Progress

Current: version 3.2 complete (F46 merged); UI refresh merged

## Functionality backlog

Submission build (F01–F17, merge by 30 Nov 2026, 6:00 PM IST):

- [x] F01 Foundation: repo layout, FastAPI skeleton, Dockerfile, docker-compose, Makefile, CI, health — `feat/f01-foundation`
- [x] F02 Data model, SQLite/PostgreSQL, demo seed, reset — `feat/f02-data-model`
- [x] F03 State packs: format, schema, loader, Telangana — `feat/f03-state-packs`
- [x] F04 Slot and queue engine — `feat/f04-slot-engine`
- [x] F05 Speech understanding — `feat/f05-understanding`
- [x] F06 Dialogue engine — `feat/f06-dialogue`
- [x] F07 Adapter interfaces, mocks, service status — `feat/f07-adapters`
- [x] F08 Speech pipeline — `feat/f08-speech-pipeline`
- [x] F09 Call simulator — `feat/f09-simulator`
- [x] F10 Dealer dashboard — `feat/f10-dealer-dashboard`
- [x] F11 Reminders and outbox — `feat/f11-reminders`
- [x] F12 Twilio Voice channel — `feat/f12-voice-channel`
- [x] F13 Twilio WhatsApp channel — `feat/f13-whatsapp`
- [x] F14 Impact metrics page — `feat/f14-metrics`
- [x] F15 Acceptance suite — `feat/f15-acceptance`
- [x] F16 Railway deployment — `feat/f16-deploy`
- [x] F17 Submission pack — `feat/f17-submission-pack`

Finale:

- [x] F18 Second state pack (Tamil Nadu, draft) — `feat/f18-second-pack`
- [x] F19 Phone-to-card link verification — `feat/f19-link-verification`
- [x] F20 Indian telephony adapter stub (Exotel) — `feat/f20-indian-telephony`
- [x] F21 Accessibility and low-bandwidth audit — `feat/f21-accessibility`
- [x] F22 Multi-shop admin and CSV import — `feat/f22-multi-shop`

Version 2 submission fixes (F23–F28, merge by 30 Nov 2026, 12:00 noon IST):

- [x] F23 Shared live demo safety: fresh demo callers, auto-restoring status toggles, nightly reset — `feat/f23-shared-demo`
- [x] F24 No login wall: dealer and admin pages open when no PIN is set — `feat/f24-no-login-wall`
- [x] F25 Build identity (commit SHA) and submission checklist — `feat/f25-submission-checklist`
- [x] F26 Real-adapter smoke script (run by hand, never in CI) — `feat/f26-real-smoke`
- [x] F27 Deck refresh: FAQ headings, finale features, live numbers, PDF limit checks — `feat/f27-deck-refresh`
- [x] F28 Demo video script v2 with a live voice interaction — `feat/f28-demo-script-v2`

Version 3 "works without a partner" (F29–F39, merge by 30 Nov 2026, 12:00 noon IST; `main` shippable after each):

- [x] F29 Deck slide "Works without a partner: three levels" + Risks text, rebuilt PDF — `feat/f29-deck-three-levels`
- [x] F30 Shop levels 0, 1, 2: capabilities, honest wording, level on dashboard/admin, v3 demo shops — `feat/f30-shop-levels`
- [x] F31 Cardholder reports and check-ins, agreement and decay model — `feat/f31-crowd-reports`
- [x] F32 Public PDS data adapter, polling and signals — `feat/f32-public-pds`
- [x] F33 Best-time advice from hourly crowd profiles — `feat/f33-best-time`
- [x] F34 Nearby-shop portability (ONORC) — `feat/f34-nearby-shops`
- [x] F35 Official complaint routing and escalation — `feat/f35-grievance-routing`
- [x] F36 Public transparency page and monthly report — `feat/f36-transparency`
- [x] F37 Dealer incentives: dealer phone line, "Rice arrived" broadcast, "Fair shop" badge — `feat/f37-dealer-incentives`
- [x] F38 Volunteer queue coordinator mode — `feat/f38-volunteer-mode`
- [x] F39 Version 3 docs, metrics for reports and levels, rebuilt PDF — `feat/f39-v3-docs`

Version 3.1 "voice polish" (F40–F45, merge by 30 Nov 2026, 10:00 AM IST; `main` shippable after each):

- [x] F40 Demo public sales stay fresh relative to now and open hours; no false "possibly stopped" — `feat/f40-fresh-demo-sales`
- [x] F41 Natural spoken times in advice (part-of-day phrases from the state pack) — `feat/f41-spoken-times`
- [x] F42 Advice honours the day and part of day asked for; prefers today's remaining hours — `feat/f42-advice-context`
- [x] F43 Shorter replies: one status warning per call, one advice sentence, length budget — `feat/f43-shorter-replies`
- [x] F44 Nearby shop gives today's wait ("go now" / today's best time / tomorrow) — `feat/f44-nearby-today`
- [x] F45 Version 3.1 docs: demo script phrases, README, acceptance map, deck only if quoted text changed — `feat/f45-v31-docs`

Version 3.2 "closed-shop honesty" (F46, merge by 29 Nov 2026, 6:00 PM IST):

- [x] F46 Closed-shop honesty: nearby offers and status answers respect open hours; demo reports keep their real age outside open hours — `feat/f46-closed-shop-honesty`

Outside the spec backlog (requested by Sandeep, 28 Nov 2026):

- [x] UI refresh: modern styling for every page (design tokens, dark theme, no inline styles), no behaviour change — `feat/ui-refresh`
