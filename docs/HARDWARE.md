# Hardware

## Board allocation (we have 2× Seeed XIAO ESP32-S3 Plus and 5× Seeed XIAO ESP32-C5)
| Board | Role | Why |
|---|---|---|
| XIAO ESP32-S3 Plus #1 | **Gateway** (USB to the fusion host) | Mature support, reliable USB serial; stays at the command post |
| XIAO ESP32-S3 Plus #2 | **Drone bridge** (USB to the Pi 5) | Same reasons |
| XIAO ESP32-C5 ×5 | **Field nodes** 1–5, each with a **Grove Sound Sensor (analog mic) + Grove Vibration SW-420 (tap) + Grove Buzzer** | 8 MB PSRAM (enable under Tools → PSRAM), built-in LiPo charging and battery-voltage sensing, 11 GPIO, U.FL antenna. Run on 2.4 GHz channel 1 to talk to the S3s |

- **Pin budget per C5 node (4 of 11 GPIO):**
  - Grove Sound Sensor on an ADC pin;
  - Grove Vibration SW-420 on a digital interrupt pin;
  - Grove Buzzer (LEDC PWM);
  - LED.
- **An antenna must be attached to every board** (U.FL connector).

- **Four field nodes is the minimum** for 2-D localization with redundancy. **Ask the hackathon library for more plain ESP32s** (listed under "Additional Compute") so we can reach 6–8 field nodes.
- The gateway can also carry a microphone and act as an extra sensing node sitting at the command post.

### First-hour risks to clear
- **ESP32-C5 needs arduino-esp32 core ≥ 3.3.** Flash a blink sketch, then ESP-NOW **between an S3 and a C5** on channel 1. If this fails, drop the C5s to ESP-IDF or request more S3/classic ESP32s immediately.
- **Grove modules must run from 3V3.** On battery the XIAO's 5V pin is dead (it only carries USB power). Check each module's minimum supply voltage on Seeed's wiki (the Loudness Sensor may need about 3.5 V).
- **Scope the Grove Sound Sensor output:** sample D0 at 16 kHz while clapping. A trace that swings around a midpoint is a real waveform (band energies and chirp ranging work). Only positive bumps means loudness only (keep `rms_db`/`peak_db`, degrade the rest).

## Per-node parts
| Part | Purpose | Source to check first | ~Cost |
|---|---|---|---|
| ESP32-C5 / S3 board | MCU + radio | have | $5–8 |
| **Grove Sound Sensor** (electret mic + amplifier, analog) | Audio: RMS, band energies, onsets, chirp ranging | Grove kit | have |
| *Fallback:* Grove Loudness Sensor (analog loudness level only) | Energy-based localization only, no band energies or chirp ranging | Grove kit | have |
| **Grove Vibration Sensor SW-420** (digital, threshold knob) | **Contact tap sensor**, replaces the piezo disc: tap timing and patterns, no amplitude | Grove kit | have |
| **Grove Buzzer** | HAIL prompt + ranging chirp (fixed pitch, about 2.3 kHz) | Grove kit | have |
| Bright LED (+ resistor) | Optical ID for the drone camera | Library | $0.10 |
| *(built in)* ESP32 radio, BLE scan + Wi-Fi promiscuous mode | **Passive phone/wearable detection** (`DEVICE_SEEN`) | have | **$0** |
| Power: USB power bank (demo) or 300–500 mAh LiPo (production) | 1–2 h runtime | Library "batteries" / Micro Center | $3–10 |
| *Optional hero node:* mmWave radar (LD2410 or whatever the library has) | Stationary-person (breathing) detection | Library "Radar & Motion" | $3–5 |
| *Optional hero node:* gas sensor (MQ-2 / Grove) | Hazard; heater draws ~150 mA, so 1 node only | Grove kit | have |
| *Command post / hero node:* Grove Speaker | Louder or spoken HAIL ("if you can hear this, knock three times"); too power-hungry for every node | Grove kit | have |
| *Demo prop:* Grove Vibration Motor | **Fake survivor**: pulsed in a knock pattern inside a box under the rubble, so the tap demo is repeatable | Grove kit | have |
| *Not used:* Grove Mini PIR | Sees only warm bodies moving in line of sight, so it can't see into voids. At most, one node shows "person approaching" | Grove kit | have |
| Grove-to-jumper cables (or a Grove shield for XIAO) | The XIAO has no Grove sockets | Grove kit | have |
| Enclosure: weighted-bottom "weeble" (cup + coins/clay) | Self-righting: microphone and antenna face up | Improvised | ~$0 |

