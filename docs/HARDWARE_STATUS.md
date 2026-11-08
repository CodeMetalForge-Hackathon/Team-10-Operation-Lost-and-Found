# Hardware implementation report

Date of this check: 2026-11-08. Branch `feat/demo-integration`, after merging William's `bcb073b` ("Updated hardware and firmware tests").

This report separates three things. Mixing them is how a demo overclaims.

1. What the firmware source does.
2. What a committed recording or William's written bench note shows.
3. What nobody has verified.

No board was flashed in this session. This Mac had no USB gateway serial device (`/dev/cu.usb*` was absent; only Bluetooth serial ports were listed). `raspberrypi.local` resolved to `10.1.200.253` and the ping was rejected by a filter (`Communication prohibited by filter`). Pi networking was not changed.

## Firmware functionality

Source: `firmware/node/node.ino` and `firmware/node/protocol.h`, plus `firmware/sensor_test/sensor_test.ino` from William's latest commit.

The mesh sketch can be compiled as a field node, a gateway, or a drone bridge by `ROLE` and `NODE_ID`. `tools/flash.py` can pass those as build flags. This session did not run it.

Implemented in the mesh sketch:

- ESP-NOW broadcast on 2.4 GHz channel 1. The C5 build forces `WIFI_BAND_MODE_2G_ONLY` because the S3 cannot hear 5 GHz.
- Wi-Fi station mode is turned on, then `WiFi.disconnect()`, then the channel is set, then ESP-NOW is initialized. There is no `WiFi.begin()`. The gateway does not join a network.
- Beacons about every 2 s. `uptime_s` comes from `millis()`. `batt_mv` is still hardcoded 0. `floor_db` is 0 until the audio task runs.
- Neighbor RSSI from direct (`hops == 0`) transmissions. Forwarding increments `hops` and decrements `ttl` (start TTL 4) with a short random delay.
- Gateway and drone-bridge roles print JSON lines and a `gw` status every 5 s. USB serial is 921600. Prints are non-blocking on USB-CDC so a quiet host cannot stall the mesh.
- Text commands on the gateway serial port: `CMD HAIL`, `BLINK`, `RANGE`, `TXPOWER`, `RATE`, `PING`, `SCAN`, `SALT`. The gateway repeats a command and rebroadcasts TX power, scan, and salt every 15 s after they have been set.
- Optional BLE scan (`ENABLE_BLE_SCAN`). Passive. Hashes the address. Sends `device_seen`.
- JSON printers for `feat`, `event`, and `range`. Generation of `feat` and `event` was added in `153bab1` and is described below. `range` is still only a printer.

`firmware/sensor_test/sensor_test.ino` is a one-board bench sketch. It samples the Grove sound sensor on D0, counts SW-420 edges on D1, and drives the buzzer on D4 and the on-board LED. It does not speak ESP-NOW and it does not emit the telemetry JSON above. William's notes from running it are in `docs/HARDWARE.md`. This session did not repeat that bench.

## Firmware after `153bab1`

Still ESP-NOW on channel 1. Still no `WiFi.begin()`. Still no TCP client. USB JSON lines are the same objects.

`ROLE_NODE` now runs STEP 3 in the same sketch: 16 kHz ADC DMA, SW-420 bursts as `VIBRATION`, sustained sound as `VOICE_LIKE`, tap patterns, and `feat` once a second with band fields hardcoded `-128`. `batt_mv` is still 0. `floor_db` is a real dBFS value after the audio task warms up, and 0 before that.

William's registry says only N2 is flashed with sensors. N1, N3, N4, and N5 are still listed as node + BLE scan. That is his note, not a port listing from this session.

His N2 bench note (not a JSONL file) says LOUD, VOICE_LIKE, VIBRATION, and TAP_PATTERN were printed, including `TAP_PATTERN count=5 conf=80`. This host has not seen those lines.

## Captured physical observations

From the six committed JSONL files and their meta notes, not from a live board in this session:

- Gateway id 0 printed `gw` lines. `rx_dropped` was 0 on all 80 of them.
- Nodes 1 and 2 sent beacons. `uptime_s` increased. `batt_mv` and `floor_db` were 0 every time, which matches the hardcoded firmware, not a measured battery or noise floor.
- Nodes heard each other, and sometimes heard the gateway (neighbor id 0).
- Nine radio lines had `hops` 1. The meta note on `beacons_line_2nodes` says the gateway still heard both nodes directly, with occasional relayed copies of node 2 via node 1, after TX power was lowered. That is evidence of forwarding. It is not evidence of a planned multi-hop route or of a location.
- `device_seen` contained `BLE_APPLE`, `BLE_OTHER`, `BLE_FINDMY`, and `BLE_GOOGLE`. No `WIFI_PROBE` line is in the files.
- Recorder commands (`host_cmd`) and firmware text echoes (`log`) are in some files. They are not sensor observations.
- No `feat`, `event`, or `range` line is in the files.
- Meta positions are hand-entered ground truth (`positions_m`). The firmware did not estimate them.

William's `docs/HARDWARE.md` registry, written by him, not re-checked on a bench here:

| Role | Board | ID he recorded | Firmware he recorded |
|---|---|---|---|
| Gateway | XIAO ESP32-S3 Plus | `44:B1:76:B0:85:54` | gateway, settings rebroadcast |
| Drone bridge | XIAO ESP32-S3 Plus #2 | not listed | not flashed |
| N1–N5 | XIAO ESP32-C5 | five MACs in that file | node + BLE scan |

His N2 bench note says the Grove sound sensor clips at both ends on 3V3, the mic is a weak tap detector on a loud floor, and the SW-420 rings for up to about 1.5 s. Those sentences are his measurements. They are not in the JSONL telemetry, and this host does not turn them into a detection.

## Unverified

- No live serial session from this Mac, including no capture of the new sensor events.
- No Wi-Fi join from the gateway. `153bab1` did not add one.
- No Raspberry Pi path tested in this session. Sebastian reports the `Team 10 Field` hotspot is up and that the dashboard has been opened from it. This session did not join that network and did not change the Pi.
- Chirp `range` is still not generated.
- No battery voltage reading.
- Noise floor is computed in the new node firmware after warm-up. This host has not seen a non-zero `floor_db` on the wire.
- No Wi-Fi probe capture in the committed files.
- No localization, heatmap, or TAK update from this host.
- Drone bridge not flashed, per William's registry.
- External LED dropped; camera LED-ID cut. Do not claim it.
- Multi-hop exists in the protocol and showed up as `hops` 1. Do not claim a multi-hop field network beyond that recording note.

The desired demo is still: a battery node makes a real observation, the gateway receives it over ESP-NOW, the gateway delivers it to the host on the local network, and the dashboard shows LIVE. USB serial is the fallback until the Wi-Fi path has actually been seen.
