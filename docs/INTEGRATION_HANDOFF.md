# Integration handoff

For William (firmware and boards) and Seb (host). Do not merge this branch to `main` until both of you have looked at a live line.

Nothing in this file was produced by flashing a board or by logging into the Pi. `docs/HARDWARE_STATUS.md` says what is firmware, what was recorded, and what is still unchecked. `docs/TELEMETRY_CONTRACT.md` is the host parser contract.

## 1. Revisions

| Piece | Revision |
|---|---|
| Integration branch | `feat/demo-integration` |
| William firmware incorporated | `bcb073b` on `origin/main` ("Updated hardware and firmware tests"), merged here |
| Mesh firmware | `firmware/node/node.ino`, `firmware/node/protocol.h` |
| Bench sketch | `firmware/sensor_test/sensor_test.ino` (not the mesh) |
| Host | `fusion/serial_ingest.py`, `fusion/state.py`, `fusion/server.py`, `fusion/recording.py`, `fusion/net_ingest.py` |

Confirm the commit on GitHub before the demo. A local hash in a chat message goes stale.

## 2. Radio topology that is actually implemented

Checked again against `firmware/node/node.ino` at `153bab1` / `c69393f`.

ESP-NOW broadcast flood on 2.4 GHz channel 1 (`ESPNOW_CHANNEL`). That did not change.

- Field nodes send beacons and, when built with `ENABLE_BLE_SCAN`, `device_seen`.
- `ROLE_NODE` now also sends `feat` and `event` from the sensor task. Band energies are `-128`. `VIBRATION` is an SW-420 burst, not an accelerometer.
- Nodes may rebroadcast. The gateway prints and does not rebroadcast uplink packets.
- There is still no `WiFi.begin()` and no TCP client. `WiFi.mode(WIFI_STA)` is only there so ESP-NOW has a radio.
- C5 builds still lock the band to 2.4 GHz.

Recorded `hops` 1 evidence is unchanged. No new capture file was added with the sensor firmware.

## 3. Which board is the gateway

William's registry in `docs/HARDWARE.md` says the gateway is the XIAO ESP32-S3 Plus `44:B1:76:B0:85:54`, flashed as `ROLE_GATEWAY`, `NODE_ID` 0.

Confirm that on the bench before the demo: `python tools/flash.py --list`, or the boot line `# Team10 node up: role=2 id=0 mac=... ch=1`. This session did not see that port.

The second S3 is the drone bridge and, by his note, is not flashed. Do not assume it is the gateway.

## 4. How nodes reach the gateway

A field node broadcasts ESP-NOW to `FF:FF:FF:FF:FF:FF` on channel 1. The gateway receives on that channel and prints JSON. A node may also forward a packet it did not originate, which shows up as `hops` greater than 0.

Nodes do not join the Pi's Wi-Fi. Do not change them to Wi-Fi stations to remove a USB cable. That would abandon the mesh the recordings already show.

## 5. USB serial from the gateway

Gateway USB, 921600, one JSON object per line. CDC on boot must be enabled or the port will not be the sketch's serial. Prints do not block.

Text the gateway understands, newline terminated:

```text
CMD PING 0 255
CMD BLINK 0 255
CMD HAIL 0 255
CMD TXPOWER 8 255
CMD SCAN 2 255
CMD SALT 1234 255
CMD RANGE 0 255
```

This host does not send those commands. `POST /cmd` is still 404.

On the Mac, do not guess `tty.usbmodem*`. Unplug, `ls /dev/cu.*`, plug in, see which node appeared. On the Pi, use `/dev/serial/by-id/`.

## 6. Planned Wi-Fi transport to the Pi

Target path, not yet seen on hardware:

```text
ESP32 field node --ESP-NOW ch 1--> optional relay --ESP-NOW ch 1--> ESP32-S3 gateway --Wi-Fi STA--> Pi AP "Team 10 Field" --TCP--> fusion host
```

Sebastian reports that the `Team 10 Field` hotspot is already up and that the dashboard has been opened from it. This session did not join that network, did not read its channel, and did not change the Pi. Do not reset it.

The host can bind the TCP listener on a LAN address (`--tcp-bind 0.0.0.0`). A unit test bound `0.0.0.0` and accepted a line via `127.0.0.1`. That is not a test that an ESP32 joined `Team 10 Field`.

