# Hardware

## Board allocation (we have 2× Seeed XIAO ESP32-S3 Plus and 5× Seeed XIAO ESP32-C5)
| Board | Role | Why |
|---|---|---|
| XIAO ESP32-S3 Plus #1 | **Gateway** (USB to the fusion host) | Mature support, reliable USB serial; stays at the command post |
| XIAO ESP32-S3 Plus #2 | **Drone bridge** (USB to the Pi 5) | Same reasons |
| XIAO ESP32-C5 ×5 | **Field nodes** 1–5, each with an **external I2S MEMS mic** | 8 MB PSRAM (enable under Tools → PSRAM), built-in LiPo charging and battery-voltage sensing, 11 GPIO, U.FL antenna. Run on 2.4 GHz channel 1 to talk to the S3s |

- **Pin budget per C5 node (6 of 11 GPIO):**
  - I2S mic (SCK, WS, SD);
  - passive buzzer (LEDC PWM);
  - LED;
  - piezo disc on an ADC pin.
- **An antenna must be attached to every board** (U.FL connector).

- **Four field nodes is the minimum** for 2-D localization with redundancy. **Ask the hackathon library for more plain ESP32s** (listed under "Additional Compute") so we can reach 6–8 field nodes.
- The gateway can also carry a microphone and act as an extra sensing node sitting at the command post.

### First-hour risks to clear
- **ESP32-C5 needs arduino-esp32 core ≥ 3.3.** Flash a blink sketch, then ESP-NOW **between an S3 and a C5** on channel 1. If this fails, drop the C5s to ESP-IDF or request more S3/classic ESP32s immediately.
- Confirm I2S microphone pin mapping on the C5.

## Per-node parts
| Part | Purpose | Source to check first | ~Cost |
|---|---|---|---|
| ESP32-C5 / S3 board | MCU + radio | have | $5–8 |
| I2S MEMS microphone (INMP441, ICS-43434, Adafruit SPH0645 #3421) | Audio | Library "Audio & Acoustic Sensing", then Micro Center (Adafruit stock) | $2–7 |
| *Fallback:* Grove sound sensor or MAX9814 analog microphone | Loudness only (still fine for energy-based localization) | Grove 40-in-1 kit | have |
| Passive piezo buzzer | HAIL prompt + ranging chirp | Grove kit / library / Micro Center | $0.50 |
| Bright LED (+ resistor) | Optical ID for the drone camera | Library | $0.10 |
| *(built in)* ESP32 radio, BLE scan + Wi-Fi promiscuous mode | **Passive phone/wearable detection** (`DEVICE_SEEN`) | have | **$0** |
| Power: USB power bank (demo) or 300–500 mAh LiPo (production) | 1–2 h runtime | Library "batteries" / Micro Center | $3–10 |
| Piezo disc (bare, 27 mm) | **Contact/seismic tap sensor** pressed to the ground ("hears" through rubble) | Micro Center | $0.30 |
| *Optional hero node:* mmWave radar (LD2410 or whatever the library has) | Stationary-person (breathing) detection | Library "Radar & Motion" | $3–5 |
| *Optional hero node:* gas sensor (MQ-2 / Grove) | Hazard; heater draws ~150 mA, so 1 node only | Grove kit | have |
| Enclosure: weighted-bottom "weeble" (cup + coins/clay) | Self-righting: microphone and antenna face up | Improvised | ~$0 |

**Production parts cost estimate per node** (bulk): ESP32-C5 module $3 + MEMS microphone $1 + buzzer/LED/piezo $0.50 + 400 mAh LiPo $2 + moulded shell $2 + PCB/assembly $3 ≈ **$12**, or **~$15 with radar**.

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
One mic, one piezo, one buzzer and one LED per node use **6 of the 11 pins (D0–D10)**. The S3 gateway and drone bridge need no sensor wiring.

| Signal | XIAO pin | GPIO | Notes |
|---|---|---|---|
| Piezo disc (ADC) | **D0** | GPIO1 | The only pin Seeed's table clearly labels ADC. 1 MΩ to GND across the piezo, plus 2× 1N4148 clamps to 3V3 and GND |
| Passive buzzer | **D4** | | LEDC PWM at about 4 kHz. A bare piezo buzzer can be driven directly. A *magnetic* buzzer (>20 mA) needs an NPN transistor + diode |
| LED | **D5** | | 220 Ω series resistor |
| Mic **BCLK** | **D8** | | **Mic = Adafruit ICS-43434 (#6049)**, bought at Micro Center. The ESP32's internal pin routing lets any GPIO carry I2S |
| Mic **LRCL** (word select) | **D9** | | |
| Mic **DOUT** (mic → MCU) | **D10** | | |
| Mic **3V** / **GND** | 3V3 / GND | | |
| Mic **SEL** | GND | | Low = left channel (also the default, but tie it to GND explicitly) |
| Battery | BAT+ / BAT− pads (back) | | 3.7 V LiPo, charged by the on-board charger |

- **ICS-43434 notes:**
  - The mic is **bottom-ported**: the sound hole is on the underside of the breakout. Mount it with the hole facing **up and out of the enclosure**, and don't seal it with glue or tape.
  - Firmware: I2S standard (Philips) format, 32-bit slots, mono left channel; the sample sits in the upper bits of each 32-bit word.
  - Start at 16 kHz (Adafruit's example rate). If the data comes back all zeros or garbage, try 32 kHz and downsample in software. The datasheet's exact sample-rate range is not yet verified.
  - Response is about 50 Hz–15 kHz, which covers voice (300–3000 Hz) and tapping.
- **Avoid D2 (GPIO25) and D3 (GPIO7).** They may be strapping or boot pins, and sources disagree.
- **Spare pins:** D1, D6, D7 (D6/D7 = UART TX/RX for an mmWave radar on a hero node).
- The board has a single 3V3 pin and a single GND pin, so use a mini breadboard rail or a soldered splice to share them.

## Micro Center (Cambridge) shopping list, only if the library lacks it (check closing time)
- 4–6× ESP32 dev boards (Inland / Adafruit / SparkFun)
- 6× I2S MEMS microphones (Adafruit SPH0645 or ICS-43434 breakouts)
- Passive piezo buzzers, bare piezo discs
- Small USB power banks (×6) or LiPos + chargers
- Jumper wires, mini breadboards
