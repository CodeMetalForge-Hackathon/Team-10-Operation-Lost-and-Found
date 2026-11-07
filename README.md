# Team 10 — Operation Lost and Found

Drop cheap acoustic nodes on a collapsed structure. They mesh without infrastructure, listen for tapping and nearby phones, and the goal is a "where to dig" cue in TAK.

This checkout is a Mac proof of concept. It does not estimate a location, and it has not been run on the ESP32 boards.

## Data flow

```
sim/demo.py  or  USB gateway JSON lines
        │
        ▼
fusion/serial_ingest.py     one parser, five published types
        │  ObservationSink.accept(observation + t_host)
        ▼
fusion/state.py             nodes, evidence, device hashes
        │  no positions
        ▼
fusion/server.py            GET /  and  GET /ws  at 2 Hz
        │
        ▼
ui/index.html               roster, not a floor-plan fix
```

TAK is still the planned primary output. The page is the secondary dashboard. Nothing in this repo sends Cursor-on-Target yet.

## Implemented and planned

| Piece | Status |
|---|---|
| Gateway JSON contract, including `device_seen` | Written by William in `docs/ARCHITECTURE.md`. This branch does not change it. |
| Serial reader (`python -m fusion.serial_ingest`) | Draft PR #8. Accepts the five JSON types from a port or a file. |
| Static page shell | Draft PR #7. This branch renders proposed `/ws` version 1 on that page. |
| Simulated gateway script | `python -m sim.demo`. Scripted lines, not a physics model, not a recording. |
| Fusion state and WebSocket host | This branch. No localization math. |
| Node positions, heatmap, source count | Not implemented. `localization_mode` is `UNLOCALIZED`. |
| `POST /cmd`, `POST /anchor`, `POST /baseline` | Named in the architecture doc. Bodies are not agreed. Not implemented. Buttons stay disabled. |
| ESP32 firmware | Not in this repo. William owns it. |
| `tak.py` / WinTAK | Not implemented. See below. |
| Drone, LED-ID, Hailo | Not in this iteration. The AI accelerator is not required. |

## Hardware

William's `docs/HARDWARE.md` (`3b45ff0`, `5935993`) says:

- 2× Seeed XIAO ESP32-S3 Plus — gateway and drone bridge
- 5× Seeed XIAO ESP32-C5 — field nodes, each with an Adafruit ICS-43434
- Raspberry Pi 5, 16 GB, with the 26 TOPS AI HAT, carried by hand for the drone role

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

Serial, when a board is actually plugged in. This does not guess a device name.

```bash
python -m fusion.server --gateway /dev/serial/by-id/usb-PASTE-THE-SYMLINK-HERE
```

`python -m fusion.serial_ingest` is still the stdout reader from PR #8. The server does not scrape that stdout. It passes `FusionState` into the same parser.

## Dashboard

`ui/index.html` is still one static page. No React.

It speaks only proposed `/ws` version 1. Nodes are drawn in a row so a missing position cannot be mistaken for a dig point. Command buttons stay disabled.

## Interfaces

Gateway → host, unchanged, one JSON object per line at 921600 baud:

- `beacon`
- `feat`
- `event`
- `range`
- `device_seen`

The host adds `t_host` as integer Unix milliseconds. That type is still a local choice; the architecture doc does not specify it.

`/ws` version 1 is proposed in `docs/WS_CONTRACT.md`. It is not in `docs/ARCHITECTURE.md` yet. William has not signed it. `GET /state` returns the same object for debugging.

A node is `inactive` when no accepted line from that `src` has arrived for 6000 ms (three missed 2 s beacons). `device_seen` is stored as the published hash, kind, rssi, and count. A raw MAC is rejected by the parser. A hash is not a person and not a location.

## TAK, still to do

To show the same tap on WinTAK, someone still has to:

1. Add `fusion/tak.py`. It is not in this repo. `pytak` is not installed.
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
git checkout feat/sim-ws-dashboard
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
