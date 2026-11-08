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
- **Audio + SW-420 + buzzer, AS BUILT (`node.ino` STEP 3, 2026-11-07).** Policy: **report every sound and every movement with its strength; fusion decides the weight.** No classification gates on the node.
  - Sound sensor sampled at **16 kHz by the ADC DMA driver** in its own FreeRTOS task (the C5 is single-core, and the 2 s BLE scans block `loop()`). The audio task sends its own packets, so events are not held up by a BLE scan.
  - **Level** per 10 ms frame = mean absolute deviation around a ~1 s running average, in **dBFS re 2048 counts** (room noise on the hackathon floor ≈ −22 dBFS; clipped buzzer ≈ −1 dBFS). **Noise floor** follows quiet frames quickly and loud stretches slowly (~5 s); it is `floor_db` in BEACON.
  - **LOUD:** an onset is a frame ≥ floor + 10 dB and ≥ 6 dB above the previous frame. Onsets within 250 ms merge into one LOUD (strongest kept).
  - **VIBRATION (SW-420):** a burst = edges until 300 ms of silence.
  - **VOICE_LIKE = any sustained sound** (≥ floor + 6 dB for ≥ 400 ms, gaps ≤ 150 ms allowed). Not a voice classifier: voice, moaning, machinery and room chatter all count. Re-sent every 2 s while it lasts.
  - **TAP_PATTERN:** built from mic onsets (outside sustained sound) and SW-420 bursts, merged when within 120 ms. Any run of ≥ 2 taps with gaps of 150–1500 ms. Sent in addition to the individual LOUD/VIBRATION events.
  - **HAIL:** 3 × 150 ms beeps at 2.3 kHz (300 ms period). The node ignores the mic and the SW-420 from the first beep until 2.5 s after the last, because neighbours receive the command (and beep) up to ~2 s late when a BLE scan is running.
  - Debug: on a field node's USB serial, `H` triggers a local HAIL; every 5 s it prints floor, level, event counters and the raw SW-420 edge count.
  - The older design notes below (50 ms frames, band energies, voice-band dominance) are superseded where they disagree.
- **Audio (original design notes):**
  - Grove Sound Sensor (analog) on the ADC at 16 kHz (ADC continuous driver). Fallback: Grove Loudness Sensor (loudness level only). Taps are also caught by a Grove Vibration SW-420 contact switch (digital interrupt, timestamps only).
  - **Measured limits (N2 bench test):** the sensor output is clipped at both ends (bottom half of the wave lost, top flat at ~1.5 V), because its LM386 runs below spec at 3V3. We accept this and design around it:
    - Sample at **16 kHz**. Count samples at ≤ 8 or ≥ 1850 counts per frame as `clip`; a frame that is mostly clipped means "very loud, level unknown (at least this loud)".
    - Measure level as the mean absolute deviation from the slow average (robust to the missing bottom half) and convert to dB. Levels compress for close, loud sources, so keep demo sources ≥ 1 m from nodes.
    - **Band energies are unreliable** (clipping creates false harmonics), so they are **not sent: FEAT band fields are always `-128`**; `VOICE_LIKE` falls back to "sustained energy above floor for > 400 ms without tap-like onsets".
    - **Blank all detection (mic onsets and SW-420) while this node's own buzzer is on, plus 50 ms after.**
  - Every 50 ms frame, compute RMS in dB and three band energies: low 60–300 Hz, voice 300–3000 Hz, high 3000–8000 Hz. Use cheap IIR band-pass filters or a 256-point FFT.
  - Track the noise floor as an exponential moving average of quiet frames.
  - **Onset detection:** the frame is more than `floor + 12 dB` and rising fast. Record a microsecond timestamp for each onset.
  - **Tap pattern:** 2–5 onsets with 150–700 ms spacing inside a 3 s window gives a `TAP_PATTERN` event.
  - **SW-420 tap detection (primary in noisy rooms):** a tap = the first edge after ≥ 300 ms of no edges (the switch rings for up to ~1.5 s after a hard tap, so also end a tap only after 300 ms of silence). Light taps give 2–6 edges, hard ones ~100. Taps spaced closer than the ring time merge into one, so the pattern detector should accept 400–1500 ms spacing for SW-420 taps. A mic onset within ±50 ms of an SW-420 tap raises `conf`.
  - **Voice-like:** voice-band energy stays above the floor for more than 400 ms and dominates the other bands.
- **Buzzer:**
  - Grove Buzzer driven by `ledc` at its resonance (about 2.3 kHz).
  - Used for the HAIL prompt and for ranging chirps.
