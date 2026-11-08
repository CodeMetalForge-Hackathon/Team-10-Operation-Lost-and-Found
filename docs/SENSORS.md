# Sensors: what detects people, what each one outputs

**Audience:** the data scientist building ingest, localization, the heatmaps and the simulator.
**Contract:** message fields match `docs/ARCHITECTURE.md` §2 and `firmware/node/protocol.h`. If this doc disagrees with those, they win; flag the mismatch.
**Status key:** ✅ implemented and tested on hardware · 🟡 designed, firmware not written yet · ⚪ optional/stretch, not fitted.

---

## 0. Ground rules for all sensor data

| Topic | What to know |
|---|---|
| **Where data comes from** | Each field node (XIAO ESP32-C5) processes its sensors on board and sends **small summaries over the ESP-NOW mesh**. The gateway (S3, USB) prints **one JSON object per line**. **No raw audio ever reaches you.** |
| **Common fields** | Every message has `type`, `src` (node ID: 1–5 field nodes, 0 = gateway, 200 = drone), `seq` (per-node counter, wraps at 65535), `hops` (0 = heard directly by the gateway), `rssi_last` (gateway's signal strength for the last radio hop, in dBm). |
| **Timestamps** | `t_ms` is the **node's own clock** (milliseconds since boot). Clocks are **not synchronised** and reset on reboot. **Use `t_host` (Unix seconds, added by the laptop on arrival) to align nodes.** Arrival jitter is about ±30 ms: a 0–20 ms random relay delay per hop, plus USB. Use `t_ms` only for ordering and intervals *within* one node. |
| **Audio units** | All `*_db` audio fields are **dBFS**: `20·log10(level / ADC full scale)`, as int8. 0 is the loudest possible; quiet rooms sit around −50 to −60. **Each node's mic and amplifier has a different gain**, so the same sound reads differently at different nodes. Correct this with a per-node offset `g_i`, measured by having every node hear one buzzer chirp (§5). |
| **Positions** | Sensors don't know where they are. Node positions come from the localization layer: hand-measured or camera anchors, acoustic ranging, and signal strength as a weak hint. Ground truth for recorded runs is in `data/*.meta.json`. |
| **Signal strength ≠ distance** | Measured on our floor (`data/rssi_calibration.csv`): −40 dBm at 1 m, −46 at 2 m, −44 at 4 m, −44 at 8 m. The fitted path-loss exponent is **0.3**, so signal strength can't measure distance indoors. Treat it as "which node is closest" or "is it in range", with σ ≥ 6 dB. |
| **Missing data** | Broadcast packets can be lost, with no retries. Gaps in `seq` mean lost packets. A node with no BEACON for more than 6 s is "lost" (see the dropout in `data/beacons_line_2nodes.jsonl`, about 113–127 s). |

### What each sensor covers (victim condition)
| Victim condition | Sound sensor | SW-420 tap switch | BLE / Wi-Fi device scan | mmWave (hero node, ⚪) |
|---|---|---|---|---|
| Conscious, can shout | ✅ voice | — | ✅ if carrying a phone | ✅ if line of sight into a void |
| Conscious, too weak to shout, can tap | ✅ taps through air gaps | ✅ **taps through the structure** | ✅ if carrying a phone | ✅ |
| Unconscious, carrying a phone or watch | ❌ | ❌ | ✅ **only channel that works** | ✅ breathing |
| Unconscious, no device | ❌ | ❌ | ❌ | ✅ only if in line of sight; otherwise out of scope (say so to judges) |

These channels are **independent evidence**. Fuse them as `P = 1 − Π(1 − P_k)` per map cell, and show each layer separately as well.

---

## 1. Grove Sound Sensor (analog electret mic + amplifier): primary acoustic sensor 🟡

**Physical:** an electret microphone with an op-amp. Its analog output goes to ADC pin D0, sampled at **16 kHz** (so content up to about 8 kHz). It's mounted facing up out of the enclosure. Airborne sound only.

**Role:**
- Detect **voices and tapping** from conscious survivors.
- Provide the **loudness at each node** used for the acoustic heatmap (energy-based localization).
- Detect the reply after a **HAIL** (call-out-and-listen).
- Hear other nodes' **buzzer chirps** for acoustic ranging (§5).

**On-node processing:**
- 50 ms frames.
- Per frame: RMS level, plus energy in three bands (low 60–300 Hz, voice 300–3000 Hz, high 3–8 kHz).
- Noise floor tracked as an exponential moving average of quiet frames.
- Onset = frame > floor + 12 dB and rising fast.

### Output A: `feat`, a 1 Hz summary (continuous)
```json
{"type":"feat","src":3,"seq":121,"hops":1,"rssi_last":-58,"t_ms":51234,
 "rms_db":-40,"low_db":-50,"voice_db":-42,"high_db":-55,"peak_db":-30,"t_host":1762551234.512}
```
| Field | Meaning | Use |
|---|---|---|
| `rms_db` | Average level over the last 1 s | Background loudness map; noise monitoring |
| `low_db` / `voice_db` / `high_db` | Average energy per band over 1 s | **Voice vs. machinery vs. tapping.** Speech: `voice_db` dominates. Taps: broadband, short. Generators and rumble: `low_db` |
| `peak_db` | Loudest 50 ms frame in that second | Captures short sounds (taps) that the 1 s average smooths out |

### Output B: `event`, sent the moment something is detected
```json
{"type":"event","src":3,"seq":122,"hops":2,"rssi_last":-70,"t_ms":51800,
 "kind":"TAP_PATTERN","peak_db":-20,"voice_db":-35,"count":3,"conf":80,"t_host":1762551235.101}
```
| `kind` | Trigger | `count` | `conf` (0–100) |
|---|---|---|---|
| `LOUD` | A single onset (any loud transient) | 1 | Based on how far above the floor |
| `TAP_PATTERN` | **2–5 onsets with 150–700 ms spacing within 3 s** (a human knocking rhythm) | number of taps | Higher if the spacing is regular **and/or the SW-420 also fired (§2)** |
| `VOICE_LIKE` | `voice_db` above the floor for > 400 ms and dominating the other bands | 0 | Based on voice-band dominance |

- **`peak_db` in an event is the per-node loudness of *that* sound.** It's the input to localization, not FEAT.

### How to use it in fusion
1. **Group events across nodes:** events with `t_host` within about **300–500 ms** of each other are probably one acoustic event. Several nodes report the same knock, each with its own `peak_db`.
2. **Energy model per grid cell `p`:** `L_i = S − 20·log10(max(|p − x_i|, 0.5 m)) + g_i`. Solve `S` in closed form, then likelihood = `exp(−SSR / 2σ²)`, with σ around 4–6 dB indoors because of reflections.
3. **Nodes that heard nothing count too:** if the model predicts a node *should* have heard the event above its `floor_db` (from BEACON) and it didn't report one, penalise that cell.
4. **Accumulate with time decay**, then cluster peaks (DBSCAN) to get "N distinct sources", split by `kind`.

### Limits and failure modes
- **Reflections indoors** blur the energy map. Expect about 1–2 m accuracy with 4–5 nodes and a quiet room.
- **The hackathon floor is noisy.** The adaptive floor helps; run the demo in the hallway.
- **Answered (N2 bench test):** it is a waveform, but clipped at both ends at 3V3. **Band fields are always `-128` (= not available)**; `rms_db` and `peak_db` are valid (dBFS). `VOICE_LIKE` means any sustained sound. Field meanings as built: ARCHITECTURE.md §2.
- **Radio interference:** the node's own transmissions can put a spike into the analog signal. The firmware blanks samples during its own transmit bursts.

**Simulator:** a source at `p` with level `S`; each node reads `S − 20·log10(d) + g_i + N(0, 4 dB)`. Report an event only if above `floor_i + 12`. Use `g_i ~ U(−6, +6)` dB, a background floor of about −55 dBFS, and drop 5% of packets.

---

## 2. Grove Vibration Sensor SW-420: contact tap switch 🟡

**Physical:** a spring-contact vibration switch with a comparator and a threshold knob. It outputs a **digital 1/0** (vibration above threshold, or not), on pin D1 with an interrupt. It's **glued firmly to the case floor**, so it senses vibration carried **through the ground or rubble**, not through air.

**Role:**
- Detect **knocks on the structure**: a survivor hitting a pipe, slab or rebar. Rescuers already rely on this signal, and it travels through solid material better than through air.
- **Confirm** acoustic taps: a tap heard by the mic *and* felt by the SW-420 is very unlikely to be speech or room noise.

**Output (as built, 2026-11-07):** every burst is reported as an EVENT `VIBRATION` (`count` = edges ≈ strength, `peak_db` = mic level at that moment or the floor). It also feeds `TAP_PATTERN`:
- Its pulse timestamps are matched with mic onsets on the node.
- If the SW-420 fires on most onsets of a pattern, **`conf` goes up**.
- **Built:** if the SW-420 alone sees a tap rhythm while the mic sees nothing (deep in the structure), the node still sends `TAP_PATTERN` with `peak_db` at the mic floor and `conf` capped around 50. Read **`TAP_PATTERN` with `peak_db` ≈ the node's floor** as **"felt through the structure, not heard"**.

**How to use it:**
- It has no amplitude, so it **can't help with energy localization.**
- Use it as **evidence weight** (higher `P_acoustic` at that node), and as a **proximity hint**: a structure-borne tap felt at one node is probably near that node.

**Limits:**
- Binary output, sensitive only within about 1 m on a floor; on concrete it depends on the threshold.
- **Footsteps and dropped objects trigger it.** The rhythm requirement (2–5 regular taps) filters most of these.
- The threshold knob differs per node, so nodes aren't comparable with each other.

**Simulator:** for a source within about 1 m of a node, the SW-420 fires on each tap with p ≈ 0.8. Otherwise add rare false pulses (about 1 per minute) during "responder walking" periods.

---

## 3. BLE device scan: phones, watches, earbuds (built-in radio, $0) ✅

**Physical:** the node's own 2.4 GHz radio, scanning **passively** (receive only) for Bluetooth Low Energy advertisements. **2 s of scanning, about twice per 10 s window**, sharing the radio with the mesh. Phones and wearables advertise even with **no Wi-Fi or cell network**. **iPhones keep sending Find My beacons for up to about 24 h after powering off** (iPhone 11+, iOS 15+).

**Role:**
- **The only channel that finds unconscious or silent victims** who carry a device.
- Independent of sound and of noise.

**Output: `device_seen`, every 10 s (if anything was seen)**
```json
{"type":"device_seen","src":1,"seq":9,"hops":0,"rssi_last":-44,"t_ms":22494,
 "devs":[["9807ad8c","BLE_APPLE",-59,1],["d82bab54","BLE_OTHER",-62,1]],"t_host":1762551300.2}
```
Each `devs` entry is `[hash, kind, rssi_max, count]`:

| Item | Meaning |
|---|---|
| `hash` | 8 hex characters = FNV-1a hash of (device Bluetooth address + deployment salt). **Never the raw address** (privacy). **The same device gives the same hash at every node** (same salt), so you can **join on hash across nodes.** |
| `kind` | `BLE_APPLE` (Apple manufacturer ID `0x004C`), `BLE_FINDMY` (Apple offline-finding beacon: a strong victim signal because it works when the phone is off), `BLE_GOOGLE` (Fast Pair / Find Hub service `0xFE2C`), `BLE_OTHER` (watches, earbuds, laptops, beacons…). The classification is unverified on real phones; we're testing it. |
| `rssi_max` | Strongest signal heard from that device by **this node** in the window, in dBm. Only devices ≥ **−80 dBm** are kept. |
| `count` | **Number of scans in the window that heard the device** (the BLE library de-duplicates within a scan), so it's 1–2 with the default settings. Treat it as a presence count, not an advertising rate. |

- **At most 20 devices per message, the strongest 20.** The node tracks up to 96 per window and evicts the weakest when full.

**Measured at the venue (tested ✅):**
- About **96+ distinct devices stronger than −80 dBm at one node within 10 s**: the hackathon's phones, watches and laptops.
- Many phones **change their Bluetooth address** every few minutes (Android sometimes more often), which inflates the counts.
- The mesh still worked while scanning (gateway `rx_dropped` = 0).

### How to use it: the RF layer (`localize_devices.py`)
1. **Join across nodes by `hash`.** For each device, the vector of `rssi_max` per node over the last 60 s.
2. **Position estimate:** don't trust signal strength as distance (exponent ≈ 0.3 here). Use **"strongest node"**, or a **weighted average** of node positions with weights ∝ `10^(rssi/20)`. Report ±3 m or more.
3. **Candidate-survivor score.** All three conditions, or the map fills with passers-by:
   - **Not in the baseline.** BASELINE (UI button) records every hash seen at the command post before deployment, meaning responders' phones, and excludes them.
   - **Stationary.** The set of nodes that hear it, and their signal strengths, stay roughly stable (±6 dB) for **≥ 2 min**.
   - **Close to one node:** `rssi_max > −65 dBm` at its strongest node, and much weaker elsewhere.
   - Boost `BLE_FINDMY` and `BLE_APPLE`/`BLE_GOOGLE` over `BLE_OTHER` (more likely a person's phone).
4. **Address rotation:** when a candidate hash disappears and a new hash appears within about 30 s, at the same strongest node, with similar signal strength and the same `kind`, merge them into one track.
5. **Output:** "M stationary candidate devices" plus a 📱 marker at the estimate.

**Limits:**
- Reinforced concrete absorbs 10–20+ dB per layer, so expect detection within only a few metres through real rubble. (A wooden desk caused no loss in our test, so this can't be confirmed indoors.)
- The device count is approximate because of address rotation.
- Airplane mode or a dead battery means no signal (except Find My after power-off).

**Measured A/B test (✅, `data/ble_quiet_node2_*.jsonl`):**
- With node 2 in a quiet hallway, the strongest background device was **−59 to −66 dBm**.
- With William's iPhone touching node 2, it read **−33 to −39 dBm in every report** (hash `9dee7325`), **about 25–30 dB above the background**.
- Node 1, near the laptop, heard the **same hash** at −42 to −57 dBm, which confirms that matching devices across nodes by hash works.
- The hash was stable for several minutes. His wearables (`3cb7eb8b`, `d7c026ed`) were detected too.
- **Near the crowded laptop area, the same phone was not distinguishable** (everything there reads −37 to −46 dBm), so the "strong at one node" rule needs nodes away from crowds.

**Demo:** the "victim" phone sits **on the floor right next to one node** (expect about −30 to −45 dBm), which is far stronger than any phone at a desk.

**Simulator:**
- 50–100 background devices at −70 to −80 dBm that come and go randomly.
- 3–5 "responder" devices that move across nodes.
- 1 "victim" device fixed near one node at about −40 dBm (±4 dB noise), changing its hash every 10 min.
- Every node uses the same hash for the same device.

---

## 4. Wi-Fi probe sniffing (built-in radio) 🟡 (cuttable)

**Physical:** the same radio in promiscuous mode, catching **Wi-Fi probe requests**: phones with Wi-Fi on keep searching for known networks even when none exist. We only see the subset sent on channel 1, the mesh channel.

**Output:** the same `device_seen` message with `kind: "WIFI_PROBE"`. Fields mean the same as for BLE.

**Use:** as a second RF source, merged into the RF layer. **Expect few and sparse hits.** Phones probe rarely with the screen off and use random addresses. It's lower priority than BLE and can be cut.

---

## 5. Support data (not people sensors, but needed to use the sensor data)

### BEACON: node health and mesh graph, every 2 s ✅
```json
{"type":"beacon","src":2,"seq":594,"hops":0,"rssi_last":-81,"batt_mv":0,"uptime_s":1191,"floor_db":0,"nbrs":[[1,-32]]}
```
| Field | Use |
|---|---|
| `nbrs` `[[id, rssi_dBm], …]` | Who each node hears directly, and how strongly (smoothed). **Mesh graph, connectivity, weak signal-strength range hints** |
| `floor_db` | Node's current audio noise floor in dBFS. Use it for **"why didn't this node hear it"** in the energy model. **Currently 0 = not implemented yet** 🟡 |
| `batt_mv` | Battery voltage in millivolts. **Currently 0 = not implemented yet** 🟡 |
| `uptime_s` | Seconds since boot. **A drop means the node rebooted**, so its `t_ms` reset |

### RANGE: acoustic distance between nodes (buzzer + sound sensor) 🟡
```json
{"type":"range","src":2,"chirper":3,"delay_us":10450,"snr_db":18}
```
- When the operator presses RANGE, nodes take turns chirping their **Grove Buzzer** (about 2.3 kHz) **at the same moment as they send a radio packet**.
- Every other node measures the delay between the radio packet and the sound arriving.
- **Distance = 343 m/s × (`delay_us` − bias) × 10⁻⁶.** Calibrate `bias` (radio and buzzer latency) once at a known distance.
- Expected σ is about 0.3 m. Discard results with `snr_db` < 10.
- These are the **strongest node-to-node distance terms** for the node-position solver.
- The same chirps give the **per-node gain offsets `g_i`** for §1: compare each node's received level against its distance.
- **Depends on** the sound sensor giving a real waveform (§1 open question).

### Buzzer and LED (actuators, no data)
- **HAIL:** every node buzzes, then listens for 10 s. TAP_PATTERN / VOICE_LIKE events in that window get **higher prior weight**: a reply to a call-out.
- **BLINK_ID:** the LED blinks the node's ID for the overhead camera, giving position anchors in GPS-denied mode.
- Commands appear in recordings as `{"type":"host_cmd","text":"CMD HAIL 0 255"}`, so you can mark the HAIL windows.

---

## 6. Optional / not fitted (know they exist; don't build for them first)

| Sensor | Status | If fitted, what it would send | Role |
|---|---|---|---|
| **mmWave radar** (LD2410-class, one hero node, UART on D6/D7) | ⚪ | `event` `RADAR_PRESENCE`, with `conf` = presence confidence. Proposed: `count` = distance in decimetres. Confirm with William first | **Breathing / stationary-person** detection in line of sight (a void opening). Can't see through concrete |
| **3-axis accelerometer** (Grove MMA7660, I2C D8/D9) | ⚪ reserved | `event` `VIBRATION` (`peak_db` = dB re 1 mg, `count` = jolts) and `MOVED` (`count` = orientation 0 up / 1 upside down / 2 side, `conf` = tilt change in degrees) | Node **landed mic-up?** If `MOVED` arrives, **re-localize that node and distrust its old position.** Too coarse for taps |
| **Gas sensor** (MQ-2 / Grove) | ⚪ | `event` `GAS` | Responder **hazard**, not people |
| **PIR motion** | not used | — | Only sees warm bodies moving in line of sight; can't see into voids |
| **Thermal camera HT-203U** | ⚪ low priority | Not on the mesh; drone/Pi imagery if it works as a webcam | Surface victims, night search. **Can't see through rubble** |
| **Drone Pi camera** | 🟡 | Node position anchors from LED-ID (not people). Hailo person detection is stretch | Node localization in GPS-denied mode |

---

## 7. Data you can use today

| File | What | Good for |
|---|---|---|
| `data/rssi_calibration.csv` | Node-to-node signal strength at 0.1 / 1 / 2 / 4 / 8 m on the floor, behind a desk, and a 10 cm shift | Signal-strength noise model (exponent ≈ 0.3, P0 ≈ −42 dBm) |
| `data/beacons_line_2nodes.jsonl` + `.meta.json` | 4 min of real gateway output: gateway at 0 m, nodes at 3 m / 6 m in a line; BLINK, low transmit power, **node 1 dropout about 113–127 s**, HAIL | Ingest/replay, neighbor graph, **dead-node detection**, `t_host` alignment |
| *Coming:* a BLE dataset with a phone at a known spot; first sound-sensor recordings | | RF layer; energy-model tuning |

**Replay:** `for line in open(path): msg = json.loads(line)`, dispatching on `msg["type"]`. Ignore `"log"` and `"gw"` (gateway status: `rx_dropped` should stay 0).
