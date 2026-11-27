# Working rules for Ration Bolo

`SPEC.md` is the single source of truth. Read `CLAUDE.md`, `SPEC.md` and `PROGRESS.md` at the start of every session.

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
- The app must always start with `docker compose up` on a clean checkout with **no `.env` and no keys**, and show the call simulator. A change that breaks this is not done.
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
