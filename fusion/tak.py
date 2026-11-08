"""tak.py: push the fusion picture to WinTAK / ATAK as Cursor-on-Target (CoT). Standard library only.

What responders see in TAK (from the fusion server's /tak, team decision 2026-11-08):
  * one marker per sensor node    (friendly ground sensor; "LOST" in the callsign when it stops reporting)
  * simple evidence at the node: callsign "T10 N2 TAP" / "FELT" / "VOICE" for 30 s after a cue,
    and the last cue + time in the remarks. No estimated survivor point is sent.
  (Legacy: pointed at a standalone heatmap.py /state, it still sends the "DIG HERE?" peak marker.)
Each item has one fixed uid and is re-sent only when it really changes, or every 20 s, so markers clear
themselves when the fusion host stops confirming them. Keep updates rare: WinTAK crashes if a marker is
updated while its details pane is open (close the pane after reading it).

Usage (WinTAK on the same laptop):
  python fusion/tak.py --lat 42.359389 --lon -71.056580                  # bridge from the fusion server's /tak
  python fusion/tak.py --lat ... --lon ... --state-url http://<pi-ip>:8000/tak   # fusion host on the Pi
  python fusion/tak.py --lat ... --lon ... --multicast --iface <pi-hotspot-ip>   # run on the Pi, all TAK devices
  python fusion/tak.py --lat ... --lon ... --state-url http://127.0.0.1:8000/state  # legacy standalone heatmap.py
  python fusion/tak.py --lat ... --lon ... --test                         # static test pattern, no fusion needed
  python fusion/tak.py ... --multicast    # 239.2.3.1:6969 SA channel: other TAK devices on the LAN see it too!

Local frame: metres, x and y as in the heatmap. The origin (0,0) is placed at --lat/--lon, +y points to
--heading degrees true (default 0 = north), +x is 90 degrees clockwise from +y. Put the origin on node N1
and set --heading to the direction N1->N5 if you want the TAK map to line up with the real room.
"""
import argparse
import json
import math
import socket
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape, quoteattr

M_PER_DEG_LAT = 111_320.0
UID_PREFIX = "T10"


# ----------------------------------------------------------------------------- geometry
class Frame:
    """Local metres (x right, y forward) -> WGS84, anchored at lat0/lon0, +y rotated to `heading` deg true."""

    def __init__(self, lat0, lon0, heading_deg=0.0):
        self.lat0, self.lon0 = lat0, lon0
        self.h = math.radians(heading_deg)

    def to_latlon(self, x, y):
        east = x * math.cos(self.h) + y * math.sin(self.h)
        north = -x * math.sin(self.h) + y * math.cos(self.h)
        lat = self.lat0 + north / M_PER_DEG_LAT
        lon = self.lon0 + east / (M_PER_DEG_LAT * math.cos(math.radians(self.lat0)))
        return lat, lon


# ----------------------------------------------------------------------------- CoT builders
def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _event(uid, cot_type, lat, lon, stale_s, detail, ce=5.0, how="m-g"):
    now = datetime.now(timezone.utc)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<event version="2.0" uid={quoteattr(uid)} type={quoteattr(cot_type)} how="{how}" '
        f'time="{_iso(now)}" start="{_iso(now)}" stale="{_iso(now + timedelta(seconds=stale_s))}">'
        f'<point lat="{lat:.7f}" lon="{lon:.7f}" hae="0" ce="{ce:.1f}" le="9999999"/>'
        f"<detail>{detail}</detail></event>"
    ).encode("utf-8")


def node_cot(frame, node, stale_s):
    """node: {"id", "x", "y", "alive", optional "floor", "remarks"}"""
    lat, lon = frame.to_latlon(node["x"], node["y"])
    alive = node.get("alive", True)
    callsign = node.get("callsign") or (f"T10 N{node['id']}" + ("" if alive else " LOST"))
    rem = node.get("remarks") or (
        f"Acoustic/vibration sensor node {node['id']}. "
        + ("Reporting" if alive else "NOT reporting (lost or out of range)")
    )
    detail = f"<contact callsign={quoteattr(callsign)}/><remarks>{escape(rem)}</remarks>"
    return _event(f"{UID_PREFIX}-node-{node['id']}", "a-f-G-E-S", lat, lon, stale_s, detail, ce=1.0)