If the Pi AP is not on channel 1, the gateway cannot keep ESP-NOW on channel 1 and join that AP. Confirm the channel on the Pi before flashing the gateway. Do not retune the field nodes to match a 5 GHz or channel-6 AP.

## 7. Message format, with a real payload

Authoritative field rules: `docs/TELEMETRY_CONTRACT.md`.

Real beacon, from `data/beacons_line_2nodes.jsonl`:

```json
{"type": "beacon", "src": 2, "seq": 91, "hops": 0, "rssi_last": -36, "batt_mv": 0, "uptime_s": 186, "floor_db": 0, "nbrs": [[1, -43]], "t_host": 1794088158.947}
```

`t_host` in that file is Unix seconds, added by `tools/record_gateway.py`. It is not on the wire. The host stores it as `t_recorded_s` and stamps its own millisecond clock for freshness.

Real gateway diagnostic:

```json
{"type": "gw", "id": 0, "t_ms": 306574, "rx_dropped": 0, "t_host": 1794088158.746}
```

`batt_mv` 0 and `floor_db` 0 are the firmware sentinels. The dashboard state keeps the zeros and marks them `unimplemented`. `uptime_s` is real. `hops` is real when it is non-zero.

`feat`, `event`, and `range` are in the printer and in the architecture examples. They are not in the recordings. Do not demo them as live sensor results until a board emits them.

## 8. Wi-Fi requirements

Not configured. Do not apply this remotely without a recovery path (keyboard and monitor, or a second network path you have already used).

For the gateway to keep ESP-NOW while it is a Wi-Fi station, the Pi access point has to be on the same channel as the mesh.

| Setting | Value | Why |
|---|---|---|
| Band | 2.4 GHz only | S3 and the C5 mesh are on 2.4 GHz. Channel 1 is `ESPNOW_CHANNEL`. |
| Channel | 1 | `WiFi.begin()` adopts the AP channel. A different channel deafens ESP-NOW peers. |
| Security | WPA2-PSK | Local password. Do not commit it. |
| Upstream | none | The demo must run with no internet. No captive portal, no DNS that only works online. |
| DHCP | Pi serves addresses on that LAN | The gateway needs an address so it can open TCP to the host. |
| Host bind | `0.0.0.0:9100` for the gateway, dashboard on another port such as 8000 | 8765 and 8775 stay untouched. |

ESP-NOW plus Wi-Fi station on one ESP32 is a known same-channel setup, not something this repo has measured. After the join, the sketch should set modem sleep off (`esp_wifi_set_ps(WIFI_PS_NONE)`) so ESP-NOW is not waiting on power save. If the association lands on the wrong channel, stop and fix the AP. Do not retune the field nodes.

BLE scan stays on the field nodes, on the duty cycle William already flashed. Do not also run a BLE scan on the gateway while it is a Wi-Fi station. The recordings already show the radio-time tradeoff was handled on the nodes.

## 9. Firmware change for William

Do not flash this from the host branch. It is the smallest gateway-only addition. Field-node radio stays ESP-NOW.

In `ROLE_GATEWAY` only, after ESP-NOW is up on channel 1:

1. Keep USB JSON exactly as `printJson` and the `gw` printf write it now.
2. Connect as a station to the Pi AP (channel 1, WPA2). If the association changes the channel, set the channel back to 1 or fix the AP. Do not continue on another channel.
3. Open a TCP client to the host port (9100 unless Seb says otherwise).
4. On every JSON line already sent to `Serial`, write the same bytes plus `\n` to the TCP client when it is connected.
5. If Wi-Fi or TCP drops, keep ESP-NOW receive and USB printing. Reconnect in the background. Do not block the mesh. `Serial.setTxTimeoutMs(0)` already exists so a quiet USB host cannot stall the radio; the TCP write needs the same property (short timeout, drop the line, do not wait).
6. Do not add a new JSON schema. Keep `uptime_s`. `batt_mv` is still 0; leave it until the battery pin is actually read. `floor_db` may now be a real dBFS value after warm-up. Do not force it back to 0. Band fields stay `-128` until a sensor can produce them. A measured zero floor must not be the only signal that a floor exists, or the host will still call 0 unimplemented.
7. Do not enable `ENABLE_BLE_SCAN` on the gateway for this path.
8. Leave `firmware/sensor_test` as a bench sketch. Do not replace `firmware/node` with it.

