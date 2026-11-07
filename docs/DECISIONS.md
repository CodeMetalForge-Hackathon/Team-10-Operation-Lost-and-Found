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

## What existed before this weekend
- Open-source: Arduino-ESP32 core, ESP-NOW, NumPy/SciPy/scikit-learn, FastAPI, pytak, TAK/WinTAK.
- Pretrained models (if used): YAMNet (Google AudioSet).
- Everything else in this repo was built during the event.

## What worked / didn't / unfinished
(keep this updated; it answers judge question #3)