def source_cot(frame, src, stale_s, idx=1):
    """src: {"x", "y", "radius" (m), "strength", optional "remarks"} -> 'possible survivor' point."""
    lat, lon = frame.to_latlon(src["x"], src["y"])
    callsign = "T10 DIG HERE?" if idx == 1 else f"T10 DIG HERE? #{idx}"
    rem = src.get("remarks") or (
        f"Possible survivor (acoustic/vibration fusion). Uncertainty +/-{src['radius']:.1f} m, "
        f"evidence strength {src.get('strength', 0):.2f}. Not a confirmed location."
    )
    detail = f"<contact callsign={quoteattr(callsign)}/><remarks>{escape(rem)}</remarks>"
    return _event(f"{UID_PREFIX}-src-{idx}", "a-u-G", lat, lon, stale_s, detail, ce=max(src["radius"], 0.5))


# ----------------------------------------------------------------------------- transport
class Sender:
    def __init__(self, host="127.0.0.1", port=4242, multicast=False, iface=None):
        if multicast:
            host, port = "239.2.3.1", 6969
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        if multicast:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            if iface:
                # Pick the network multicast goes out on. Needed on a Pi that only runs its own
                # hotspot: with no default route, sending to 239.2.3.1 fails "Network unreachable".
                self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))

    def send(self, payload):
        self.sock.sendto(payload, self.addr)


# ----------------------------------------------------------------------------- picture -> CoT
def picture_from_heatmap_state(s):
    """Adapter for fusion/heatmap.py /state. Returns {"nodes": [...], "sources": [...], "note": str}.
    A future fusion server only needs its own adapter producing the same shape."""
    nodes = [{"id": n["id"], "x": n["x"], "y": n["y"], "alive": n["alive"], "floor": n.get("floor")}
             for n in s.get("nodes", [])]
    sources = []
    if s.get("peak"):
        p = s["peak"]
        sources.append({"x": p["x"], "y": p["y"], "radius": p["radius"], "strength": p["strength"]})
    note = ""
    if s.get("hail_age") is not None:
        note = f"HAIL sent {s['hail_age']:.0f} s ago"
    return {"nodes": nodes, "sources": sources, "note": note}


def picture_from_json(s):
    """Accept the fusion server's /tak picture as-is, or heatmap.py's /state via its adapter."""
    if "sources" in s:  # fusion/server.py GET /tak (fusion/tak_picture.py)
        return s
    if "v" in s:  # the dashboard's /state: no node positions in it
        raise ValueError("that is the dashboard /state; point --state-url at the server's /tak")
    return picture_from_heatmap_state(s)  # standalone fusion/heatmap.py /state


