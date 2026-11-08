# Raspberry Pi gateway setup

This is the runbook for the fusion host. It does not replace `docs/HARDWARE.md`.

William's latest hardware note (`3b45ff0`, "update hardware list") says the team has 2× Seeed XIAO ESP32-S3 Plus (gateway and drone bridge) and 5× XIAO ESP32-C5 field nodes. Sebastian's check the same afternoon found 5 C5s, the Pi 5, and the Grove kit, and did not confirm an S3. That disagreement is on issue #5. Do not edit `docs/HARDWARE.md` from this branch.

The reader does not care which chip is on the USB cable. Point it at the gateway that is actually plugged in. This iteration does not assume a drone bridge.

Nothing here starts on boot. There is no systemd unit.

## What can run today

Two entry points:

```bash
python -m fusion.serial_ingest --simulate tests/fixtures/sample_gateway.txt
python -m fusion.server --demo
```

The first prints validated gateway lines to stdout. The second serves the dashboard at http://127.0.0.1:8000 and pushes proposed `/ws` version 1. `--demo` is simulated. It is not a hardware recording.

On the Pi, bind the dashboard so the laptop can open it:

```bash
python -m fusion.server --demo --host 0.0.0.0 --listen 8000
```

There is still no TAK process and no systemd unit. The AI accelerator is not used.

## Packages

Raspberry Pi OS Lite 64-bit (Debian Trixie). Python 3.11 or newer. Trixie ships a newer Python; that is fine.

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

`pyserial`, FastAPI, and uvicorn are installed in the virtualenv, not from apt, so the Pi and a laptop use the same host. Nothing here needs the Hailo runtime.

From the Team-10 checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests
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

`python -m fusion.server` serves `ui/index.html` and pushes state on `/ws` at about 2 Hz. The payload is proposed in `docs/WS_CONTRACT.md`. It is not yet in `docs/ARCHITECTURE.md`.

Opening `ui/index.html` as a file still shows nothing from the gateway. Use the server.

`POST /cmd`, `POST /anchor`, and `POST /baseline` are still unnamed bodies. This server does not send HAIL, BLINK, RANGE, QUIET MODE, or BASELINE. The buttons stay disabled.

PR #7 is the page shell. This branch renders version 1 on that page. It does not parse gateway JSON in the browser.

## Planned local Wi-Fi, not applied

`docs/INTEGRATION_HANDOFF.md` is the proposal: Pi access point on 2.4 GHz channel 1, no upstream internet, gateway TCP to port 9100. Do not configure that remotely from a laptop that cannot already get back in.

On 2026-11-08 this Mac resolved `raspberrypi.local` to `10.1.200.253` and the ping was rejected (`Communication prohibited by filter`). That is not a verified host. No Pi networking change was made.

Sebastian later reported that the `Team 10 Field` hotspot is up and that the dashboard has been opened from it. This note does not reconfigure that AP, does not record its channel, and does not treat the report as a radio test of the ESP32 gateway. The host listener can bind `0.0.0.0` (`--tcp-bind`). The gateway firmware still has no TCP client. See `docs/INTEGRATION_HANDOFF.md`.
