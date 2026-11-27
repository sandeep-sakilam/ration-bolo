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
| 10 | More than 300 lines of application code | `scripts/count_loc.py` (`make loc`), `tests/test_acceptance.py::test_check10_…` |

Run everything locally:

```bash
make check          # lint, format, types, unit tests (SQLite)
make e2e            # browser flows
make test-pg        # unit tests on PostgreSQL (needs a server; see Makefile for the URL)
make fresh-clone-check
```
