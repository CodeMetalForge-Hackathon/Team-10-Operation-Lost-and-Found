# Architecture

```
 FIELD (debris)                                         COMMAND POST
 ┌──────────┐  ESP-NOW flood   ┌──────────┐
 │ Node 1   │◄────────────────►│ Node 2   │ ...       ┌──────────────┐ USB serial  ┌─────────────────────────┐
 │ mic,buzz │                  │          │◄─────────►│ Gateway ESP32│────────────►│ Fusion host (Python)    │
 │ LED      │◄──────┐   ┌─────►└──────────┘           └──────────────┘ JSON lines  │  ingest (serial | sim)  │
 └──────────┘       │   │                                                         │  node localization      │
                ┌───┴───┴────────────┐                                            │  source heatmap + count │
                │ Drone: Pi5 + cam + │  (GPS if available; else relay +           │  FastAPI + WebSocket UI │
                │ ESP32 bridge       │   optical LED-ID of nodes)                 │  CoT ──► WinTAK / ATAK  │
                └────────────────────┘                                            └─────────────────────────┘
```

## 1. Node firmware (`firmware/node/`, Arduino, one sketch for S3 and C5)
- **Role at compile time:** `ROLE_NODE`, `ROLE_GATEWAY` or `ROLE_DRONE_BRIDGE`. Node ID is set by a `#define` or derived from the MAC address.
- **Radio:**
  - Wi-Fi STA mode, not connected to any network, **fixed channel 1**.
  - On the C5, force 2.4 GHz only: `esp_wifi_set_band_mode(WIFI_BAND_MODE_2G_ONLY)`.
  - ESP-NOW broadcast to `FF:FF:FF:FF:FF:FF`.
  - The receive callback (core 3.x) provides `esp_now_recv_info_t->rx_ctrl->rssi`, so signal strength comes for free.
- **Flooding:**
  - On receive, de-duplicate on `(src, seq)` using a ring buffer of the last 64 entries.
  - If `ttl > 0`, rebroadcast with `ttl-1` and `hops+1` after a random 0–20 ms jitter.
  - Starting TTL is 4.
  - The transmit power is adjustable by command, so we can force multi-hop on a small floor.
- **Audio:**
  - I2S MEMS microphone at 16 kHz. Fallback: an analog microphone on the ADC.
  - Every 50 ms frame, compute RMS in dB and three band energies: low 60–300 Hz, voice 300–3000 Hz, high 3000–8000 Hz. Use cheap IIR band-pass filters or a 256-point FFT.
  - Track the noise floor as an exponential moving average of quiet frames.
  - **Onset detection:** the frame is more than `floor + 12 dB` and rising fast. Record a microsecond timestamp for each onset.
  - **Tap pattern:** 2–5 onsets with 150–700 ms spacing inside a 3 s window gives a `TAP_PATTERN` event.
  - **Voice-like:** voice-band energy stays above the floor for more than 400 ms and dominates the other bands.
- **Buzzer:**
  - Passive piezo driven by `ledc` at about 4 kHz.
  - Used for the HAIL prompt and for ranging chirps.
- **LED:** blinks its ID code (Manchester-style, about 5 Hz) on the `BLINK_ID` command, so the overhead camera can identify it.

## 2. Message format (CONTRACT: change only with team agreement)

### Over the air (packed binary, little-endian, ≤ 250 bytes)

Common header, 8 bytes:
| field | type | notes |
|---|---|---|
| magic | u8 | `0xA7` |
| type | u8 | see below |
| src | u8 | origin node ID (0 = gateway, 200+ = drone) |
| ttl | u8 | hops remaining |
| hops | u8 | hops so far |
| seq | u16 | per-source counter |
| rsv | u8 | 0 |

