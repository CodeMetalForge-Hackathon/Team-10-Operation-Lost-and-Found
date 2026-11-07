"""Simulated gateway lines.

Every line is the JSON contract from docs/ARCHITECTURE.md.
Nothing here was recorded from hardware.
"""

import json
import time


def _line(payload):
    return json.dumps(payload, separators=(",", ":"))


def beacon(src, seq, hops=1, rssi=-58):
    return _line(
        {
            "type": "beacon",
            "src": src,
            "seq": seq,
            "hops": hops,
            "rssi_last": rssi,
            "batt_mv": 3950,
            "floor_db": -62,
            "nbrs": [[1, -55], [2, -71]] if src == 3 else [[3, -61]],
        }
    )


def feat(src, seq):
    return _line(
        {
            "type": "feat",
            "src": src,
            "seq": seq,
            "hops": 1,
            "rssi_last": -58,
            "t_ms": 51234,
            "rms_db": -40,
            "low_db": -50,
            "voice_db": -42,
            "high_db": -55,
            "peak_db": -30,
        }
    )


def tap(src, seq):
    return _line(
        {
            "type": "event",
            "src": src,
            "seq": seq,
            "hops": 2,
            "rssi_last": -70,
            "t_ms": 51800,
            "kind": "TAP_PATTERN",
            "peak_db": -20,
            "voice_db": -35,
            "count": 3,
            "conf": 80,
        }
    )


def range_report():
    return _line({"type": "range", "src": 2, "chirper": 3, "delay_us": 10450, "snr_db": 18})


def device_seen(src, seq):
    return _line(
        {
            "type": "device_seen",
            "src": src,
            "seq": seq,
            "hops": 1,
            "rssi_last": -61,
            "t_ms": 60000,
            "devs": [["9f3a01c2", "BLE_APPLE", -52, 14], ["07bb4e10", "WIFI_PROBE", -70, 2]],
        }
    )


# Delays are seconds from the start of the script. Node 3 stops talking after 2.2 s.
# Node 4 is kept alive by keepalive_line so the dashboard can show one inactive node.
SCRIPT = [
    (0.0, beacon(3, 1)),
    (0.4, feat(3, 2)),
    (1.0, tap(3, 3)),
    (1.4, range_report()),
    (1.8, device_seen(4, 1)),
    (2.0, beacon(4, 2)),
    (2.2, beacon(3, 4)),
]

KEEPALIVE_SRC = 4


def keepalive_line(seq):
    return beacon(KEEPALIVE_SRC, seq, hops=1, rssi=-61)


def main(argv=None):
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="sim.demo",
        description="Print simulated gateway JSON lines. Not a hardware recording.",
    )
    parser.add_argument("--once", action="store_true", help="Print the script and exit. Do not keep node 4 alive.")
    args = parser.parse_args(argv)
    sys.stderr.write("simulated gateway lines. Not a hardware recording.\n")
    start = time.monotonic()
    for at, line in SCRIPT:
        time.sleep(max(0.0, at - (time.monotonic() - start)))
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    if args.once:
        return 0
    seq = 10
    while True:
        time.sleep(2.0)
        sys.stdout.write(keepalive_line(seq) + "\n")
        sys.stdout.flush()
        seq = (seq + 1) % 65536
