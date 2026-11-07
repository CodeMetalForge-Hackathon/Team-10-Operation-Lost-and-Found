# Raspberry Pi gateway setup

This is the runbook for the fusion host. It does not replace `docs/HARDWARE.md`.

William's latest hardware note (`3b45ff0`, "update hardware list") says the team has 2× Seeed XIAO ESP32-S3 Plus (gateway and drone bridge) and 5× XIAO ESP32-C5 field nodes. Sebastian's check the same afternoon found 5 C5s, the Pi 5, and the Grove kit, and did not confirm an S3. That disagreement is on issue #5. Do not edit `docs/HARDWARE.md` from this branch.

The reader does not care which chip is on the USB cable. Point it at the gateway that is actually plugged in. This iteration does not assume a drone bridge.

Nothing here starts on boot. There is no systemd unit.

## What can run today

The only runnable piece is the serial reader:

```bash
python -m fusion.serial_ingest
```

There is no `fusion/server.py`, no TAK process, and no dashboard server. The static dashboard is on draft PR #7 (`feat/dashboard-foundation`). It is not served by this reader. Opening `ui/index.html` as a file will not show serial data.

## Packages

Raspberry Pi OS Lite 64-bit (Debian Trixie). Python 3.11 or newer. Trixie ships a newer Python; that is fine.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

`pyserial` is installed in the virtualenv, not from apt, so the Pi and a laptop use the same reader.

From the Team-10 checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest tests.test_serial_ingest
```

## SSH

On the Pi, SSH has to be enabled once. In Raspberry Pi Imager that is an imaging option. On a running Pi:

```bash
sudo raspi-config
```

Interface Options, then SSH, then enable. Find the address on the Pi with `hostname -I`, or try `raspberrypi.local` if mDNS works.

From the laptop:

```bash
ssh <user>@<pi-address>
```

Use the account created at imaging time. This guide does not set a password.

## Serial port

Do not hardcode `ttyUSB0` or `ttyACM0`. Those names move when another USB device is plugged in.

1. Unplug the gateway board.
2. `ls -l /dev/serial/by-id/`
3. Plug the gateway into a USB port on the Pi. Use the board's USB port, not a bare TX/RX jumper, unless you are deliberately using a USB-UART adapter.
4. Run `ls -l /dev/serial/by-id/` again. The new symlink is the port.
5. A native USB device usually points at `ttyACM*`. A USB-UART chip usually points at `ttyUSB*`.

Permissions, on Debian, are the `dialout` group:

```bash
ls -l /dev/ttyACM0
groups
sudo usermod -aG dialout "$USER"
```

Log out of SSH and back in. `groups` should then include `dialout`. If `ls` shows `root dialout` and you are in `dialout`, you can open the port. Do not run the reader as root to skip this.

Baud rate is 921600, from `docs/ARCHITECTURE.md`. Override it only if the firmware is actually using another rate:

```bash
export GATEWAY_PORT=/dev/serial/by-id/usb-PASTE-THE-SYMLINK-HERE
export GATEWAY_BAUD=921600
python -m fusion.serial_ingest
```

`--port` and `--baud` do the same thing. If neither `--port` nor `GATEWAY_PORT` is set, the process exits. It will not guess a device name.

Valid lines are printed to stdout as JSON, with `t_host` added. Malformed lines and disconnects go to stderr. Unplug is retried. Plug it back in and the same process keeps reading.

## Simulated input

No board required:

```bash
python -m fusion.serial_ingest --simulate tests/fixtures/sample_gateway.txt
```

That file is the five gateway examples from the architecture doc, including `device_seen`. It is not a recording from our hardware.

## Dashboard

This process does not feed the dashboard. The planned path is still: reader sink, then fusion state, then `/ws` at about 2 Hz, then `ui/`. The `/ws` payload is not specified. `POST /cmd`, `POST /anchor`, and `POST /baseline` are named and have no agreed body. This reader does not send HAIL, BLINK, RANGE, QUIET MODE, or BASELINE.

PR #7 was written before `device_seen` and the layer toggle. Leave that PR as it is until the `/ws` shape is agreed. Do not parse gateway JSON in the browser.
