# Decision Log
One line per decision: date/time, decision, why. Newest at the bottom.

- 2026-11-07 13:00: Scenario is a **collapsed structure / debris field**, for **responders** (not a victim-worn device). Why: matches the panel's "no batteries/cables on people" point and the speakers' guidance to pick one scenario.
- 2026-11-07 13:00: **Nodes do the processing on board and send small feature/event packets; no raw audio streaming.** Why: the mesh bandwidth and battery can't carry raw audio (~900× more data).
- 2026-11-07 13:00: **ESP-NOW flooding mesh on a fixed 2.4 GHz channel 1** (no painlessMesh, no Wi-Fi access point). Why: no infrastructure needed, simple, works across the S3 and C5 boards.
- 2026-11-07 13:00: **Node localization uses a PACE stack:** anchors (GPS drop log or camera LED-ID) → acoustic ranging → signal strength → manual. Why: signal strength alone is unreliable at ground level and indoors; the panel asked for primary/alternate/emergency plans and adaptability.
- 2026-11-07 13:00: **Source localization by energy-based likelihood heatmap**; TDoA is stretch. Why: TDoA needs sub-ms clock sync.
- 2026-11-07 13:00: **TAK (WinTAK via CoT multicast) is the primary operator output**; the web dashboard is secondary. Why: the panel said to integrate with existing systems rather than bring a new widget.
- 2026-11-07 13:00: **Develop on the Windows laptop; Pi 5 rides on the drone** (and can host fusion later). Why: speed of development; adaptability story.
- 2026-11-07 13:00: Board allocation: S3 = gateway + drone bridge, C5 ×4 = field nodes. Why: S3s are more reliable for USB serial; maximizes field nodes.

- 2026-11-07 ~13:30: **The drone is simulated by carrying the Pi 5 payload by hand** and dropping nodes manually at logged points. Why: the Cetus X payload is about 15–30 g and the Pi 5 payload weighs well over 100 g. The architecture doesn't change: the drone is just another mesh node with a camera. A real Cetus X single-node drop is an optional video clip.
- 2026-11-07 ~13:30: The HT-203U thermal camera is low priority. Integrate it only if it works as a UVC webcam.

- 2026-11-07 ~14:00: **Add passive phone/device detection** (BLE advertisements + Wi-Fi probe requests) as a firmware feature: new `DEVICE_SEEN` message type 7 and a second heatmap layer (RF), fused with acoustic. Why: it detects victims who are unconscious or can't tap (phones, watches and iPhone powered-off Find My beacons transmit with no network), uses the existing ESP32 radio at $0 extra, and adds a strong "novel combination" for ideation.
- 2026-11-07 ~14:00: Device detection is **receive-only, with hashed IDs and no cellular transmission**. Why: privacy and legality (a fake cell tower needs licensed spectrum; it is mentioned only as a production path).
- 2026-11-07 ~14:00: Priority order is now DEVICE_SEEN before acoustic ranging. Why: device detection is a new detection channel with high demo value; node localization already has fallbacks (anchors and signal strength).
- Known risk: the demo room is full of other teams' phones. Mitigations: BASELINE exclusion, stationarity, strong-signal-at-one-node scoring. Demo the hidden phone under boxes on the floor (strong at one node).

