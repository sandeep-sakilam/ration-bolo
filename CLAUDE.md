# Working rules for Ration Bolo

`SPEC.md` is the single source of truth. Read `CLAUDE.md`, `SPEC.md` and `PROGRESS.md` at the start of every session.

## Spec updates
- When `SPEC.md` is replaced with a newer version, the first branch of the session is `docs/spec-vN` (N = version): replace `SPEC.md`, add the new backlog rows to `PROGRESS.md` unticked, copy changed working rules here. Normal PR and local merge before any functionality work.

## Start of every session
- Check for open branches and PRs. If a functionality is in progress or waiting to merge, finish and merge it before anything new.
- Then take the next unchecked item in `PROGRESS.md`.

## Git workflow (mandatory)
1. Start from an up-to-date `main`; create one feature branch for exactly one functionality (e.g. `feat/f04-slot-engine`).
2. Implement it with its tests on that branch. Nothing else goes on it.
3. Run the quality gate (`make check`, plus `make e2e` for user flows), then open a PR to `main` describing what changed and how it was tested.
4. Merge locally: `git checkout main && git merge --no-ff <branch>`, then `git push origin main`. Delete the local branch. (Remote branch deletion is refused by the cloud proxy; Sandeep cleans those up.)
5. Only then start the next functionality. At most one open feature branch at any time.

## Commit identity (every commit, including merges)
- Author and committer: `Sandeep Sakilam <sakilamsandeep@gmail.com>`.
- Check: `git log --format='%an <%ae> | %cn <%ce>' main..HEAD`.
- Never merge with GitHub's merge button or API.

## No assistant attribution
- No commit title or message, PR title or PR description may mention the AI assistant or its tooling: no co-author trailers, no "generated with" footers, no session links.
- Check before every push: `git log --format='%B' main..HEAD | grep -i claude` must return nothing.

## Product rules
- The app must always start with `docker compose up` on a clean checkout with **no `.env` and no keys**, and show the call simulator. From F24, the dealer and admin pages must also open without any PIN when none is set. A change that breaks this is not done.
- No login wall: the live link must be usable by judges without a PIN; PINs apply only when explicitly set.
- Submission deadlines: F23–F28 (version 2) and F29–F39 (version 3) merged by 30 Nov 2026, 12:00 noon IST; F40–F45 (version 3.1) merged by 30 Nov 2026, 10:00 AM IST; F46 (version 3.2) merged by 29 Nov 2026, 6:00 PM IST; always in order, with `main` shippable after every merge (if time runs short, stop after the last finished item); the hackathon form closes 30 Nov 11:59 PM IST and can be submitted once.
- Works without a partner (version 3): Level 0 features (cardholder reports, public PDS data, best-time advice, nearby shops, grievance routing, transparency page) must work with no partner, no keys and mock adapters, and must never break the Shop 108 flows or acceptance checks 1–14.
- Every new outside service (public PDS portal, grievance helpline, check-in number, broadcasts) gets an interface, a mock adapter and a real adapter; tests use mocks only and never fetch real government portals.
- Never dial a helpline or any real phone number, in tests or by hand; never message real people.
- Voice polish (version 3.1): advice times (best time, quiet hours, nearby-shop wait, "opens at") are spoken as part-of-day phrases from the state pack, never "HH:MM"; exact slot and token times ("Repu 10:20 ki, sare na?") keep their format. One status warning per call, at most one advice sentence per answer, and scripted replies fit the length budget (at most 2 sentences plus the closing question, at most 220 characters before it).
- Closed-shop honesty (version 3.2): a closed shop is never offered with a current wait (closed candidates rank after open ones; the offer says it is closed, when it opens and the usual wait then); the nearby offer and the reply after "yes" come from one stored result per suggestion, so they never disagree; "rice is there" is said for a closed shop only when today's reports or sales confirm it; demo reports keep their real age outside open hours (spoken as "this morning" / "yesterday evening"). Every reply at 11:00 IST stays exactly as in version 3.1.
- Existing assertions change only where a version 3.2 rule requires it; list every changed assertion in the PR description.
- Existing assertions change only where a version 3.1 rule requires it (repeated status warning, extra advice sentence, 24-hour advice times), and every changed assertion is listed in the PR description.
- Schema changes: new tables only, never new columns on existing tables (`create_all` must upgrade an existing database safely).
- Deck PDF: at most 30 pages and 10 MB; numbers in it are computed at build time. Demo video: YouTube only, at most 3:00, with a live voice interaction.
- Never run the real-adapter smoke script (`scripts/smoke_real.py`) against real services; it is for Sandeep only, never in CI or tests.
- Every outside service has an interface, a mock adapter and a real adapter; real adapters only turn on when keys are present. Tests always use mocks.
- Never commit secrets. Every key is listed in `.env.example`.
- Don't stop to ask: decide, log one line in `DECISIONS.md` (date, question, choice, reason), carry on. Stop only before irreversible actions outside the repo (spending money, buying numbers, contacting real people).

## Definition of done
- Code and tests written; `make check` passes (ruff lint, ruff format check, mypy, pytest) and `make e2e` for touched user flows.
- Docs updated; `PROGRESS.md` ticked in the same PR.
- PR opened, merged locally into `main`, pushed, local branch deleted.

## Cloud session notes
- `gh pr` is blocked: open PRs with the GitHub tools or `gh api repos/{owner}/{repo}/pulls`.
- PostgreSQL 16 and Docker are installed but not running (`service postgresql start`, start dockerd).
- Chromium is under `/opt/pw-browsers`. Never run `playwright install`.
- Keep long commands under 10 minutes or run them in the background.
