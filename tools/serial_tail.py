"""serial_tail.py: print serial output from one or more boards for N seconds.

Usage:
  python tools/serial_tail.py COM12                 # 15 s
  python tools/serial_tail.py COM12 COM5 --secs 30  # several boards, prefixed by port
  python tools/serial_tail.py COM12 --reset         # pulse reset first to catch the boot line
"""
import argparse
import threading
import time

import serial


def tail(port, secs, reset):
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 921600, 0.2
    s.dtr = False  # set BEFORE open so we don't hold the chip in reset / boot mode
    s.rts = False
    for attempt in range(40):  # something on Windows briefly grabs the port; retry ~10 s
        try:
            s.open()
            break
        except serial.SerialException as e:
            err = e
            time.sleep(0.25)
    else:
        print(f"[{port}] cannot open: {err}")
        return
    if reset:  # pulse EN via RTS while BOOT (DTR) stays released -> normal run mode
        s.rts = True
        time.sleep(0.1)
        s.rts = False
    end = time.time() + secs
    buf = b""
    while time.time() < end:
        buf += s.read(512)
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            print(f"[{port}] {line.decode(errors='replace').rstrip()}", flush=True)
    s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ports", nargs="+")
    ap.add_argument("--secs", type=float, default=15)
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    ts = [threading.Thread(target=tail, args=(p, a.secs, a.reset)) for p in a.ports]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


if __name__ == "__main__":
    main()
