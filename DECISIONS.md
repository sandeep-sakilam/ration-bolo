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
- 2026-11-27 · Late arrival bookkeeping · the booking is marked `late` and a new walk-in token (same card, waiting) is issued · keeps the history of the lost booking and puts the family in the walk-in line.
- 2026-11-27 · Which arrived booked families can be served · only those whose window has started · "Serve next" alternates within the current window; early arrivals wait for their window.
- 2026-11-27 · "One booking per month" month · the calendar month of the slot date; cancelled bookings don't count · a booking tomorrow on the 1st belongs to the new month.
- 2026-11-27 · Live "people ahead" for a reminder · booked families before it (earlier windows, or same window with a lower token) plus, because lines alternate, up to one walk-in for each of them and one more · gives the small, honest numbers the reminder script expects ("three are ahead").
- 2026-11-27 · Session words → hours · morning 08:00–12:00, evening 16:00–20:00 fixed IST ranges, as in the spec · shops with other hours still match by part of day.
- 2026-11-27 · Fuzzy matching of short words · words of 4 letters or fewer must match exactly; longer words use rapidfuzz ratio ≥ the pack threshold (82) · "kal" (tomorrow) must never be read as "kam" (less).
- 2026-11-27 · "Any number of kilos" · a number next to a kilo word adds 2 to the complaint score · so "Naaku 15 kilolu ichharu" is a complaint even without a complaint keyword.
- 2026-11-27 · Caller language detection · script (Telugu/Devanagari) first, else the language whose words matched most · used as a hint only; replies follow the card's saved language unless the caller asks to switch.
- 2026-11-27 · Caller asks a question instead of answering the card check · treated as "yes" and the question is answered · fewer turns for callers; nothing is saved by a card check.
- 2026-11-27 · Failure counting · consecutive failures (reset after an understood turn); the 2nd switches to the backup engine for the rest of the session, the 3rd shows the fallback menu in any state · matches "two failures → backup, one more → menu" and acceptance check 5.
- 2026-11-27 · Booking request with no day · a session word alone means tomorrow; "book" alone asks "which day, morning or evening?"; keypad 3 offers the first free window tomorrow · keypad callers can't say a day.
- 2026-11-27 · "No" at "anything else?" · ends the call politely with the summary · natural way to finish a call.
- 2026-11-27 · Picking among several cards · caller says the last digits or presses/says 1, 2, ...; no extra read-back · choosing is not saving, and the next answer reads the card's own data.
- 2026-11-27 · Text summary · sent at the end of a session only when something happened (booking, complaint) · avoids empty messages.
- 2026-11-27 · Long number words misheard ("padihaaru") · single-word fuzzy match ≥ 85 for words of 6+ letters, only when no exact match · speech engines spell Telugu numbers inconsistently.
