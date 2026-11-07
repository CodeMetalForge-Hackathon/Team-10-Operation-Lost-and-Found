# Contributing

Read `CLAUDE.md` first. Architecture, hardware, and the plan live in `docs/`. This file only covers how we avoid stepping on each other during the hackathon.

## Already decided

- The over-the-air and gateway JSON formats in `docs/ARCHITECTURE.md` are the contract. Do not change them in code without updating that doc and telling the team.
- TAK is the primary operator output. The page in `ui/` is the secondary dashboard. See `docs/DECISIONS.md`.
- There is no project README yet. Do not invent one that claims history. `docs/DECISIONS.md` already lists what existed before this weekend.

## Branches

`main` is the integration branch. Do not commit feature work directly to it.

- `feat/...` new capability
- `fix/...` bugfix
- `docs/...` documentation only
- `chore/...` tooling

Keep branches short-lived. Open a pull request into `main`. Use a draft while it is not ready to merge. Do not merge your own PR unless the other person has agreed.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `chore:`.

One logical change per commit. No secrets, `.env` files, or build output.

## Shared files

Say so before editing these at the same time:

- `CLAUDE.md`
- `docs/ARCHITECTURE.md`, especially the message format
- any file both of us import

The planned layout keeps firmware, fusion, the simulator, the dashboard, and drone scripts in separate directories. Stay in your directory unless a shared interface forces a cross-cut.

## How to run

Nothing in this repo runs yet. These commands are planned in `docs/PLAN.md`. They are not verified:

- Python 3.11+ (`python3` on this Mac is 3.9; `python3.11` is installed)
- packages named in the plan: numpy, scipy, fastapi, uvicorn, pyserial, pytak, scikit-learn
- firmware: Arduino IDE 2 or arduino-cli, with arduino-esp32 core >= 3.3

`ui/index.html` is a static skeleton. It does not start a server and does not define a new message format.