| type | name | payload | rate |
|---|---|---|---|
| 1 | BEACON | `batt_mv u16, uptime_s u16, floor_db i8, n u8, neighbors[n]{id u8, rssi i8}` | every 2 s |
| 2 | FEAT | `t_ms u32, rms_db i8, low_db i8, voice_db i8, high_db i8, peak_db i8` (1 s summary) | 1 Hz |
| 3 | EVENT | `t_ms u32, kind u8, peak_db i8, voice_db i8, count u8, conf u8` | on detection |
| 4 | CHIRP | `t_us u32` (the sender buzzes as it transmits) | on command |
| 5 | RANGE | `chirper u8, delay_us u32, snr_db i8` | after hearing a chirp |
| 6 | CMD | `cmd u8, arg i16, target u8 (255 = all)` | flooded downlink from gateway |

- EVENT `kind`: 1 = LOUD, 2 = TAP_PATTERN, 3 = VOICE_LIKE, 4 = RADAR_PRESENCE, 5 = GAS.
- CMD `cmd`: 1 = HAIL, 2 = BLINK_ID, 3 = START_RANGING (nodes chirp in ID order, 500 ms apart), 4 = SET_TX_POWER, 5 = SET_RATE, 6 = PING.

### Gateway → host (one JSON object per line over USB serial, 921600 baud)
```json
{"type":"beacon","src":3,"seq":120,"hops":1,"rssi_last":-58,"batt_mv":3950,"floor_db":-62,"nbrs":[[1,-55],[2,-71]]}
{"type":"feat","src":3,"seq":121,"hops":1,"rssi_last":-58,"t_ms":51234,"rms_db":-40,"low_db":-50,"voice_db":-42,"high_db":-55,"peak_db":-30}
{"type":"event","src":3,"seq":122,"hops":2,"rssi_last":-70,"t_ms":51800,"kind":"TAP_PATTERN","peak_db":-20,"voice_db":-35,"count":3,"conf":80}
{"type":"range","src":2,"chirper":3,"delay_us":10450,"snr_db":18}
```
- The host adds `t_host`, its own arrival timestamp.
- Host → gateway commands go back over the same serial port as text, e.g. `CMD HAIL 0 255\n`.
- **The simulator (`sim/`) must emit exactly these lines**, either to stdout or to a TCP socket. The ingest code accepts either a serial port or a simulator source.

## 3. Fusion host (`fusion/`, Python 3.11)
- **ingest:** a serial reader thread or a simulator source, feeding an in-memory state (nodes, latest features, events, ranges, neighbor signal strengths).
- **Node localization (`localize_nodes.py`):**
  - Solve one robust least-squares problem (`scipy.optimize.least_squares`, `loss='soft_l1'`) over node positions `x_i` in a local east-north frame (metres, origin at the command post).
  - **Anchor terms:** `(x_i − a_i)/σ_a`. Sources: GPS drop log or drone GPS (σ about 3 m), camera LED-ID (σ about 0.3 m), or manual placement (σ about 0.5 m).
  - **Acoustic range terms:** `d_ij = c·(delay_us − bias_us)·1e-6`, with `c = 343 m/s`. Calibrate `bias` once at a known distance. σ about 0.3 m.
  - **Signal-strength terms:** log-distance model `rssi = P0 − 10·n·log10(d)`, calibrated on site with P0 and n fitted from pairs at known distance. Use the residual in log-distance space, with a large σ.
  - **Prior:** a weak term pulling every node toward the centroid of the area, to avoid runaway solutions.
  - With no anchors, use classical multidimensional scaling (MDS) to initialise and report positions as *relative* only. The dashboard says so.
- **Source localization (`localize_sources.py`):**
  - Group EVENT and FEAT spikes across nodes into one window of about 300 ms, aligned by `t_host`.
  - Per-node gain calibration `g_i`: everyone hears the same reference chirp.
  - For each grid cell `p` (0.25 m), use the model `L_i = S − 20·log10(max(|p − x_i|, 0.5)) + g_i`.
    - `S` has a closed form: the mean of `L_i − g_i + 20·log10(d_i)`.
    - Nodes that did *not* detect add a penalty if the model predicts a level above their noise floor.
  - Likelihood `exp(−SSR/2σ²)` gives the **heatmap**. Accumulate it with decay over time.
  - **Count:** DBSCAN on the peak locations of the last N minutes, split by event kind, reported as "N distinct sources (confidence)".
  - **Stretch:** time-difference-of-arrival (TDoA) using the onset timestamps, once ranging has proven the nodes' timing.
