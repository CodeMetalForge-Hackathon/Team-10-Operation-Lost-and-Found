# Project Brief

## Problem
After a building collapses (missile strike, earthquake), survivors are trapped in voids under rubble. Search teams today rely on a few kinds of tools:
- **Call-out-and-listen:** everyone goes quiet, someone shouts, and searchers listen for tapping.
- **A small number of expensive acoustic and seismic listening devices**, operated one position at a time by trained specialists.
- **Search dogs.**
- **Cameras on poles** pushed into voids.

All of these are slow and point-by-point, and they need people standing on unstable rubble. GPS doesn't work inside or under the structure, the cell network is down or overloaded, and responders are exhausted.

## User
The **search and rescue team leader / drone operator** at a collapsed structure: an urban search and rescue (USAR) team, a military unit responding to a strike, or a fire department. They already carry TAK (ATAK on phones, WinTAK on laptops).

## Our capability (the edge)
**A disposable acoustic sensor mesh you can drop, which turns the whole debris field into one listening array at once and puts the result on the map they already use.**

1. **Drop:** a drone (or a person) scatters cheap nodes (target about $15 each) across the debris field. They are self-righting, last 1–2 hours, and are meant to be thrown away.
2. **Self-organize:** the nodes form an ESP-NOW mesh with no infrastructure. The mesh repairs itself when a node dies, and a reduced transmit power demonstrates multi-hop relaying.
3. **Self-locate (adaptive, PACE plan: primary, alternate, contingency, emergency):**
   - **Primary:** absolute anchors. These come from the drone's GPS drop log or, when GPS is denied, from the drone camera seeing each node's LED blink its ID.
   - **Alternate:** **radio-triggered acoustic ranging**. Each node chirps its buzzer at the same moment it sends a radio packet. The others time how long the sound takes to arrive, which gives node-to-node distances to about 0.3 m with no clock sync. The node reuses its own microphone, so this costs nothing extra.
   - **Contingency:** signal-strength (RSSI) ranging across the neighbor graph, plus the drone acting as an extra node.
   - **Emergency:** a responder drags the node to its position in TAK or the dashboard.
4. **Listen:** each node tracks its own background noise level and reports **every sound and every felt vibration** with its strength, plus **tap patterns** and sustained sound (voices, moaning). The operator can press **HAIL**: every node buzzes in sync ("tap three times if you can hear this"), then the network listens. This automates the call-out-and-listen procedure rescuers already use.
5. **Sense devices:** each node also **passively listens for phones and wearables**: BLE advertisements and Wi-Fi probe requests. These transmit even with no network, and iPhones keep sending Find My beacons for hours after powering off. This finds victims who are **unconscious or too weak to tap**, at $0 extra hardware. Receive-only, with hashed IDs.
6. **Fuse:** the fusion host combines loudness across nodes into an **acoustic likelihood heatmap**, adds an **RF device layer** (stationary, non-responder devices), and fuses them. Repeated detections are clustered into "N acoustic sources · M stationary devices (with confidence)".
7. **Deliver:** sends Cursor-on-Target (CoT) to **TAK**, and only small events travel over the mesh. A low-bandwidth, degraded-comms design is built in. A web dashboard shows the full picture for the operator.

### Mission objectives covered
- **OBJ.01 Locate:** primary.
- **OBJ.02 Detect life:** primary; hazards are stretch.
- **OBJ.04 Deliver over degraded comms:** primary.
- **OBJ.03 Map changing conditions:** secondary. The mesh and heatmap update live, and a node that dies or goes silent is itself information.

## Assumptions (say these out loud to judges)
- Collapsed or partially collapsed structure. The search area is about 30 × 30 m in the real world and about 8 × 8 m on the demo floor.
- No GPS under the structure. The drone may have GPS above it, and **the system works with or without it**.
- Survivors can make some sound (tapping, voice) at least intermittently. Unconscious and silent victims are out of scope for audio; mmWave radar and thermal are listed as extensions.
- Responders can enforce a quiet period, which is standard USAR practice.
- Node positions accurate to about 1 m and source positions to about 2 m are good enough to direct a dig or camera team. We **trade precision for portability and cost** (the SEAL panelist explicitly endorsed this trade).
- Security and encryption are out of scope for the hackathon. Production would need encrypted, low-probability-of-intercept links, which the panel stressed.

## Demo metric (measured against tape-measured ground truth)
- **Source localization error:** distance from the heatmap peak to the hidden sound source (a phone playing tapping or voice under boxes). Target **≤ 2 m**.
- **Time to detect:** from HAIL to the marker appearing in TAK. Target **≤ 15 s**.
- **Node self-localization error:** for each method (camera, acoustic ranging, signal strength). Report them all honestly.
- **Bandwidth:** bytes per second per node over the mesh, compared with streaming raw audio as the reference paper does.

## Prior work we build on (and how we differ)
- **Poudel & Assaad 2025, construction-site acoustic IoT:**
  - What they did: ESP32 + MEMS microphones streaming raw audio over Wi-Fi to a Jetson; a neural network on mel spectrograms; 89% accuracy across 14 classes; 30–50 ms inference.
  - What we reuse: ESP32 + MEMS microphone nodes and the edge/cloud split.
  - How we differ: we have **no Wi-Fi infrastructure**, **do the processing on board and send only events (no raw audio streaming)**, **fuse many nodes to *locate* the source** rather than just label sounds at one microphone, and **the nodes locate themselves**.
- **Commercial acoustic and seismic rubble-search devices:** a handful of sensors, placed by hand, expensive, operated by experts. Ours is cheap, dropped by drone, many nodes at once, and outputs to TAK.
- **Existing systems used:** TAK / Cursor-on-Target (plain CoT XML over UDP, standard library; works with WinTAK, ATAK and iTAK with no plugin or TAK Server), ESP-NOW, and optionally a pretrained audio classifier (YAMNet). All open source and declared.

## Speaker-feedback alignment (from the Friday panel)
- "Don't bring a new widget, integrate": our output goes into **TAK**, the map responders already have open. Standard CoT symbols (friendly sensor nodes, an unknown contact labelled "T10 DIG HERE?"), no plugin and no server, and it works over local multicast with no internet. Responders learn nothing new, and every TAK user on the network can see, share and route to the estimate. Details: `docs/TAK.md`.
- "No batteries or cables on people": nothing goes on the victim or the operator.
- "Primary, alternate, emergency plan": our localization stack *is* a PACE plan.
- "Adapt to changing conditions": the mesh repairs itself, the system has GPS and GPS-denied modes, and the drone is optional.
- "Measurable outcomes": the demo metric above.
- "Red light or full map, depending on scenario": TAK gets a few simple markers for the field team, and the dashboard gets the full heatmap for the operator.

## Questions to have answered at the table
1. **Show it working:** run the live mesh, tap under the boxes, and watch the heatmap and TAK marker appear.
2. **What existed before vs. built here:** see the README section (libraries and the pretrained model are declared; everything else was built this weekend).
3. **What worked, what didn't, what's unfinished:** keep an honest list in `docs/DECISIONS.md`.
4. **Off the laptop:**
   - the fusion host runs on a Pi 5, either on the drone or at the command post;
   - parts cost per node;
   - battery math;
   - bandwidth budget;
   - a moulded self-righting shell and seismic (piezo) contact sensor;
   - LoRa backhaul and encryption for production.