- 2026-11-07: **Mic = Adafruit ICS-43434 I2S MEMS breakout (#6049), the same model on all 5 C5 nodes.** Why: available at Micro Center today, digital I2S with fixed gain (no automatic gain control), works with ESP32. One mic and one piezo per node.

- 2026-11-07 ~16:30: **Measured signal strength on the demo floor** (`data/rssi_calibration.csv`): −40 dBm at 1 m, −46 at 2 m, −44 at 4 m, −44 at 8 m; a wooden desk made no difference. The fitted path-loss exponent is about 0.3, so **signal strength can't measure distance at room scale.** It's a weak term in the solver (σ ≥ 6 dB) and serves only as a neighbor graph. Node positions come from anchors (camera, manual) and acoustic ranging. The mesh range is ample (about −44 dBm at 8 m), so demonstrating multi-hop relaying requires the lowest transmit power.
- 2026-11-07 ~16:45: **The gateway sends each CMD 3× with the same sequence number** (nodes de-duplicate). Why: ESP-NOW broadcast has no acknowledgement or retry. Delivery went from occasional misses to 9/10 on a weak link.
- Gotchas: on `XIAO_ESP32S3_Plus`, the option `CDCOnBoot=cdc` means *Disabled*, so `tools/flash.py` uses the board defaults for the S3. WinTAK and Bambu Studio poll COM ports and break flashing.

- 2026-11-07 (evening): **Sensors switch to Grove modules: Grove Sound Sensor (analog, D0) replaces the Adafruit ICS-43434 I2S mic; Grove Vibration SW-420 (digital, D1) replaces the piezo disc; Grove Buzzer (D4) is the chirp/HAIL source.** Why: we couldn't get the Adafruit mic, and the Grove kit has enough modules on hand. Costs: lower audio quality, and taps give timing only, no amplitude. The message format is unchanged. If the sound sensor turns out to output loudness only, band energies and chirp ranging degrade and node positions lean on anchors.
- 2026-11-07 (evening): All Grove modules are powered from **3V3, not 5V**. Why: the XIAO's 5V pin only carries USB power, so it is dead on battery.
- 2026-11-07 (evening): Grove Speaker → command post/hero node HAIL only; Grove Vibration Motor → "fake survivor" knock prop; Grove Mini PIR not used (can't see into voids).
- 2026-11-07 (evening): **3D-printed node case** (`hardware/enclosure/node_case.py`, parametric, ~102 x 66 x 15 mm): all modules flat on the floor in corner fences, lid openings over the mic and buzzer, USB-C slot for charging with the lid on, FPC antenna recess away from the LiPo. Why: repeatable build for 5 nodes; flat layout is simplest to assemble and lets the SW-420 feel taps through the case floor.
- 2026-11-07 (evening): **No accelerometer (IMU) on the nodes for now; sensors stay sound sensor + SW-420.** Why: the Grove ±1.5 g MMA7660FC is 6-bit at ≤ 120 samples/s, so it adds almost nothing to tap detection; its value (orientation, "node moved") isn't core to the demo and would cost wiring, firmware, sim, fusion and case time before the deadline. Stretch: one node on I2C D8/D9 if the core demo is solid.
- 2026-11-07 (evening): EVENT kinds 6 = VIBRATION and 7 = MOVED stay in the contract as **reserved** (additive, unused), so an accelerometer can be added later without a format change.
- 2026-11-07 (late): **No external LED on the nodes** (only one found); the on-board user LED does status/`BLINK_ID`. Camera LED-ID stays cut; anchors are hand-measured. D5 is now spare.
- 2026-11-07 (late): **Grove Sound Sensor is clipped at both ends at 3V3 (N2 bench test); accept and design around it**: 16 kHz sampling, clip counting as a "very loud" flag, mean-absolute-deviation level, band energies not relied on, detection blanked during the node's own beeps, demo sources ≥ 1 m from nodes. Why: the fix (5 V supply + divider) needs USB power and untested hardware changes on 5 nodes; energy and onsets are enough for the heatmap and taps.
- 2026-11-07 ~21:30: **Node firmware reports every sound and every movement with its strength; fusion weighs it** (no classification gates on the node). Why: in a collapse, any sound or movement matters, and the fusion layer sees all nodes at once. Only safeguard: onsets within 250 ms merge into one LOUD, so a noisy room can't flood the mesh.
- 2026-11-07 ~21:30: **Contract (team must know): EVENT `VIBRATION` (6) now carries SW-420 bursts** (`count` = edges ≈ strength, `peak_db` = mic level or floor); **`VOICE_LIKE` (3) means any sustained sound**, with `voice_db` = average level and `count` = duration in 100 ms; **all dB fields are dBFS re 2048 counts; FEAT band fields are always `-128`.** No struct changes. Field meanings: ARCHITECTURE.md §2.
- 2026-11-07 ~21:30: Audio runs in its own task with ADC DMA at 16 kHz and sends its own packets. Why: the C5 is single-core and BLE scans block `loop()` for 2 s.
- 2026-11-07 ~21:30: HAIL = 3 beeps; nodes ignore their sensors until 2.5 s after their own last beep. Why: other nodes may receive the command up to ~2 s late (during a BLE scan) and their beeps would otherwise be reported as taps.

## What worked / didn't / unfinished
- ✅ STEP 3 sensor firmware on N2 (2026-11-07 ~21:20): 16 kHz DMA audio with zero ADC errors; LOUD / VOICE_LIKE / VIBRATION / TAP_PATTERN events; 5 firm taps → `TAP_PATTERN count=5 conf=80` (3 felt + heard, 2 heard only); HAIL beeps with self-blanking. SW-420 (after re-plugging and re-tuning) feels roughly half of firm knuckle taps at 20–30 cm on a bare table and stays silent at rest; a mic-only knock pattern still arrives as `TAP_PATTERN conf=50`.
- ✅ BLE phone detection on the C5 (2026-11-07 ~17:40): an iPhone touching a node in a quiet hallway read −33 to −39 dBm, against a background of −59 to −66 (+25–30 dB). The same hash was seen at a second node, more weakly. ❌ Near the crowded laptop area the phone was indistinguishable (dozens of Apple devices at about −40 to −45), so the demo places the victim node away from people. Gateway settings rebroadcast verified: a rebooted node re-learned its TX power within 19 s.
- ✅ C5↔C5 ESP-NOW, C5→S3 gateway JSON, multi-hop forwarding (hops=1 observed), gateway→node commands.

## What existed before this weekend
- Open-source: Arduino-ESP32 core, ESP-NOW, NumPy/SciPy/scikit-learn, FastAPI, pytak, TAK/WinTAK.
- Pretrained models (if used): YAMNet (Google AudioSet).
- Everything else in this repo was built during the event.

