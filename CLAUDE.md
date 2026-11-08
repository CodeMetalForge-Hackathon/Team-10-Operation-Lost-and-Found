# CLAUDE.md — Team 10, Code Metal Forge 2026 ("Operation Lost and Found")

Shared context for every teammate's Claude Code session. Read this first, then the file in `docs/` for your area.

## The one-sentence demo
**Drop a handful of cheap, expendable acoustic sensor nodes onto a collapsed structure; they mesh with each other without any infrastructure, work out where they are, listen for trapped survivors (tapping, voices), and push a live "where to dig" heatmap to responders in TAK.**

## Hard facts
- **Deadline: Sunday Nov 8, 12:00 (hard cutoff).** Table judging 12:00–14:00 (about 15 min), finals 14:45 (10 min on stage, shared with USSOCOM).
- Judging: 4 equally weighted criteria, each scored 1–5: **real-world relevance, working live demo, deployability (path off the laptop: hardware, power, latency, bandwidth, reliability), ideation.**
- Only work done between Sat 10:00 and Sun 12:00 counts. **Commit early and often.** Keep `docs/DECISIONS.md` and the README honest about what existed before (open-source libraries, pretrained models).
- **Drones fly only with Code Metal staff, in daytime.**
- Team of 3: William (ME/EE/CS, firmware, hardware, integration owner), the data scientist (fusion math, detection, simulator), and the econ/defense teammate (TAK, operations concept, deployability and cost case, pitch).
- The demo is **indoors on an office floor**, with a hallway available for quieter tests. Indoors means no GPS, so the demo naturally runs our **GPS-denied mode**.

## Scenario (the assumptions we state to judges)
- A multi-story building has partially collapsed (missile strike or earthquake). Survivors are trapped in voids.
- There is no GPS inside or under the rubble, cell networks are down, and fixed comms are gone.
- Responders already use TAK.
- We help **the people searching**. We put nothing on the victim ("no batteries or cables on people").
- We trade precision for portability and cost: the goal is metre-level "dig here" guidance, not centimetre accuracy.

## Architecture in 30 seconds
- **Node** (ESP32-S3 or ESP32-C5, plus Grove sound sensor (analog mic), Grove SW-420 vibration (tap) switch and Grove buzzer, about $15):
  - runs on-board signal processing (noise floor, loudness, onsets, sustained sound, SW-420 taps, tap patterns) and **reports every sound and movement with its strength as small event packets, never a raw audio stream**; fusion decides what matters (field meanings: `docs/ARCHITECTURE.md` §2);
  - **also passively scans for phones and wearables** (BLE advertisements and Wi-Fi probe requests, receive only, hashed IDs) and reports them as `DEVICE_SEEN`.
- **Mesh:** ESP-NOW broadcast with flooding (rebroadcast with a hop limit, de-duplicated). No router, no infrastructure.
- **Gateway:** an ESP32 on USB serial to the fusion host. It prints JSON lines.
- **Fusion host** (develop on William's Windows laptop, deploy to the Pi 5 later; Python):
  - node localization, combining anchors, acoustic ranging and signal-strength ranging;
  - acoustic source heatmap, plus an RF device layer and a fused layer;
  - source clustering and count;
  - a web dashboard;
  - **Cursor-on-Target (CoT) output to WinTAK**.
- **Drone** (Pi 5 + Pi camera + an ESP32 bridge, plus GPS if available): an extra mobile mesh node. **For the demo it is carried by hand to simulate flight**, because the Cetus X only lifts about 15–30 g. With GPS it adds absolute anchors. Without GPS it acts as a relay and an overhead camera that spots the nodes' LED blinks to fix their positions.
- Full details are in `docs/ARCHITECTURE.md`.

## Rules for Claude sessions on this repo
- **The message format in `docs/ARCHITECTURE.md` is the contract between firmware, simulator and fusion.** Don't change it silently. If you must change it, update the doc and tell the team.
- Everything downstream of the gateway must run on the **simulator** (`sim/`) so that a dead board can't sink the demo.
- Prefer simple and working over clever and half-done ("a working, demonstrable slice over a half-finished whole").
- Timebox: if something is stuck for 90 minutes, cut it or ask a mentor.
- Windows laptop for development: Python 3.11+, Arduino IDE 2 / arduino-cli with **arduino-esp32 core ≥ 3.3** (needed for the ESP32-C5).
- Log significant decisions in `docs/DECISIONS.md` (one line each, with the reason).

## Docs map
| File | What's in it |
|---|---|
| `docs/PROJECT_BRIEF.md` | Problem, user, scenario, assumptions, demo metric, pitch angle, judge Q&A |
| `docs/ARCHITECTURE.md` | Components, message format, algorithms, TAK mapping, repo layout |
| `docs/HARDWARE.md` | Board allocation, wiring, parts to request or buy, cost per node, power |
| `docs/SENSORS.md` | **Every people-detecting sensor: physics, role, exact message output, how to fuse it, limits, simulator recipe** (for the data scientist) |
| `docs/PLAN.md` | Timeline with clock times, owners, checkpoints, cut list |
| `docs/DECISIONS.md` | Running decision log |
