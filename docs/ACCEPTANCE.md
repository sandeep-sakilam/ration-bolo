# Acceptance checks ("Done when")

| # | Check (SPEC) | Proven by |
| --- | --- | --- |
| 1 | Fresh clone, no `.env`: `docker compose up` starts, simulator loads, status says "key not set" | `scripts/check_fresh_clone.sh` (CI job `fresh-clone`), `tests/e2e/test_simulator.py::test_simulator_loads_with_key_not_set_banner` |
| 2 | Lakshmi: confirm 0421, stock 24 kg, 18 ahead / 36 min, book tomorrow 10:20, all by speech (text box) | `tests/e2e/test_acceptance.py::test_check2_lakshmi_books_by_speech` |
| 3 | Same booking through the WhatsApp channel handler (mock adapter) | `tests/test_acceptance.py::test_check3_…`, `tests/test_whatsapp.py`, `tests/e2e/test_acceptance.py::test_check3_…` |
| 4 | Machine down → booking refused on every channel, status heard first | `tests/e2e/test_acceptance.py::test_check4_…`, `tests/test_acceptance.py::test_check4_…`, `tests/test_voice.py` |
| 5 | Two failures → backup engine; third → fallback menu | `tests/e2e/test_acceptance.py::test_check5_…`, `tests/test_dialogue.py::test_failures_switch_engine_then_menu` |
| 6 | Booked family arriving 11 minutes late moves to the walk-in line | `tests/e2e/test_acceptance.py::test_check6_…`, `tests/test_queue.py::test_arrival_11_minutes_late_joins_walkins` |
| 7 | "Naaku 15 kilolu ichharu" files a complaint with an ID; "24 kilolu" files nothing | `tests/e2e/test_acceptance.py::test_check7_…`, `tests/test_dialogue.py` |
| 8 | Unknown number registers by digits and is recognised next call; two-card phone is asked which | `tests/e2e/test_acceptance.py::test_check8_…`, `tests/test_dialogue.py` |
| 9 | Full suite passes on SQLite and PostgreSQL | `make check`, `make test-pg`, `make e2e-pg` (CI job `postgres`) |
| 11 | Two Lakshmi calls in a row: the second hears Telugu and is offered 10:20 again | `tests/test_shared_demo.py::test_check11_…`, `tests/e2e/test_acceptance.py::test_check11_…` |
| 12 | "Machine down" in demo mode is normal again after 10 minutes | `tests/test_shared_demo.py::test_check12_…` |
| 13 | No `DEALER_PIN`/`ADMIN_PIN`: dealer and admin pages work without a PIN; with them set, a wrong PIN is refused | `tests/test_dealer.py::test_check13_…`, `test_pin_required_when_set`, `tests/e2e/test_acceptance.py::test_check13_…`, `scripts/check_fresh_clone.sh` |
| 14 | `/health` and every footer show the commit the app was built from | `tests/test_buildinfo.py::test_check14_…`, `tests/e2e/test_acceptance.py::test_check14_…`, `scripts/check_fresh_clone.sh` |
| 10 | More than 300 lines of application code | `scripts/count_loc.py` (`make loc`), `tests/test_acceptance.py::test_check10_…` |
| 15 | Level 0: "book" gives best-time advice with the honest reason and creates no booking; Level 1/2 book as before | `tests/test_levels.py::test_check15_…`, `test_level1_and_2_book_as_before` |
| 16 | Two phones within 45 minutes confirm "rice arrived" (spoken with source and age); one report is "one person"; older than 3 hours ignored; 3× queue outlier dropped | `tests/test_crowd.py::test_check16_…`, `test_queue_outlier_dropped_and_checkins_count` |
| 17 | Public PDS mock "selling since 9:10" gives a Level 0 status; a failing source keeps calls working and shows "unavailable" | `tests/test_public_pds.py::test_check17_…` |
| 18 | Fewer than 20 data points → the pack's default pattern, spoken with "usually" | `tests/test_besttime.py::test_check18_…` |
| 19 | Shop 108 "Machine down" → Lakshmi offered Shop 112 with distance, landmark and wait; yes → Shop 112's best time, no booking | `tests/test_nearby.py::test_check19_…` |
| 20 | Unresolved 7 days → reminder and district escalation offer; helpline never dialled in tests; reference read back and stored | `tests/test_grievance.py::test_check20_…`, `test_reference_number_read_back_and_stored`, `test_helpline_handoff_only_after_yes_as_twiml` |
| 21 | `/shop/112` has no login, no names, phones or card numbers, "fewer than 5" for small counts; monthly CSV downloads | `tests/test_transparency.py::test_check21_…`, `tests/e2e/test_acceptance.py::test_check21_…` |
| 22 | Dealer phone presses 1 → stock arrived; opted-in cardholders get exactly one "rice arrived" message that day | `tests/test_incentives.py::test_check22_…`, `tests/e2e/test_acceptance.py::test_check22_…` |
| 23 | Volunteer on duty at Shop 109: tokens and bookings; off duty: Level 0 | `tests/test_volunteers.py::test_check23_…`, `tests/e2e/test_acceptance.py::test_check23_…` |
| 24 | All Shop 108 checks 1–14 still pass unchanged | the whole suite above, unchanged assertions for checks 1–14 |

Run everything locally:

```bash
make check          # lint, format, types, unit tests (SQLite)
make e2e            # browser flows
make test-pg        # unit tests on PostgreSQL (needs a server; see Makefile for the URL)
make fresh-clone-check
```
