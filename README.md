# Team 10 — Operation Lost and Found

Drop cheap acoustic nodes on a collapsed structure. They mesh without infrastructure, listen for tapping and nearby phones, and the goal is a "where to dig" cue in TAK.

This checkout is a Mac proof of concept. It does not estimate a location, and it has not been run on the ESP32 boards.

## Data flow

```
sim/demo.py  or  USB gateway JSON  or  TCP newline JSON  or  data/*.jsonl
        │
        ▼
fusion/serial_ingest.py     one parser for serial, TCP, and recordings
        │  ObservationSink.accept(observation + ingestion t_host)
        ▼
fusion/state.py             nodes, evidence, device hashes, gateway diagnostics
        │  no positions
        ▼
fusion/server.py            GET /, GET /ws
        │
        ▼
ui/index.html               LIVE, RECORDING, or SIMULATION
```

TAK is still the planned primary output. The page is the secondary dashboard. `fusion/tak_hello.py` can send hardcoded CoT markers. The dashboard server does not.

## Implemented and planned

| Piece | Status |
|---|---|
| Gateway JSON contract, including `device_seen` | Written by William in `docs/ARCHITECTURE.md`. Host field rules for his recordings are in `docs/TELEMETRY_CONTRACT.md`. |
| Serial reader and TCP listener | Same parser. TCP was checked on this Mac only. Not on a Pi. |
| Static page shell | Draft PR #7, replaced on this branch by the operations overview. |
| Simulated gateway script | `python -m sim.demo`. Scripted lines, not a physics model, not a recording. |
| Fusion state and WebSocket host | This branch. No localization math. |
| Node positions, heatmap | Hand-entered `--pos`; the experimental heatmap (`fusion/heatmap.py`'s model) runs in the same process at `/heatmap`. The dashboard `/state` stays `UNLOCALIZED`. Source count: not implemented. |
| `POST /cmd` | `?name=HAIL`, `PING` or `BLINK`, sent from the heatmap page. Only with `--gateway` (serial); otherwise refused with 409. |
| `POST /anchor`, `POST /baseline` | Named in the architecture doc. Not implemented. |
| Simulation replay | `POST /demo/replay` on a `--demo` process only. See `docs/DEMO_GUIDE.md`. |
| ESP32 firmware | In `firmware/node/`. William owns it. This host has not been run on a board. |
| TAK / WinTAK / ATAK | `fusion/tak.py`, a separate process, polls the server's `GET /tak` and sends node markers with short evidence text as CoT. No survivor point is sent. See `docs/TAK.md`. |
| Drone, LED-ID, Hailo | Not in this iteration. The AI accelerator is not required. |

## Hardware

William's earlier `docs/HARDWARE.md` (`3b45ff0`, `5935993`) said:

- 2× Seeed XIAO ESP32-S3 Plus — gateway and drone bridge
- 5× Seeed XIAO ESP32-C5 — field nodes, each with an Adafruit ICS-43434
- Raspberry Pi 5, 16 GB, with the 26 TOPS AI HAT, carried by hand for the drone role

The `docs/HARDWARE.md` in this tree is later than that. It switches the field-node sensors to Grove modules. This README does not edit that file.

Sebastian's check on 2026-11-07 did not confirm an S3 in hand. That disagreement is open on issue #5. This README does not change his counts.

If the S3s are in hand, the gateway stays the S3. If they are not, the USB gateway for this iteration is a C5 and there is no drone bridge. The reader uses whichever board is on the cable.

The Pi fusion host uses ordinary Python. It does not load the Hailo accelerator.

## Mac setup

`python3` on this Mac is 3.9. Use 3.11.

```bash
cd ~/Projects/codemetal
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests
```

## Run the simulation and the dashboard

One process. The input is simulated.

```bash
. .venv/bin/activate
python -m fusion.server --demo
```

Open http://127.0.0.1:8000

The running weekend demo may already be on another port. Identify it before starting a second one. Commands, replay, and the occupied-port case are in [`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md).

What you should see, in order:

1. Node 3 appears on the roster. The spacing is not a location.
2. A `TAP_PATTERN` event raises that node's search priority. The banner says it is not a confirmed location.
3. A `device_seen` line from node 4 shows hashed BLE and Wi-Fi evidence. It does not increment the survivor cue.
4. After about 8 seconds node 3 goes inactive. Node 4 stays active because the script keeps sending its beacon.

The other way, still simulated, is a pipe. The simulator flushes each line.

```bash
python -m sim.demo | python -m fusion.server --simulate -
```

A file of the five contract examples, loaded at once rather than paced:

```bash
python -m fusion.server --simulate tests/fixtures/sample_gateway.txt
```

A committed hardware recording, paced, and labeled RECORDING. This is not `--simulate`.

```bash
python -m fusion.server --recording data/beacons_line_2nodes.jsonl --speed 8 --listen 8000
```

TCP newline JSON, same parser as USB. Use a free port. Do not bind 8765 or 8775. This command does not mean a Pi was reached.

```bash
python -m fusion.server --tcp 9100 --tcp-bind 127.0.0.1 --listen 8000
```

The bench checklist is [`docs/INTEGRATION_HANDOFF.md`](docs/INTEGRATION_HANDOFF.md).

Serial, when a board is actually plugged in. This does not guess a device name.

```bash
python -m fusion.server --gateway /dev/serial/by-id/usb-PASTE-THE-SYMLINK-HERE
```

`python -m fusion.serial_ingest` is still the stdout reader from PR #8. The server does not scrape that stdout. It passes `FusionState` into the same parser.

## Dashboard

`ui/index.html` is still one static page. No React.

It speaks only proposed `/ws` version 1. Sensors are listed, not plotted, so a missing position cannot be mistaken for a dig point. Command buttons are not shown. Replay demo appears only for a `--demo` process.

## Interfaces

Gateway → host, one JSON object per line at 921600 baud, or the same line over TCP:

- `beacon` (observed)
- `device_seen` (observed)
- `gw` (observed diagnostic, not a node)
- `feat`, `event` (in `data/live_3node_test1.jsonl`; the host must not drop an unknown `event.kind`)
- `range` (printable, not in the committed recordings)
- `log` and `host_cmd` (recorder or text echo, not sensors)

The host ingestion clock is integer Unix milliseconds. Recorder files store Unix seconds in `t_host`; the host keeps that as `t_recorded_s`. See `docs/TELEMETRY_CONTRACT.md`.

`/ws` version 1 is proposed in `docs/WS_CONTRACT.md`. It is not in `docs/ARCHITECTURE.md` yet. William has not signed it. `GET /state` returns the same object for debugging.

A node is `inactive` when no accepted line from that `src` has arrived for 6000 ms (three missed 2 s beacons). `device_seen` is stored as the published hash, kind, rssi, and count. A raw MAC is rejected by the parser. A hash is not a person and not a location.

## TAK, still to do

To show the same tap on WinTAK, someone still has to:

1. Wire CoT to fusion state. `fusion/tak_hello.py` sends hardcoded markers and is not that path. `fusion/tak.py` is not in this repo. `pytak` is not installed.
2. Pick a command-post origin (`lat0`, `lon0`) by hand. There is no GPS fix in this demo, and there is no node position to convert. Do not invent one.
3. Send CoT to UDP multicast `239.2.3.1:6969`, as `docs/ARCHITECTURE.md` already plans.
4. For this cue, a single unknown-affiliation point is the honest marker, with remarks like `Possible acoustic cue: TAP_PATTERN x3, conf 80, node 3, no position`. Set `stale` to about 30 s.
5. Do not send a CASEVAC / confirmed-survivor marker for simulated or unlocalized evidence.
6. Verify the `type` string in WinTAK. The architecture list is a plan, not a checked render.

Until a position exists, TAK can show the node id and the cue text, or it can show nothing. It cannot show a dig point.

## Tests

```bash
python -m unittest discover -s tests
```

The suite is simulated. It does not open a serial port and it does not claim a hardware run.

## Pi, when SSH exists

Do not reimage or repartition the microSD card from the laptop. The boot partition can stay mounted. Nothing here starts on boot.

On the Pi, after SSH works:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
git clone https://github.com/CodeMetalForge-Hackathon/Team-10.git
cd Team-10
git fetch origin
git checkout feat/demo-integration
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python -m fusion.server --demo --host 0.0.0.0 --listen 8000
```

From the laptop: `http://<pi-address>:8000`

Bind `0.0.0.0` only on the Pi. The Mac default is `127.0.0.1`.

Serial on the Pi, once a gateway board is plugged in, is in `docs/PI_SETUP.md`. Add the user to `dialout`, then:

```bash
python -m fusion.server --gateway /dev/serial/by-id/usb-PASTE-THE-SYMLINK-HERE --host 0.0.0.0 --listen 8000
```

No systemd unit. No Hailo runtime. Raspberry Pi OS 64-bit and a normal Python 3.11+ virtualenv are enough.

`fusion/heatmap.py` came in from `main`. It is a separate experimental estimator. It is not this dashboard, and this page does not show its output as a dig point. See `docs/TELEMETRY_CONTRACT.md`.
