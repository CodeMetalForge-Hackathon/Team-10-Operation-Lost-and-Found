# Plan: Sat 13:00 → Sun 12:00 (23 h)

**Owners:**
- **W** = William: firmware, hardware, integration and demo owner.
- **D** = data scientist: simulator, fusion math, detection.
- **E** = econ/defense teammate: TAK, scenario, operations concept, deployability and cost case, pitch, procurement, mentor interviews.

**Golden rule:** by 22:00 Saturday an ugly end-to-end path runs: real node → gateway → fusion → dashboard + TAK. Everything after that is improvement.

| Time | W (firmware/HW) | D (fusion/sim) | E (TAK/ops/pitch) | Done when |
|---|---|---|---|---|
| **13:00–13:45** | Read docs; check out hardware (library: extra ESP32s, I2S mics, buzzers, LEDs, GPS, mmWave, power banks) | Read `ARCHITECTURE.md` §2–3; set up Python env (`numpy scipy fastapi uvicorn pyserial pytak scikit-learn`) | Register at tak.gov and **download WinTAK-CIV now** (large download); ask staff about drone slots and indoor flying | Hardware in hand; WinTAK downloading |
| **13:45–18:00** spikes | Arduino core ≥ 3.3; **S3↔C5 ESP-NOW broadcast + RSSI**; gateway prints JSON lines; I2S mic → RMS/band dB on serial | **Simulator** (`sim/`) emitting exact gateway JSON + ground truth; `localize_nodes.py` (anchors + ranges + RSSI); `localize_sources.py` heatmap, all on simulated data | `tak.py`: CoT hello world showing in WinTAK (node markers + one "possible survivor"); local→lat/lon; Micro Center run if needed; **interview 2+ SOF mentors** on the scenario | Each piece works alone |
| 18:00 | **Dinner checkpoint (15 min):** demo each spike; freeze message format | | | |
| **18:00–22:00** thin E2E | Flooding (TTL, de-dup); FEAT + BEACON + onset/LOUD events on 4 nodes; CMD downlink (PING, BLINK) | `server.py` + `ui/` canvas: nodes, links, heatmap, buttons; serial ingest; wire real data | Wire `tak.py` to fusion state; write the operations-concept storyline; draft the cost/bandwidth/power slide | **Tap near a node → heatmap + TAK marker move to the right spot** |
| **22:00–02:00** | TAP_PATTERN + VOICE_LIKE detection; HAIL (buzzer sync); **acoustic ranging spike (timebox 2 h)**; TX-power-down multi-hop | Per-node gain calibration; DBSCAN source count; record + replay runs to `data/`; error metrics vs. tape-measured truth | Pitch deck v1 (problem → scenario → demo → PACE → deployability → ask); README "what existed before" | Runs 3× in a row |
| **02:00–08:00** harden + sleep shifts | Sleep 05:00–07:30. Enclosures (weeble cups); drone payload assembled; LED-ID blink | Sleep 02:30–05:00. `drone/ledid.py` from overhead camera (or hand-measured anchors as fallback); tune thresholds in the hallway | Sleep 00:30–04:00. Then rehearse the 15-min table walkthrough and 10-min finals talk | Measured: source error, time to detect, node-localization error |
| **08:00–10:00** | **Simulated drone pass:** carry the Pi + camera + bridge overhead, drop nodes, record LED-ID + relay footage. *Optional:* Cetus X drops one bare node (with staff, daylight) for the video | Deploy fusion to the Pi 5 (optional); final tuning | Film the **backup demo video** | Video recorded |
| **10:00–11:00** | **Feature freeze.** Bug fixes only | Clean `data/` replay demo as fallback | Finalize deck + README | Repo pushed |
| **11:00–11:45** | Final push & submit | | | **Submitted before 11:45** |
| 12:00–14:00 | Table judging: one person at the table at all times. Live demo + replay fallback | | | |
| 14:45 | Finals (if selected): 10 min | | | |

## Cut list (cut from the bottom first if behind)
1. ~~Hailo person detection / HT-203U thermal~~
2. ~~Time-difference-of-arrival (TDoA) source localization~~
3. ~~Cetus X single-node drop clip~~
4. ~~Optical LED-ID~~ → hand-measured anchors entered in the UI
5. ~~Acoustic ranging~~ → signal strength + anchors only
6. ~~mmWave / gas hero node~~
7. **Never cut:** mesh → gateway → heatmap → TAK, HAIL, tap detection, simulator/replay fallback.

## Checkpoints (all three people, 10 min max)
18:00 · 22:00 · 02:00 · 08:00 · 10:00
