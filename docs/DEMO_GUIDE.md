# Demo guide

This is the Mac path for the operator page. It is a simulation unless you pass a real serial device. It does not estimate a dig location.

The page title is Operations overview. A connected browser is not a TAK connection.

## Open the page that is already running

The evidence-review page verified on 2026-11-07 is:

```bash
open http://127.0.0.1:8775/
```

Port 8765 can still be an older checkout. Identify the process before assuming which page you opened:

```bash
lsof -nP -iTCP:8775 -sTCP:LISTEN
lsof -a -p PID -d cwd
```

Replace `PID` with the number from `lsof`. Do not run `kill` unless you mean to stop that exact process.

## Start

This worktree has no `.venv`. The command below was run from the evidence-review checkout with the main checkout's interpreter. `--listen 8775` was free. Do not start a second process on a port that is already listening.

```bash
cd ~/Projects/codemetal-worktrees/evidence-review
/Users/offamacbook/Projects/codemetal/.venv/bin/python -m fusion.server --demo --host 127.0.0.1 --listen 8775
```

`scripts/run-demo.sh` was not used. It looks for `.venv` in the current checkout, and this worktree does not have one.

What the served page showed:

1. Source `SIMULATION`, browser `Connected`, sensors `1 reporting · 2 stale` after node 3 aged out, TAK `Not implemented`.
2. The queue selected `Tap pattern` on Node 3. Evidence age and sensor staleness were separate. The raw event `TAP_PATTERN` stayed in the detail panel.
3. Node 4's newer line did not make the Node 3 cue look fresh.
4. The timeline plotted host-receipt time by sensor. A circle was the tap. Triangles were radio evidence. Node 2 had a row and no mark.

## Stop

Stop only the fusion server PID on the port you started. This does not kill other Python processes.

```bash
lsof -nP -iTCP:8775 -sTCP:LISTEN
kill PID
```

`kill PID` sends TERM. If it does not exit, `kill -9 PID` is the last resort for that same PID. Do not use `killall python` or `pkill -f python`.

## Replay

On a `--demo` process, Replay demo `POST`s `/demo/replay`. The same call from another terminal, verified against the 8775 process:

```bash
curl -sS -X POST http://127.0.0.1:8775/demo/replay
```

It clears retained demo observations and plays `sim/demo.py` again through ingest. It does not send a hardware command. The page keeps an explicit selection instead of jumping to the new cue. A snapshot that has not cleared yet is still the previous demo run.

## Tests

```bash
cd ~/Projects/codemetal-worktrees/evidence-review
/Users/offamacbook/Projects/codemetal/.venv/bin/python -m unittest discover -s tests
```

That run included `tests/review_policy_check.cjs` via `node`. 29 tests passed. The suite does not open a serial port.

The spacing is not a map. Positions stay unreported.

## Branch and commit

```bash
cd ~/Projects/codemetal
git status -sb
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git log -1 --oneline
```

If the server cwd is a worktree, run those commands in that directory, not in a different checkout.

## Available controls

- Select a sensor card, an acoustic cue, or a device-evidence row.
- Filter: All, Acoustic cues, Device evidence, Stale.
- Expand Technical details on the selection.
- Expand Diagnostics for the socket URL, rates, neighbor reports, timing reports, and the raw message.
- Replay demo, only while `GET /demo` says `available` is true.

## Not available

HAIL, BLINK IDs, RANGE, QUIET MODE, and BASELINE are explained in Diagnostics. There is no button for them. `POST /cmd`, `POST /anchor`, and `POST /baseline` return 404. QUIET MODE has no agreed command byte.

## Status of the other paths

| Path | Status in this checkout |
|---|---|
| Simulated `--demo` ingest and the operator page | Run on this Mac. Not a hardware recording. |
| `--simulate FILE` ingest | Implemented. Replay is not. Restart the process. |
| Serial `--gateway DEVICE` | Code exists. Not verified against a board from this guide. Baud defaults to the contract 921600 unless `--baud` is passed. Do not invent a device name. |
| TAK / CoT | Not implemented. No `tak.py`. A connected socket is not TAK. |
| Localization | Not implemented. `localization_mode` is `UNLOCALIZED`. The page says Unavailable. |
| Raspberry Pi | Not deployed from this guide. Do not flash or repartition a card from the laptop. |

Serial `--gateway` was not run from this guide. Do not invent a device name. `--simulate` was not re-run in this pass. Replay returns 409 for a live gateway session and for `--simulate`; that refusal is covered by `tests/test_demo_replay.py`, not by a second server started here.

## Troubleshooting

Occupied port: `lsof -nP -iTCP:8775 -sTCP:LISTEN`. Use another port, or stop that one PID if it is the fusion server you intend to replace. Do not start a second server on a port that is already listening. Port 8765 was still the older checkout when this page was verified.

Wrong checkout: the process cwd is the code being served. `lsof -a -p PID -d cwd`, then `git -C THAT_DIRECTORY rev-parse HEAD`.

Missing environment: `python3.11 -m venv .venv` in the checkout you are running, then install `requirements.txt`. A worktree does not contain `.venv`.

Disconnected socket: the header says Disconnected, then Reconnecting. Cached rows stay, with ages marked cached. The page does not invent a new observation while the socket is down. If it stays down, confirm the server PID is still listening and that you opened the page from that server, not as a file.

File URL: `file://` has no host. Open `http://127.0.0.1:PORT/` instead.
