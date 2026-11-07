"""rssi_log.py: record neighbor RSSI from a node's '# alive' lines at a labeled distance.

Usage:
  python tools/rssi_log.py --port COM5 --neighbor 2 --dist 0.5 --secs 25 [--note "floor, LOS"]
Appends one summary row per run to data/rssi_calibration.csv (path-loss model calibration).
"""
import argparse
import csv
import os
import re
import statistics
import time

import serial

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "rssi_calibration.csv")


def open_port(port):
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 921600, 0.2
    s.dtr = s.rts = False
    for _ in range(40):
        try:
            s.open()
            return s
        except serial.SerialException:
            time.sleep(0.25)
    raise SystemExit(f"cannot open {port}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--neighbor", type=int, required=True)
    ap.add_argument("--dist", type=float, required=True, help="metres")
    ap.add_argument("--secs", type=float, default=25)
    ap.add_argument("--note", default="floor, line of sight")
    a = ap.parse_args()

    pat = re.compile(r"\[%d (-?\d+)dBm\]" % a.neighbor)
    s = open_port(a.port)
    vals, buf, end = [], b"", time.time() + a.secs
    while time.time() < end:
        buf += s.read(512)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            m = pat.search(line.decode(errors="replace"))
            if m:
                vals.append(int(m.group(1)))
                print(f"  {a.dist} m: {m.group(1)} dBm", flush=True)
    s.close()

    if not vals:
        print(f"NO READINGS of node {a.neighbor} at {a.dist} m (out of range or unpowered?)")
        row = [time.strftime("%H:%M:%S"), a.port, a.neighbor, a.dist, 0, "", "", "", "", a.note]
    else:
        row = [time.strftime("%H:%M:%S"), a.port, a.neighbor, a.dist, len(vals),
               round(statistics.mean(vals), 1), round(statistics.pstdev(vals), 1), min(vals), max(vals), a.note]
        print(f"SUMMARY {a.dist} m: mean {row[5]} dBm, sd {row[6]}, n={len(vals)}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    new = not os.path.exists(OUT)
    with open(OUT, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "port", "neighbor", "dist_m", "n", "mean_dbm", "sd_db", "min", "max", "note"])
        w.writerow(row)


if __name__ == "__main__":
    main()
