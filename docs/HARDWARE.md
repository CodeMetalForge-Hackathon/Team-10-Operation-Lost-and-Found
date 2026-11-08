# Hardware

## Board allocation (we have 2× Seeed XIAO ESP32-S3 Plus and 5× Seeed XIAO ESP32-C5)
| Board | Role | Why |
|---|---|---|
| XIAO ESP32-S3 Plus #1 | **Gateway** (USB to the fusion host) | Mature support, reliable USB serial; stays at the command post |
| XIAO ESP32-S3 Plus #2 | **Drone bridge** (USB to the Pi 5) | Same reasons |
| XIAO ESP32-C5 ×5 | **Field nodes** 1–5, each with a **Grove Sound Sensor (analog mic) + Grove Vibration SW-420 (tap) + Grove Buzzer** | 8 MB PSRAM (enable under Tools → PSRAM), built-in LiPo charging and battery-voltage sensing, 11 GPIO, U.FL antenna. Run on 2.4 GHz channel 1 to talk to the S3s |

- **Pin budget per C5 node (3 of 11 GPIO):**
  - Grove Sound Sensor on an ADC pin;
  - Grove Vibration SW-420 on a digital interrupt pin;
  - Grove Buzzer (LEDC PWM).
  - No external LED (we only found one): status and `BLINK_ID` use the XIAO's on-board user LED (`LED_BUILTIN`).
- **An antenna must be attached to every board** (U.FL connector).

- **Four field nodes is the minimum** for 2-D localization with redundancy. **Ask the hackathon library for more plain ESP32s** (listed under "Additional Compute") so we can reach 6–8 field nodes.
- The gateway can also carry a microphone and act as an extra sensing node sitting at the command post.

### First-hour risks to clear
- **ESP32-C5 needs arduino-esp32 core ≥ 3.3.** Flash a blink sketch, then ESP-NOW **between an S3 and a C5** on channel 1. If this fails, drop the C5s to ESP-IDF or request more S3/classic ESP32s immediately.
- **Grove modules must run from 3V3.** On battery the XIAO's 5V pin is dead (it only carries USB power). Check each module's minimum supply voltage on Seeed's wiki (the Loudness Sensor may need about 3.5 V).
- ~~Scope the Grove Sound Sensor output~~ **Done on N2 (2026-11-07), see "Grove Sound Sensor: measured behaviour" below.** It is a real waveform, but clipped at both ends.