Sketch of the write, not a file to compile:

```cpp
// ROLE_GATEWAY only. Do not flash from this note.
void emitLine(const String &line) {
  Serial.print(line);          // existing USB path, already non-blocking
  if (tcp.connected()) {
    tcp.print(line);           // same bytes, including the trailing newline
  }
}
```

`printJson` currently prints with several `Serial.printf` calls. The TCP copy has to be one complete line, not a partial printf. Build the line in a buffer, then emit it once to USB and once to TCP.

## 10. Commands for Seb

From this worktree. Python 3.11. Do not stop whatever is already on 8765 or 8775.

```bash
cd ~/Projects/codemetal-worktrees/demo-integration
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests
```

Recorded fallback. No board, no internet, no Pi. The badge must say RECORDING.

```bash
python -m fusion.server --recording data/beacons_line_2nodes.jsonl --speed 8 --host 127.0.0.1 --listen 8000
```

Open http://127.0.0.1:8000 . Nodes 1 and 2 should appear, then go stale about 6 s after playback ends. `batt_mv` stays 0 and is unimplemented. Gateway drops stay 0 for that file.

USB, when a gateway is actually plugged in. Replace the device path. The badge must say LIVE.

```bash
python -m fusion.server --gateway /dev/cu.usbmodemXXXX --host 127.0.0.1 --listen 8000
```

TCP on this Mac, for a gateway that can already open a socket. This does not prove the Pi.

```bash
python -m fusion.server --tcp 9100 --tcp-bind 0.0.0.0 --host 0.0.0.0 --listen 8000
```

`--tcp-bind 0.0.0.0` is what a gateway on `Team 10 Field` needs. On a laptop with no gateway, prefer `127.0.0.1`. Do not bind 8765 or 8775.

The process writes `data/host.sqlite` unless you pass `--no-store`. That file is history. It is not loaded back into the live roster on restart. `GET /history` returns it, marked historical.

USB and TCP together, still one live state:

```bash
python -m fusion.server --gateway /dev/cu.usbmodemXXXX --tcp 9100 --tcp-bind 0.0.0.0 --host 0.0.0.0 --listen 8000
```

`--tcp-bind 0.0.0.0` is for the Pi LAN. On a laptop with no gateway attached, prefer `127.0.0.1`. Do not reset the existing `Team 10 Field` AP to find out.

`--demo` and `--simulate` are SIMULATION. They are not the hardware recording.

## 11. Physical acceptance test

Not passed. Run it on the bench. Pass only if every step is true.

1. One field node is on battery, not USB. Gateway is the S3 from the registry, or a board you just identified and wrote down.
2. The node beacon arrives at the gateway over ESP-NOW. `hops` may be 0. A relayed copy is extra evidence, not required.
3. The gateway delivers that JSON line to the host. Prefer TCP to the Pi AP on channel 1. If that firmware is not flashed yet, USB serial counts as the fallback, and the report must say so.
4. The dashboard badge says LIVE, not RECORDING and not SIMULATION.
5. The node row shows the real `src`, a changing `uptime_s` or `seq`, and raw `batt_mv` 0 marked unimplemented. It does not show a position.
6. Disconnect the gateway from the host. Within about 6 s the node goes stale. Reconnect. It becomes active again without restarting the browser.
7. A garbage line on the wire does not stop the next beacon.
8. Unplug the building network. The page still updates. The assets are local. Nothing in this path should have needed DNS.

If step 3 only works over USB, the demo is a USB demo. Do not call it Wi-Fi.

## 12. Fallbacks

USB: section 10, `--gateway`. Leave it working even after TCP exists.

Recording: section 10, `--recording`. Use a committed file, not a hand-built dashboard object. `--speed 8` is enough to show motion without waiting 240 s. When it ends, the badge stays RECORDING.

Simulation: `python -m fusion.server --demo` on a port that is free. It is the script in `sim/demo.py`. Say that out loud if you use it.

Do not kill the processes on 8765 and 8775 to free a port. Pick 8000 or another free port.