- **LED:** no external LED on the demo nodes (we only found one). The XIAO's on-board user LED (`LED_BUILTIN`) shows status and blinks its ID code (Manchester-style, about 5 Hz) on `BLINK_ID`. It is too dim for the overhead camera, so camera LED-ID is cut for the demo: anchors are hand-measured.
- **Phone/device detection (passive RF; receive only, never transmit):**
  - **BLE scan** (the BLE library in core 3.x, or NimBLE-Arduino):
    - Passive scan **2 s out of every 10 s** (adjustable with `SET_SCAN`), so ESP-NOW keeps most of the shared radio time.
    - Classify each advertisement by its data:
      - Apple manufacturer ID `0x004C` gives `BLE_APPLE`.
      - Apple payload type `0x12` (the offline Find My beacon, broadcast even when the iPhone is powered off) gives `BLE_FINDMY`.
      - Google Fast Pair / Find Hub service UUIDs (e.g. `0xFE2C`) give `BLE_GOOGLE`.
      - Anything else is `BLE_OTHER`.
      - Verify these IDs with a real phone.
  - **Wi-Fi probe requests:**
    - Use promiscuous mode with filter `WIFI_PROMIS_FILTER_MASK_MGMT` and keep frames of subtype `0x40` (probe request).
    - This only works on channel 1, the same channel as ESP-NOW. Phones scan every channel, so we catch a subset.
  - **Privacy:** never send raw MAC addresses. Send `hash32 = FNV-1a(MAC ‖ deployment_salt)`.
  - **Aggregation:** keep a table over each 10 s window: hash → `{kind, rssi_max, count}`. Ignore our own nodes' MACs. Send the strongest 20 as one `DEVICE_SEEN` packet.
  - **Risk to clear first:** confirm BLE scanning and ESP-NOW can run together on the **C5**, and that the BLE library builds for the C5 under core 3.3. If the C5 can't, scan on the S3s only.

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
| 7 | DEVICE_SEEN | `t_ms u32, n u8, devs[n]{hash u32, kind u8, rssi_max i8, count u8}` (7 B/device, n ≤ 20) | every 10 s if any were seen |

- EVENT `kind`: 1 = LOUD, 2 = TAP_PATTERN, 3 = VOICE_LIKE, 4 = RADAR_PRESENCE, 5 = GAS, 6 = VIBRATION, 7 = MOVED.
  - **All dB fields are dBFS re 2048 ADC counts (≤ 0). `-128` = not available.** FEAT band fields (`low_db`, `voice_db`, `high_db`) are always `-128` on the Grove sound sensor (clipping makes bands meaningless). FEAT `peak_db` = loudest 10 ms frame in the second.
  - **LOUD:** `peak_db` = loudest 10 ms frame in the 250 ms after the onset, `voice_db` = -128, `count` = onsets merged, `conf` = 4 × (peak − floor) dB.
  - **TAP_PATTERN:** `peak_db` = loudest tap as heard by the mic, **or the node's floor if no tap was heard ("felt, not heard"; `conf` ≤ 50)**, `voice_db` = -128, `count` = taps, `conf` = 30 + 10·min(taps, 5) + 20 if most taps were felt + 15 if regular.
  - **VOICE_LIKE (= sustained sound, not a voice classifier):** `peak_db` = loudest frame since the last report, `voice_db` = **average level** over the episode, `count` = duration so far in 100 ms units (cap 255), `conf` = 5 × (average − floor) dB.
  - **VIBRATION, from the SW-420 (repurposed from the parked accelerometer):** one event per burst of switch edges. `count` = **number of edges (strength proxy: light tap ≈ 2–6, hard hit or handling ≈ 50–255)**, `peak_db` = how loud the mic heard it (loudest frame from 50 ms before to 150 ms after the burst start) **or the floor if not heard**, `voice_db` = -128, `conf` = 90 if the mic also heard it, else 60. `t_ms` = burst start.
  - Kind 7 (MOVED) is **reserved for an optional accelerometer (not fitted); nothing sends it yet.** If an accelerometer is ever fitted, its jolts would also use VIBRATION:
  - **VIBRATION** (accelerometer, not fitted): `peak_db` = peak acceleration in dB re 1 mg (`20·log10(mg)`, int8), `voice_db` = 0, `count` = jolts in the window, `conf` = 0–100 (higher when the SW-420 or the mic saw an onset at the same time).
  - **MOVED** (accelerometer): `peak_db` = 0, `voice_db` = 0, `count` = orientation code (0 = mic up, 1 = upside down, 2 = on its side, 255 = unknown), `conf` = tilt change in degrees (capped at 255). Sent once at boot and on each disturbance.
- CMD `cmd`: 1 = HAIL, 2 = BLINK_ID, 3 = START_RANGING (nodes chirp in ID order, 500 ms apart), 4 = SET_TX_POWER, 5 = SET_RATE, 6 = PING, 7 = SET_SCAN (arg = BLE scan seconds per 10 s window; 0 = off), 8 = SET_SALT (arg = deployment salt).
- DEVICE_SEEN `kind`: 1 = BLE_OTHER, 2 = BLE_APPLE, 3 = BLE_FINDMY, 4 = BLE_GOOGLE, 5 = WIFI_PROBE.

