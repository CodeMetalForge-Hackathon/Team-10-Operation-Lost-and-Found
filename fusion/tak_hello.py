"""tak_hello.py: verify WinTAK shows our Cursor-on-Target (CoT) markers.

Sends 3 node markers + 1 "possible survivor" marker around an origin, refreshed every 5 s.
No dependencies beyond the Python standard library.

Usage (Windows, same laptop as WinTAK):
  python fusion/tak_hello.py --lat 42.35 --lon -71.05             # unicast to 127.0.0.1:4242
  python fusion/tak_hello.py --lat 42.35 --lon -71.05 --port 6969 # try another input port
  python fusion/tak_hello.py --lat 42.35 --lon -71.05 --multicast # 239.2.3.1:6969 (visible to other TAK users on the LAN!)

Replace --lat/--lon with the venue's coordinates (right-click the building in WinTAK or Google Maps).
"""
import argparse
import math
import socket
import time
from datetime import datetime, timedelta, timezone

M_PER_DEG_LAT = 111_320.0


def local_to_latlon(lat0, lon0, east_m, north_m):
    lat = lat0 + north_m / M_PER_DEG_LAT
    lon = lon0 + east_m / (M_PER_DEG_LAT * math.cos(math.radians(lat0)))
    return lat, lon


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def cot_point(uid, cot_type, lat, lon, callsign, remarks, stale_s=30, ce=5.0):
    now = datetime.now(timezone.utc)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<event version="2.0" uid="{uid}" type="{cot_type}" how="m-g" '
        f'time="{iso(now)}" start="{iso(now)}" stale="{iso(now + timedelta(seconds=stale_s))}">'
        f'<point lat="{lat:.7f}" lon="{lon:.7f}" hae="0" ce="{ce}" le="9999999"/>'
        f'<detail><contact callsign="{callsign}"/><remarks>{remarks}</remarks></detail>'
        f"</event>"
    ).encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True, help="origin latitude (command post)")
    ap.add_argument("--lon", type=float, required=True, help="origin longitude (command post)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4242)
    ap.add_argument("--multicast", action="store_true", help="send to 239.2.3.1:6969 (shared SA channel)")
    ap.add_argument("--duration", type=int, default=120, help="seconds to keep refreshing")
    args = ap.parse_args()

    host, port = (("239.2.3.1", 6969) if args.multicast else (args.host, args.port))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    if args.multicast:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

    # Local frame: metres east/north of the command post.
    nodes = {1: (5.0, 5.0), 2: (10.0, 5.0), 3: (7.5, 10.0)}
    survivor = (7.0, 7.0)

    print(f"Sending CoT to {host}:{port} for {args.duration}s ... check WinTAK near {args.lat}, {args.lon}")
    t_end = time.time() + args.duration
    while time.time() < t_end:
        for nid, (e, n) in nodes.items():
            lat, lon = local_to_latlon(args.lat, args.lon, e, n)
            sock.sendto(cot_point(f"T10-node-{nid}", "a-f-G-E-S", lat, lon,
                                  f"T10 Node {nid}", "Acoustic sensor node, batt 3.9V, 1 hop"), (host, port))
        lat, lon = local_to_latlon(args.lat, args.lon, *survivor)
        sock.sendto(cot_point("T10-src-1", "a-u-G", lat, lon, "T10 Possible survivor",
                              "TAP x3 heard by N1,N3. conf 0.8, +/-1.5 m", ce=1.5), (host, port))
        time.sleep(5)
    print("done")


if __name__ == "__main__":
    main()