class Publisher:
    """One fixed uid per item; send only on a real change or every REFRESH_S.

    WinTAK crashes ('Must create DependencySource on same Thread...') if an item is updated while its
    details pane is open, so updates are kept rare and their text fixed.
    No drawn uncertainty circle for now: circles seemed to stack in WinTAK, but that test was confounded
    (several old bridge processes were still sending circles). Uncertainty is the marker's ce + remarks.
    A source is "changed" when it
    moves to another 0.3 m cell or its uncertainty changes by a 0.3 m step.
    """
    REFRESH_S, STALE_S, CLEAR_S, STEP_M = 20.0, 60.0, 1.0, 0.3

    def __init__(self, sender, frame):
        self.sender, self.frame = sender, frame
        self.last = {}  # uid -> (key, time sent)
        self.shown = None  # last source sent, so a clear happens in place

    def _send(self, uid, key, payload, now):
        old = self.last.get(uid)
        if old is None or old[0] != key or now - old[1] >= self.REFRESH_S:
            self.sender.send(payload())
            self.last[uid] = (key, now)
            return 1
        return 0

    def update(self, pic, now=None):
        now = time.time() if now is None else now
        f, n = self.frame, 0
        for node in pic["nodes"]:
            # Re-send on LOST/back or a callsign change (a new evidence kind); remarks ride the 20 s refresh.
            key = (node["alive"], node.get("callsign"))
            n += self._send(f"node{node['id']}", key, lambda node=node: node_cot(f, node, self.STALE_S), now)
        src = pic["sources"][0] if pic["sources"] else None
        if src:
            key = tuple(round(v / self.STEP_M) for v in (src["x"], src["y"], src["radius"]))
            n += self._send("src", key, lambda: source_cot(f, src, self.STALE_S), now)
            self.shown = src
        elif "src" in self.last:  # fusion lost confidence: clear the marker once
            del self.last["src"]
            self.sender.send(source_cot(f, dict(self.shown, strength=0.0, remarks="Cleared"), self.CLEAR_S))
            n += 1
        return n



def test_picture():
    return {"nodes": [{"id": 1, "x": 0.0, "y": 0.0, "alive": True, "floor": -22},
                      {"id": 2, "x": 3.0, "y": 0.0, "alive": True, "floor": -24},
                      {"id": 5, "x": 0.0, "y": 3.0, "alive": False, "floor": -24}],
            "sources": [{"x": 2.0, "y": 0.8, "radius": 0.8, "strength": 1.5}], "note": "TEST PATTERN"}


def main():
    ap = argparse.ArgumentParser(description="Push the T10 fusion picture to TAK as CoT over UDP.")
    ap.add_argument("--lat", type=float, required=True, help="latitude of local (0,0), e.g. node N1")
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--heading", type=float, default=0.0, help="true bearing of the local +y axis, degrees")
    ap.add_argument("--state-url", default="http://127.0.0.1:8000/tak",
                    help="fusion server /tak (default), or a standalone heatmap.py /state")
    ap.add_argument("--test", action="store_true", help="send a fixed test pattern instead of polling fusion")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4242)
    ap.add_argument("--multicast", action="store_true", help="239.2.3.1:6969 (shared SA channel on the LAN)")
    ap.add_argument("--iface", default=None,
                    help="with --multicast: this machine's IP on the network to send on (e.g. the Pi's hotspot IP)")
    ap.add_argument("--period", type=float, default=2.0)
    a = ap.parse_args()

    frame = Frame(a.lat, a.lon, a.heading)
    sender = Sender(a.host, a.port, a.multicast, a.iface)
    pub = Publisher(sender, frame)
    print(f"# CoT -> {sender.addr[0]}:{sender.addr[1]} every {a.period:g}s; origin {a.lat:.6f},{a.lon:.6f} "
          f"heading {a.heading:g}; source: {'TEST PATTERN' if a.test else a.state_url}", flush=True)
    last_err = None
    while True:
        t = time.time()
        try:
            if a.test:
                pic = test_picture()
            else:
                pic = picture_from_json(json.load(urllib.request.urlopen(a.state_url, timeout=2)))
            n = pub.update(pic)
            if last_err:
                print("# fusion reachable again", flush=True)
                last_err = None
            src = pic["sources"][0] if pic["sources"] else None
            print(f"# sent {n} CoT | nodes alive {[x['id'] for x in pic['nodes'] if x['alive']]} | "
                  f"dig-here {'(%.1f, %.1f) +/-%.1f m' % (src['x'], src['y'], src['radius']) if src else 'none'}",
                  flush=True)
        except Exception as e:  # keep running: fusion host may restart; markers simply go stale meanwhile
            if str(e) != last_err:
                print(f"# fusion not reachable ({e}); TAK markers will go stale", flush=True)
                last_err = str(e)
        time.sleep(max(0.1, a.period - (time.time() - t)))


if __name__ == "__main__":
    main()
