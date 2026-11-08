# TAK integration (Cursor-on-Target)

## Why TAK (the pitch point)
Responders at a collapse already run **TAK** (ATAK on phones, WinTAK on laptops, iTAK, TAK Server). It's the standard situational-awareness tool for US military, federal, state and local first responders. **We don't ask them to learn a new app.** Our "where to dig" estimate lands as an ordinary marker in the TAK map they already have open, next to their own team, routes and casualty markers. That's what the Friday panel asked for: *"don't bring a new widget, integrate."*

What makes the integration seamless:
- **Standard protocol.** Plain **Cursor-on-Target (CoT) XML over UDP**, the format every TAK client reads. No plugin, no TAK Server and no account needed. One Python file, standard library only.
- **Standard symbols.** Nodes are friendly ground sensors (`a-f-G-E-S`). The survivor estimate is an unknown ground contact (`a-u-G`), labelled **"T10 LOOK HERE"**. Any TAK user already knows how to read, share, route to or mark these.
- **Works on a degraded network.** Unicast to one laptop, or the TAK SA multicast channel (`239.2.3.1:6969`) so every TAK device on the local network sees it. No internet or cell service is needed, which matches our "no infrastructure" scenario.
- **Honest output.** Markers say what they are ("Possible survivor … Not a confirmed location", with the uncertainty in metres). They **clear themselves** when the fusion host stops confirming them, so a stale "survivor" never lingers on a responder's map.
- **GPS-denied friendly.** Positions come from our local metre grid, anchored to one known point (the command post or node N1) and a compass heading.

## What responders see
| TAK item | CoT type | Label | When it changes |
|---|---|---|---|
| Each sensor node | `a-f-G-E-S` (friendly ground sensor) | `T10 N1` … or **`T10 N5 LOST`** when it stops reporting | Immediately on LOST/back, else refreshed every 20 s (stale 60 s) |
| Survivor estimate (heatmap peak) | `a-u-G` (unknown ground) | **`T10 LOOK HERE`**; remarks: uncertainty ±m, evidence strength, "HAIL sent N s ago" when relevant, "Not a confirmed location" | When the peak moves to another 0.3 m cell or its uncertainty changes by 0.3 m, else every 20 s; **cleared** (1 s stale) when the map loses confidence |

The uncertainty is the marker's circular error (`ce`) and is stated in its remarks. The full heatmap stays on the operator dashboard: the field gets a few simple markers, the operator gets the full map (see PROJECT_BRIEF "red light or full map").

**Verified on 2026-11-07/08 in WinTAK** on the demo laptop, with the heatmap simulator. Node markers, the LOST state and "DIG HERE?" (since renamed "LOOK HERE") render at the right place and scale (N1 to N2 = 3 m on the TAK scale bar). The marker followed the heatmap peak after a HAIL and cleared when confidence dropped.

## How to run it
```bash
# 1. fusion: live gateway, a recording, or the simulator (serves /state on :8000)
python fusion/heatmap.py --port COM13          # or: --replay data/live_3node_test1.jsonl   or: --sim
# 2. TAK bridge: polls /state every 2 s, sends CoT to WinTAK on this laptop (127.0.0.1:4242)
python fusion/tak.py --lat 42.35938882464616 --lon -71.05658046185967 --heading 0
#    add --multicast to share with every TAK device on the LAN (others at the venue will see it too!)
#    --test sends a fixed pattern (3 nodes, one LOST, one LOOK HERE) without any fusion running
```
- **Room alignment:** `--lat/--lon` = the real position of local (0, 0), i.e. node N1. `--heading` = compass bearing of the local +y axis (the N1 → N5 direction in the 3-node layout). Then the TAK map matches the room.
- The demo venue origin used so far is 42.35938882464616, −71.05658046185967.

## Demo rules (learned the hard way)
1. **Turn off WinTAK's serial/GPS COM-port scanning** before plugging in boards. WinTAK grabs COM ports, which breaks flashing and can steal the gateway's port.
2. **Read a marker's details, then close the pane.** WinTAK crashes ("Must create DependencySource on same Thread as the DependencyObject") if a marker is updated while its details pane is open. It's a WinTAK bug, reproduced twice. The bridge keeps updates rare (only on real change, or every 20 s) to make this unlikely, but it can't rule it out.
3. **Run exactly one `tak.py`.** Check with `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ? CommandLine -match 'tak.py'`. Stopping a background shell can leave the Python process running, and a leftover old bridge kept drawing shapes on the map.
4. Other teams' TAK markers may appear (e.g. "SAR #3 RESPONSIVE INJURED"): the venue network carries shared SA multicast. Ours are all prefixed **T10**.

## How it plugs into the fusion host
`tak.py` only reads JSON over HTTP. It needs a picture of this shape, built by one adapter function (`picture_from_heatmap_state`):
```json
{"nodes": [{"id": 1, "x": 0.0, "y": 0.0, "alive": true}],
 "sources": [{"x": 2.0, "y": 0.8, "radius": 0.8, "strength": 1.5}],
 "note": "HAIL sent 6 s ago"}
```
When the merged fusion server replaces `heatmap.py`, add one adapter for its state and nothing else changes. The bridge keeps running if the fusion host restarts: markers go stale, then come back.

## Limits and next steps
- **No drawn uncertainty circle yet.** Circles appeared to stack up in WinTAK, but that test was confounded by leftover bridge processes. Retest a single fixed-uid circle (`u-d-c-c`) with one bridge running before adding it back.
- Not yet sent:
  - RF "device signal" markers (stationary phone or Find My beacon near a node);
  - more than one source;
  - a CASEVAC marker once a source is confirmed;
  - node battery (firmware doesn't measure it yet).
- Positions are only as good as the node anchors (hand-measured for the demo).
- Production path: send through a **TAK Server** (TLS, certificates) for teams beyond the local network, or package it as an **ATAK plugin** with a heatmap layer.
