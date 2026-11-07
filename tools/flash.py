"""flash.py: compile + upload firmware/node with role/id baked in (no sketch edits needed).

Usage:
  python tools/flash.py --port COM12 --board c5 --role node --id 2
  python tools/flash.py --port COM5  --board s3 --role gateway --id 0
  python tools/flash.py --port COM12 --board c5 --role node --id 1 --ble
  python tools/flash.py --list         # show connected boards

Close any Arduino IDE Serial Monitor on that port first.
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe")
FQBN = {
    "c5": "esp32:esp32:XIAO_ESP32C5:CDCOnBoot=cdc",
    "s3": "esp32:esp32:XIAO_ESP32S3_Plus:CDCOnBoot=cdc",
}
ROLES = {"node": 1, "gateway": 2, "drone": 3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--board", choices=FQBN)
    ap.add_argument("--role", choices=ROLES)
    ap.add_argument("--id", type=int)
    ap.add_argument("--ble", action="store_true", help="enable passive BLE scan (DEVICE_SEEN)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        sys.exit(subprocess.call([CLI, "board", "list"]))
    if not (a.port and a.board and a.role and a.id is not None):
        ap.error("--port, --board, --role and --id are required")

    flags = f"-DROLE={ROLES[a.role]} -DNODE_ID={a.id} -DENABLE_BLE_SCAN={1 if a.ble else 0}"
    build = os.path.join(ROOT, "build", f"{a.board}-{a.role}-{a.id}{'-ble' if a.ble else ''}")
    cmd = [CLI, "compile", "--upload", "-p", a.port, "-b", FQBN[a.board],
           "--build-path", build,
           "--build-property", f"compiler.cpp.extra_flags={flags}",
           os.path.join(ROOT, "firmware", "node")]
    print(">", " ".join(cmd), flush=True)
    sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
