# Decision log

One line per decision: date · question · choice · reason.

- 2026-11-27 · Uvicorn entry point · `uvicorn --factory app.main:create_app` · importing the module must not create a database; tests build their own app.
- 2026-11-27 · How to store window times · `windows.date` and `start_time` are IST wall-clock (shop schedule); every instant (issued, served, due) is naive UTC · a window is a schedule, not an instant, and India has no DST.
- 2026-11-27 · Timezone source · fixed UTC+05:30 offset instead of zoneinfo · slim images may lack tzdata; IST has no DST.
- 2026-11-27 · Demo "several cards" caller · added a fictional "Family phone" (+91 90000 09903) with cards TS-108-0610 and TS-108-0733 · acceptance check 8 needs a phone with two cards.
- 2026-11-27 · "08:00 to 10:00 fully booked" · the 10:00 window is included (7 windows × 5 bookings) · so the first free morning window is 10:20, as the spec's script says.
- 2026-11-27 · Metrics demo history · seed a week of fictional served tokens, sessions and two complaints · the spec asks for queue and metrics that look real.
- 2026-11-27 · Weights · stored as integer grams (`grams_due`, `grams_given`) · spec says weights in grams; column names say the unit.
- 2026-11-27 · Reply languages in the Telangana pack · Telugu and Hindi as specified, plus English as a third reply language · judges and testers who speak neither can follow the demo; Urdu still gets Hindi replies.
- 2026-11-27 · Native-script speech · keyword, yes/no, day and number lists include Telugu and Devanagari script forms next to romanised ones · real speech engines return native script; the romanised forms serve the text box and browser speech.
- 2026-11-27 · Intent ties · resolved by a pack-level `intent_priority` (complaint, book, queue, stock, end) · deterministic and per-state configurable.
- 2026-11-27 · Pack completeness · besides the JSON schema, the loader checks every reply language has every required phrase with the same placeholders, and that `state` matches the file name · a broken pack must stop startup with a clear error.