**Production parts cost estimate per node** (bulk): ESP32-C5 module $3 + MEMS microphone $1 + buzzer/LED/vibration switch $0.50 + 400 mAh LiPo $2 + moulded shell $2 + PCB/assembly $3 ≈ **$12**, or **~$15 with radar**.

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
One Grove Sound Sensor, one Grove Vibration SW-420, one Grove Buzzer and one LED per node use **4 of the 11 pins (D0–D10)**. The S3 gateway and drone bridge need no sensor wiring.

Grove cable colours: **black = GND, red = VCC, white = NC (unused on these modules), yellow = SIG.**

| Signal | XIAO pin | GPIO | Notes |
|---|---|---|---|
| Grove **Sound Sensor** SIG (yellow) | **D0** | GPIO1 | The only pin Seeed's table clearly labels ADC. 12-bit ADC, 11 dB attenuation (0–3.3 V). Sample at 16 kHz with the ADC continuous driver, not an `analogRead()` loop |
| Grove **Vibration SW-420** SIG (yellow) | **D1** | | Digital input, `attachInterrupt` on change. Check with a serial print which level means "vibration". Set the threshold knob on the board so a knuckle tap on the floor triggers but footsteps a metre away don't |
| Grove **Buzzer** SIG (yellow) | **D4** | | LEDC PWM. The module has its own driver transistor, so wire it directly. Resonance is about 2.3 kHz (verify by ear), so chirp at that pitch rather than 4 kHz |
| LED | **D5** | | 220 Ω series resistor to GND |
| All three Grove VCC (red) | **3V3** | | Not 5V: the 5V pin is dead on battery |
| All three Grove GND (black) + LED cathode | **GND** | | |
| Battery | BAT+ / BAT− pads (back) | | 3.7 V LiPo with protection circuit, charged by the on-board charger over USB-C. Check polarity: JST plug colour order isn't standard |

```
                 XIAO ESP32-C5 (top view, USB-C up)
                       ┌─────[USB-C]─────┐
 Sound SIG (yellow) ── │ D0           5V │   (unused: dead on battery)
 SW-420 SIG (yellow) ─ │ D1          GND │ ── GND bus ── 3× Grove black, LED cathode
        (avoid) ────── │ D2          3V3 │ ── 3V3 bus ── 3× Grove red
        (avoid) ────── │ D3          D10 │   (spare)
 Buzzer SIG (yellow) ─ │ D4           D9 │   (spare)
 LED ─[220 Ω]─ anode ─ │ D5           D8 │   (spare)
        (spare, TX) ── │ D6           D7 │   (spare, RX)
                       └─────────────────┘
                       back: BAT+ (red) / BAT− (black) ── LiPo   ·   U.FL ── antenna
```

- **Shared power:** the board has a single 3V3 pin and a single GND pin, so make a 3V3 bus and a GND bus with a mini breadboard rail or a soldered splice (one wire in, four out).
- **Analog noise:** the radio's transmit bursts can couple into the sound sensor's signal. Keep the yellow wire short, route it away from the antenna, and expect a small spike on each ESP-NOW transmit. The firmware can blank samples during its own transmissions.
- **Avoid D2 (GPIO25) and D3 (GPIO7).** They may be strapping or boot pins, and sources disagree.
- **Spare pins:** D6/D7 (UART TX/RX for an mmWave radar on a hero node) and D8–D10 (freed by dropping the I2S mic).
- **Mounting:** the sound sensor's microphone must face up and out of the enclosure, unobstructed. The SW-420 should be screwed or glued firmly to the floor of the case so taps reach it through the ground.

## Micro Center (Cambridge) shopping list, only if the library lacks it (check closing time)
- 4–6× ESP32 dev boards (Inland / Adafruit / SparkFun)
- *(Not needed now: mics, buzzers and tap sensors come from the Grove kit.)*
- Small USB power banks (×6) or LiPos + chargers
- Jumper wires, mini breadboards
