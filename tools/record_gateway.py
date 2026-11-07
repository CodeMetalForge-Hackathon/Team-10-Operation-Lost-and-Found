"""record_gateway.py: record gateway JSON lines (+ host timestamps) for offline replay.

Usage:
  python tools/record_gateway.py --port COM13 --name beacons_2nodes --secs 180 \
      --pos 1=0,0 --pos 2=3.5,0 --note "office floor, nodes on floor"

Writes:
  data/<name>.jsonl      one gateway JSON object per line, with "t_host" (unix seconds) added
  data/<name>.meta.json  ground-truth node positions (metres, local frame), notes, port, duration
Non-JSON lines from the gateway ("# ...") are kept with type "log".
Replay later with:  for line in open(path): msg = json.loads(line)
"""
import argparse
import json
import os
import time

import serial

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
    raise SystemExit(f"cannot open {port} (close WinTAK / Arduino Serial Monitor)")


def parse_pos(items):
    out = {}
    for it in items:
        nid, xy = it.split("=")
        x, y = (float(v) for v in xy.split(","))
        out[nid] = [x, y]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--secs", type=float, default=180)
    ap.add_argument("--pos", action="append", default=[], help="node ground truth: ID=x,y in metres")
    ap.add_argument("--note", default="")
    ap.add_argument("--cmd", action="append", default=[],
                    help='scheduled gateway command "SECONDS:CMD NAME ARG TARGET", e.g. "90:CMD TXPOWER 8 255"')
    a = ap.parse_args()
    sched = sorted((float(c.split(":", 1)[0]), c.split(":", 1)[1].strip()) for c in a.cmd)

    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    path = os.path.join(ROOT, "data", f"{a.name}.jsonl")
    meta = {"name": a.name, "port": a.port, "start": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "secs": a.secs, "positions_m": parse_pos(a.pos), "note": a.note}

    meta["scheduled_cmds"] = [f"{t:g}s: {c}" for t, c in sched]
    s = open_port(a.port)
    t0 = time.time()
    counts, buf, end = {}, b"", t0 + a.secs
    with open(path, "w", encoding="utf-8") as f:
        while time.time() < end:
            while sched and time.time() - t0 >= sched[0][0]:
                _, c = sched.pop(0)
                s.write((c + "\n").encode())
                f.write(json.dumps({"type": "host_cmd", "text": c, "t_host": round(time.time(), 3)}) + "\n")
                print(f"\n>> {c}", flush=True)
            buf += s.read(1024)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode(errors="replace").strip()
                if not line:
                    continue
                t = round(time.time(), 3)
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    msg = {"type": "log", "text": line}
                msg["t_host"] = t
                f.write(json.dumps(msg) + "\n")
                k = msg.get("type", "?")
                counts[k] = counts.get(k, 0) + 1
            print(f"\r{int(end - time.time()):4d}s left  {counts}", end="", flush=True)
    s.close()
    meta["counts"] = counts
    with open(os.path.join(ROOT, "data", f"{a.name}.meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