## Flashed board registry (2026-11-07)
Flash with `python tools/flash.py --port COMx --board c5|s3 --role node|gateway --id N [--ble]`. Board ID = USB serial number = MAC (shown by `python tools/flash.py --list` or in each node's boot line).

| Role | Board ID (MAC) | Firmware |
|---|---|---|
| Gateway (S3 Plus) | `44:B1:76:B0:85:54` | gateway, settings rebroadcast every 15 s |
| Drone bridge (S3 Plus #2) | — | not flashed yet |
| N1 | `10:BD:A3:CF:B1:20` | node + BLE scan |
| N2 | `10:BD:A3:CC:83:68` | node + BLE scan + **sensors (STEP 3)**, SW-420 tuned (2026-11-07 ~22:15) |
| N3 | `10:BD:A3:CC:8D:74` | node + BLE scan |
| N4 | `10:BD:A3:CB:DF:98` | node + BLE scan |
| N5 | `10:BD:A3:CF:46:80` | node + BLE scan |

## Per-node parts
| Part | Purpose | Source to check first | ~Cost |
|---|---|---|---|
| ESP32-C5 / S3 board | MCU + radio | have | $5–8 |
| **Grove Sound Sensor** (electret mic + amplifier, analog) | Audio: loudness, onsets, sustained sound (no band energies or chirp ranging: output is clipped at 3V3) | Grove kit | have |
| *Fallback:* Grove Loudness Sensor (analog loudness level only) | Energy-based localization only, no band energies or chirp ranging | Grove kit | have |
| **Grove Vibration Sensor SW-420** (digital, threshold knob) | **Contact tap sensor**, replaces the piezo disc: one `VIBRATION` event per tap, edge count ≈ strength; feeds tap patterns | Grove kit | have |
| **Grove Buzzer** | HAIL prompt: 3 × 150 ms beeps at 2.3 kHz (ranging chirps cut) | Grove kit | have |
| *Dropped:* external bright LED | Optical ID for the drone camera. Only one found, so nodes use the on-board user LED; camera LED-ID is on the cut list (hand-measured anchors instead) | — | — |
| *(built in)* ESP32 radio, BLE scan + Wi-Fi promiscuous mode | **Passive phone/wearable detection** (`DEVICE_SEEN`) | have | **$0** |
| Power: USB power bank (demo) or 300–500 mAh LiPo (production) | 1–2 h runtime | Library "batteries" / Micro Center | $3–10 |
| *Optional hero node:* mmWave radar (LD2410 or whatever the library has) | Stationary-person (breathing) detection | Library "Radar & Motion" | $3–5 |
| *Optional hero node:* gas sensor (MQ-2 / Grove) | Hazard; heater draws ~150 mA, so 1 node only | Grove kit | have |
| *Command post / hero node:* Grove Speaker | Louder or spoken HAIL ("if you can hear this, knock three times"); too power-hungry for every node | Grove kit | have |
| *Demo prop:* Grove Vibration Motor | **Fake survivor**: pulsed in a knock pattern inside a box under the rubble, so the tap demo is repeatable | Grove kit | have |
| *Stretch, not fitted:* Grove 3-Axis Accelerometer ±1.5 g (MMA7660FC, I2C) | Orientation ("landed mic-up?") and "node moved" detection. Too coarse (6-bit, ≤ 120 samples/s) to help with taps. Only if the core demo is solid: one node, I2C on D8 (SDA, white) / D9 (SCL, yellow) | Grove kit | have |
| *Not used:* Grove Mini PIR | Sees only warm bodies moving in line of sight, so it can't see into voids. At most, one node shows "person approaching" | Grove kit | have |
| Grove-to-jumper cables (or a Grove shield for XIAO) | The XIAO has no Grove sockets | Grove kit | have |
| Enclosure: weighted-bottom "weeble" (cup + coins/clay) | Self-righting: microphone and antenna face up | Improvised | ~$0 |

**Production parts cost estimate per node** (bulk): ESP32-C5 module $3 + MEMS microphone $1 + buzzer/LED/vibration switch $0.50 (production keeps a bright LED for camera ID) + 400 mAh LiPo $2 + moulded shell $2 + PCB/assembly $3 ≈ **$12**, or **~$15 with radar**.

## Drone: simulated, carried by hand
- The available drone is a **BetaFPV Cetus X (payload about 15–30 g)**. It can't lift the Pi 5, so **we simulate the drone**. A teammate carries the "drone payload" overhead along a lawnmower path over the field and drops the nodes by hand at logged points.
- The simulated drone payload is:
  - Pi 5 (16 GB) + AI HAT (26 TOPS) + Pi Camera, facing down;
  - the ESP32-S3 drone bridge over USB;
  - a USB power bank;
  - optionally, a GPS/GNSS module from the library. Indoors it won't get a fix, which demonstrates GPS-denied mode.
- **Drop log in GPS-denied mode:** the carrier presses a key or button at each drop. The Pi logs the time and the camera frame, and the drop point is anchored in the overhead image.
- **Optional real-drone clip (stretch, for video only):** the Cetus X carries **one bare ESP32-C5 node with a 1S 100–150 mAh LiPo (about 10–15 g)** and releases it, filmed with Code Metal staff in daylight. This proves the drop concept physically and doesn't block anything else.

## Thermal camera (low priority)
- The **HT-203U** is a USB-C smartphone thermal camera.
- Later, test whether it enumerates as a UVC webcam on the laptop or Pi. If it does, OpenCV `VideoCapture` can read it, and it can sit on the drone payload or a hero node for "heat" (OBJ.02).
- If it only works through its phone app, use phone screenshots or video as supporting evidence only.

## Power math (talking point)
- An ESP32-C5 with ESP-NOW receive always on draws about 80–100 mA. A 400 mAh LiPo gives about **4 h**, which meets the 1–2 h requirement with margin.
- With duty cycling (radio wakes for 100 ms each second, microphone stays always-on with a low-power wake-on-loud-sound comparator), average draw is about 20 mA, giving about **20 h**. That covers the multi-day rescue reality.

## Wiring: XIAO ESP32-C5 field node (provisional; **check against Seeed's official pinout before soldering**)
One Grove Sound Sensor, one Grove Vibration SW-420 and one Grove Buzzer per node use **3 of the 11 pins (D0–D10)**. No external LED. The S3 gateway and drone bridge need no sensor wiring.

Grove cable colours: **black = GND, red = VCC, white = NC (unused on these modules), yellow = SIG.**

| Signal | XIAO pin | GPIO | Notes |
|---|---|---|---|
| Grove **Sound Sensor** SIG (yellow) | **D0** | GPIO1 | The only pin Seeed's table clearly labels ADC. 12-bit ADC, 11 dB attenuation (0–3.3 V). Sample at 16 kHz with the ADC continuous driver, not an `analogRead()` loop |
| Grove **Vibration SW-420** SIG (yellow) | **D1** | | Digital input, `attachInterrupt` on change. Idle level reads 1. **Check the Grove plug is seated at the module** (N2's was not, and it silently read 1 with no edges). Tune the knob as in the bring-up checklist below |
| Grove **Buzzer** SIG (yellow) | **D4** | | LEDC PWM. The module has its own driver transistor, so wire it directly. Resonance is about 2.3 kHz (verify by ear), so chirp at that pitch rather than 4 kHz |
| All three Grove VCC (red) | **3V3** | | Not 5V: the 5V pin is dead on battery |
| All three Grove GND (black) | **GND** | | |
| Battery | BAT+ / BAT− pads (back) | | 3.7 V LiPo with protection circuit, charged by the on-board charger over USB-C. Check polarity: JST plug colour order isn't standard |

```
                 XIAO ESP32-C5 (top view, USB-C up)
                       ┌─────[USB-C]─────┐
 Sound SIG (yellow) ── │ D0           5V │   (unused: dead on battery)
 SW-420 SIG (yellow) ─ │ D1          GND │ ── GND bus ── 3× Grove black
        (avoid) ────── │ D2          3V3 │ ── 3V3 bus ── 3× Grove red
        (avoid) ────── │ D3          D10 │   (spare)
 Buzzer SIG (yellow) ─ │ D4           D9 │   (spare)
        (spare) ────── │ D5           D8 │   (spare)
        (spare, TX) ── │ D6           D7 │   (spare, RX)
                       └─────────────────┘
                       back: BAT+ (red) / BAT− (black) ── LiPo   ·   U.FL ── antenna
```

- **Shared power:** the board has a single 3V3 pin and a single GND pin, so make a 3V3 bus and a GND bus with a mini breadboard rail or a soldered splice (one wire in, three out).
- **Analog noise:** the radio's transmit bursts can couple into the sound sensor's signal. Keep the yellow wire short, route it away from the antenna, and expect a small spike on each ESP-NOW transmit. The firmware can blank samples during its own transmissions.
- **Avoid D2 (GPIO25) and D3 (GPIO7).** They may be strapping or boot pins, and sources disagree.
- **Spare pins:** D6/D7 (UART TX/RX for an mmWave radar on a hero node) and D8–D10 (freed by dropping the I2S mic; D8/D9 reserved for an optional I2C accelerometer).
- **Mounting:** the sound sensor's microphone must face up and out of the enclosure, unobstructed. The SW-420 should be screwed or glued firmly (not foam-taped) to the floor of the case so taps reach it through the ground.

## Field node bring-up checklist (per node, ~10 min)
1. Wire D0 sound, D1 SW-420, D4 buzzer, all reds to 3V3, blacks to GND (table above). **Push every Grove plug fully home at both ends.**
2. Flash: `python tools/flash.py --port COMx --board c5 --role node --id N --ble`.
3. Open the Serial Monitor at 921600 (or `python tools/serial_tail.py COMx --secs 30`). Every 5 s a node prints:
   `# audio floor=-22.6 dBFS level=-18.1 | events loud=.. felt=.. sustained=.. patterns=.. adc_err=0 | sw_edges=.. sw_pin=1`
   - `floor` should settle around −20 to −25 on the hall floor; `adc_err` must stay 0; `sw_pin` reads 1 at rest.
   - `# AUDIO init FAILED` means the sound sensor is disabled: check D0 and reflash.
4. **Buzzer:** type `H` in the Serial Monitor (local HAIL): 3 short beeps, and no events for ~3.5 s.
5. **SW-420 knob:** tap firmly 20–30 cm away. Each felt tap prints `# EVENT VIBRATION ... count=N`. Turn the knob until firm taps print and nothing prints for 10–20 s at rest. If nothing ever prints, the knob is too far the wrong way, or the plug isn't seated (`sw_edges` stays constant).
6. **Close the Serial Monitor** (it holds the COM port), and note the node in the registry above.

## Grove Sound Sensor: measured behaviour (N2 bench test, 2026-11-07, `firmware/sensor_test`)
- **It outputs a real waveform, but clipped at both ends.** The output rests at or below 0 V, so 30–40% of samples read exactly 0 (the bottom half of each wave is lost). Loud sounds flatten at about 1900 counts (~1.5 V). Likely cause: the LM386 amplifier is specified for ≥ 4 V and we run it from 3V3.
- Room noise on the hackathon floor: AC RMS about 250–350 counts. The node's own buzzer 10 cm away: about 850 counts (+9 dB) and fully clipped.
- `analogRead` takes ~35 µs, so 16 kHz sampling is fine.
- The buzzer responds to every tone from 500 Hz to 3 kHz. Pitch measurements at 8 kHz sampling were wrong (clipping harmonics alias), so measure its resonance at ≥ 16 kHz before choosing the chirp tone.
- **Tap test (N2, noisy hackathon floor, taps 20–30 cm away, claps ~1 m):** the 10 ms onset strength sits at 4–8 dB from room noise; only a few taps reached 10–13 dB and claps barely stood out. **The mic is a weak tap detector in a loud room**; the SW-420 is the primary tap sensor. Test in the quieter hallway before the demo.
- **SW-420 rings after a tap:** handling the table or a hard hit produces a burst of edges that can last ~1–1.5 s (up to ~100 edges per 200 ms, decaying). Clean knuckle taps (third test, hands off the table) give 1–6 edges over ≤ 1 s. In that test it registered 3 tap events (seemingly 3 of 5 taps), so it may be slightly under-sensitive for light taps at 20–30 cm on a bare board; a node glued to the case floor and resting on the surface should couple better.
- **Mic in the third test:** room baseline onset median 5 dB, max 8.4 dB; claps at ~1 m reached only 9.5–10 dB, so a 10 dB onset threshold barely separates claps from room noise; taps were not visible at all. At rest with nobody touching it, and during the node's own beeps, it stayed silent (0 edges). Turn the threshold knob down until a knuckle tap gives a short burst.
- **Decision: accept it and design around it** (see ARCHITECTURE.md §1 Audio): energy, onsets and taps only; treat clipped samples as a "very loud" flag; keep test sources ≥ 1 m from nodes; blank detection while the node beeps. Possible later fix: power the sensor from 5 V on USB power banks, with a 10 kΩ / 20 kΩ divider on SIG to protect the ADC (untested).

## Micro Center (Cambridge) shopping list, only if the library lacks it (check closing time)
- 4–6× ESP32 dev boards (Inland / Adafruit / SparkFun)
- *(Not needed now: mics, buzzers and tap sensors come from the Grove kit.)*
- Small USB power banks (×6) or LiPos + chargers
- Jumper wires, mini breadboards
