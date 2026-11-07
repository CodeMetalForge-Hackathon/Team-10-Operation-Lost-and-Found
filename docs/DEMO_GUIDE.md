# Demo guide

This is the Mac path for the operator page. It is a simulation unless you pass a real serial device. It does not estimate a dig location.

The page title is Operations overview. A connected browser is not a TAK connection.

## Open the page that is already running

If someone already started the demo on port 8765:

```bash
open http://127.0.0.1:8765/
```

Identify that process without stopping it:

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

The command column should be `python -m fusion.server`. The cwd of that PID is the checkout it is serving. On macOS:

```bash
lsof -a -p PID -d cwd
```

Replace `PID` with the number from `lsof`. Do not run `kill` unless you mean to stop that exact process.

## Environment

`python3` on this Mac is 3.9. Use 3.11.

```bash
cd ~/Projects/codemetal
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

A git worktree does not bring `.venv` with it. From a worktree, either create a venv there or call the main checkout's interpreter with that worktree as the working directory:

```bash
cd ~/Projects/codemetal-worktrees/operator-ui
/Users/offamacbook/Projects/codemetal/.venv/bin/python -m fusion.server --demo --host 127.0.0.1 --listen 8775
```

Change the path if your checkout is somewhere else. Do not point a Pi browser at `127.0.0.1` on the laptop. The page builds the socket URL from the page origin.

## Start

Default port is 8000. This weekend's running demo has used 8765. Pick one and do not start a second process on it.

```bash
cd ~/Projects/codemetal
. .venv/bin/activate
python -m fusion.server --demo --host 127.0.0.1 --listen 8765
```

Or, if the port is free:

```bash
cd ~/Projects/codemetal
./scripts/run-demo.sh 8765
```

`scripts/run-demo.sh` exits if the port is taken. It does not kill the process that owns it.

What you should see, in order:

1. Data source `SIMULATION`, connection `Connected`, localization `Unavailable`, TAK `Not implemented`.
2. Node 3 reports a `TAP_PATTERN`. The summary shows 1 possible acoustic cue. That is not a survivor count.
3. Node 4 reports hashed device evidence. It does not increment the cue count.
4. After about 10 seconds node 3 is stale. Its tap stays on the card. Stale does not mean cleared.
5. Node 2 can appear because a timing report names it as `src`. It is an observed id, not a deployed-node count.

The spacing is not a map. Positions stay unreported.

## Stop

Stop only the fusion server PID. This does not kill other Python processes.

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
kill PID
```

`kill PID` sends TERM to that one process. If it does not exit, `kill -9 PID` is the last resort for that same PID. Do not use `killall python` or `pkill -f python`.

## Replay

On a `--demo` process, the page shows Replay demo. It `POST`s `/demo/replay`, which clears retained state and plays `sim/demo.py` again through the same ingest parser. It does not send a hardware command.

From another terminal, the same call:

```bash
curl -sS -X POST http://127.0.0.1:8765/demo/replay
```

A live `--gateway` process, and a `--simulate` file process, return 409. Do not expect Replay demo on those. Restart the process instead:

```bash
# stop the PID first, as above, then:
cd ~/Projects/codemetal
. .venv/bin/activate
python -m fusion.server --simulate tests/fixtures/sample_gateway.txt --host 127.0.0.1 --listen 8765
```

That file is loaded at once. It is not the paced demo script.

## Tests and the raw fixture

```bash
cd ~/Projects/codemetal
. .venv/bin/activate
python -m unittest discover -s tests
```

Or:

```bash
cd ~/Projects/codemetal
./scripts/run-tests.sh
```

The fixture is `tests/fixtures/sample_gateway.txt`. The suite reads it. It does not open a serial port.

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

Serial, when a board is actually on the cable:

```bash
python -m fusion.server --gateway /dev/serial/by-id/usb-PASTE-THE-SYMLINK-HERE --host 127.0.0.1 --listen 8765
```

## Troubleshooting

Occupied port: `lsof -nP -iTCP:8765 -sTCP:LISTEN`. Use another port, or stop that one PID if it is the fusion server you intend to replace. Do not start a second server on 8765.

Wrong checkout: the process cwd is the code being served. `lsof -a -p PID -d cwd`, then `git -C THAT_DIRECTORY rev-parse HEAD`.

Missing environment: `python3.11 -m venv .venv` in the checkout you are running, then install `requirements.txt`. A worktree does not contain `.venv`.

Disconnected socket: the header says Disconnected, then Reconnecting. Cached rows stay, with ages marked cached. The page does not invent a new observation while the socket is down. If it stays down, confirm the server PID is still listening and that you opened the page from that server, not as a file.

File URL: `file://` has no host. Open `http://127.0.0.1:PORT/` instead.