### Gateway → host (one JSON object per line over USB serial, 921600 baud)
```json
{"type":"beacon","src":3,"seq":120,"hops":1,"rssi_last":-58,"batt_mv":0,"floor_db":-22,"nbrs":[[1,-55],[2,-71]]}
{"type":"feat","src":3,"seq":121,"hops":1,"rssi_last":-58,"t_ms":51234,"rms_db":-21,"low_db":-128,"voice_db":-128,"high_db":-128,"peak_db":-12}
{"type":"event","src":3,"seq":122,"hops":2,"rssi_last":-70,"t_ms":51800,"kind":"TAP_PATTERN","peak_db":-11,"voice_db":-128,"count":5,"conf":80}
{"type":"event","src":3,"seq":123,"hops":2,"rssi_last":-70,"t_ms":51790,"kind":"VIBRATION","peak_db":-11,"voice_db":-128,"count":14,"conf":90}
{"type":"event","src":3,"seq":124,"hops":2,"rssi_last":-70,"t_ms":53000,"kind":"VOICE_LIKE","peak_db":-10,"voice_db":-14,"count":38,"conf":42}
{"type":"range","src":2,"chirper":3,"delay_us":10450,"snr_db":18}
{"type":"device_seen","src":4,"seq":88,"hops":1,"rssi_last":-61,"t_ms":60000,"devs":[["9f3a01c2","BLE_APPLE",-52,14],["07bb4e10","WIFI_PROBE",-70,2]]}
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
- **RF device layer (`localize_devices.py`), the second heatmap layer:**
  - For each device hash, take the strongest signal at every node over the last 60 s.
  - **Position estimate:** a likelihood grid using the same signal-strength-to-distance model as node ranging, with a large σ because signals pass through rubble. As a fallback, use a weighted average of node positions with weight `10^(rssi/20)`.
  - **Candidate-survivor score.** Without filtering, every passer-by's phone would light up the map, so a device must be:
    1. **not in the baseline.** The UI's BASELINE button records every hash seen at the command post before the drop (the responders' own phones) and excludes them.
    2. **stationary.** The set of nodes that hear it, and their signal strengths, stay stable for ≥ 2 min. Responders walking past show up at changing nodes.
    3. **strong at one or two nodes**, e.g. `rssi_max > −65 dBm` at its nearest node.
  - **Address rotation:** phones change their BLE address about every 15 min. When a hash disappears and a new one appears within about 30 s, at the same nodes, with similar signal strength and the same kind, treat them as the same device.
  - **Fused "survivor likelihood"** = `1 − (1−P_acoustic)(1−P_rf)`, shown as its own layer. The acoustic and RF layers are independent evidence.
  - **Counts are reported separately**, e.g. "2 acoustic sources · 1 stationary device".
- **server.py:** FastAPI app.
  - `/ws` pushes state at 2 Hz.
  - POST `/cmd` sends HAIL, BLINK, RANGE, TXPOWER.
  - POST `/anchor` handles manual drag-to-place.
  - POST `/baseline` marks currently seen devices as friendly or background.
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
    - a candidate-survivor device → point (e.g. `a-u-G`), with the label "Device signal: BLE_FINDMY, −52 dBm near N3, stationary 4 min, ±3 m";
    - heatmap hotspots → circle or polygon drawing shapes, coloured by likelihood;
    - set `stale` short (about 30 s) so dead information ages out.

## 4. UI (`ui/`, a single static page)
- Canvas showing a floor-plan or drone-mosaic background image, with a metre grid.
- Nodes drawn as dots with their IDs. Mesh links drawn coloured by signal strength. Hop count shown.
- Heatmap overlay with **layer toggle: Acoustic / RF devices / Fused**. Source markers (🔊) and device markers (📱) with their counts.
- **Big buttons:** HAIL, BLINK IDs, RANGE, QUIET MODE, BASELINE (mark responder phones).
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
- Per node: BEACON about 30 B every 2 s, plus FEAT 16 B at 1 Hz, plus DEVICE_SEEN (about 13 + 7n B every 10 s, so about 8 B/s with 10 devices), plus events (16 B each; measured ~0.5–1 per second per node on the noisy hall floor, because nodes report every sound: ≤ 16 B/s). That's about **45–60 B/s per node**.
- Raw 16 kHz 16-bit audio (the reference paper's approach) is 32,000 B/s, about **700× more**.
- Flooding multiplies traffic by the node count. 50 nodes × 45 B/s × 50 is about 110 kB/s, well within what ESP-NOW can carry. Larger fields use TTL limits and cluster heads.