- **server.py:** FastAPI app.
  - `/ws` pushes state at 2 Hz.
  - POST `/cmd` sends HAIL, BLINK, RANGE, TXPOWER.
  - POST `/anchor` handles manual drag-to-place.
  - Static UI is in `ui/`.
- **tak.py:** CoT over UDP multicast `239.2.3.1:6969` (the TAK multicast channel for sharing positions), using `pytak` or raw XML.
  - **Local frame to latitude/longitude:**
    - `lat = lat0 + dN/111_320`
    - `lon = lon0 + dE/(111_320·cos(lat0))`
    - `lat0` and `lon0` are the command post, entered by hand or taken from the drone's GPS.
  - **Planned CoT mapping** (verify each `type` renders as intended in WinTAK):
    - each node → sensor/equipment point (e.g. `a-f-G-E-S`), with the node ID and battery in the remarks;
    - each live source estimate → point (e.g. `a-u-G`), with the label "Possible survivor: TAP x3, conf 0.8, ±1.5 m";
    - a confirmed source → CASEVAC / medevac marker type;
    - heatmap hotspots → circle or polygon drawing shapes, coloured by likelihood;
    - set `stale` short (about 30 s) so dead information ages out.

## 4. UI (`ui/`, a single static page)
- Canvas showing a floor-plan or drone-mosaic background image, with a metre grid.
- Nodes drawn as dots with their IDs. Mesh links drawn coloured by signal strength. Hop count shown.
- Heatmap overlay. Source markers with their count.
- **Big buttons:** HAIL, BLINK IDs, RANGE, QUIET MODE.
- **Status strip:** nodes alive, packets per second, bytes per second, localization mode (ANCHORED / RELATIVE).
- The panel's "red light / green light" advice: a single big banner, `0 / 1 / 2 possible survivors`.

## 5. Drone (`drone/`, Pi 5, **carried by hand to simulate flight**; the Cetus X can't lift it)
- `droplog.py` logs each drop: a keypress records the time, the camera frame and GPS if there's a fix.
- A Pi camera captures frames.
- `ledid.py` detects blinking LEDs, decodes the IDs, and converts pixel positions to ground positions. Scale comes from the known altitude or from two reference markers. The output is anchors.
- An ESP32 in `ROLE_DRONE_BRIDGE` connects over USB to the Pi. It relays the mesh and logs signal strength per node along with GPS (if a GPS module is attached).
- With GPS, the drone's signal-strength samples taken at many known points are multilaterated into each node's position. This replaces the "drop log" when a real drop isn't possible.
- **Stretch:** a person detector on the AI HAT (Hailo, using the prebuilt `hailo-rpi5-examples` YOLO models), or the HT-203U thermal camera if it works as a UVC webcam.

## 6. Repo layout
```
firmware/node/        Arduino sketch (all roles), protocol.h shared structs
fusion/               ingest, localize_nodes, localize_sources, server, tak
sim/                  simulator emitting gateway JSON lines (+ ground truth)
ui/                   static dashboard
drone/                Pi scripts (camera LED-ID, bridge logger)
data/                 recorded runs (replayable) + ground truth
docs/                 these docs
```

## Bandwidth budget (deployability talking point)
- Per node: BEACON about 30 B every 2 s, plus FEAT 16 B at 1 Hz, plus occasional events. That's about **35 B/s per node**.
- Raw 16 kHz 16-bit audio (the reference paper's approach) is 32,000 B/s, about **900× more**.
- Flooding multiplies traffic by the node count. 50 nodes × 35 B/s × 50 is about 90 kB/s, well within what ESP-NOW can carry. Larger fields use TTL limits and cluster heads.
