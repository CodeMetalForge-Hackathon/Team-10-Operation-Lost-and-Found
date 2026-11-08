"""tak_overlay.py: put the drone camera mosaic into WinTAK / ATAK as a georeferenced image (KMZ GroundOverlay).

The mosaic's metre frame is the heatmap's frame (origin = first dropped node, see drone/live_mosaic.py), and
tak.py turns heatmap metres into lat/lon with --lat/--lon/--heading. This applies the SAME conversion to the
image, so the node markers from tak.py sit exactly on the nodes in the photo. Use identical --lat/--lon/--heading
for both. Uncovered parts of the mosaic are transparent, so the satellite map shows around it.

  # one-off file: drag it into WinTAK (or Import Manager)
  python fusion/tak_overlay.py --mosaic http://PI-IP:8080 --lat 42.359389 --lon -71.056580 --out data/tak/t10_mosaic.kmz
  python fusion/tak_overlay.py --mosaic data/camera/walk3_mosaic --lat ... --lon ...      # a saved mosaic

  # live: serve a KMZ that always holds the latest mosaic; in WinTAK import http://THIS-HOST:8090/link.kml once
  # (a KML network link: WinTAK re-downloads the overlay every --refresh seconds)
  python fusion/tak_overlay.py --mosaic :8080 --lat ... --lon ... --serve 8090

--heading: true bearing of the camera's "up" (top of its first frame) when the walk/flight started, degrees.
"""
import argparse
import io
import json
import math
import os
import sys
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tak import M_PER_DEG_LAT, Frame  # noqa: E402  (same geometry as the CoT markers)


def load_mosaic(src):
    """(png bytes, meta dict) from a camera address (http://..., or :PORT on this host) or a file prefix."""
    if src.startswith(("http", ":")):
        base = ("http://127.0.0.1" + src) if src.startswith(":") else src.rstrip("/")
        meta = json.load(urllib.request.urlopen(base + "/mosaic.json", timeout=5))
        png = urllib.request.urlopen(base + "/mosaic.png", timeout=10).read()
    else:
        with open(src + ".json") as f:
            meta = json.load(f)
        with open(src + ".png", "rb") as f:
            png = f.read()
    if not meta.get("width"):
        raise ValueError("no mosaic yet")
    return png, meta


def overlay_geometry(px_to_m, w, h, frame):
    """LatLonBox for an image whose pixels map to local metres by px_to_m (2x3), w x h px.
    Returns (north, south, east, west, rotation_deg_ccw). The image->metres map is a similarity (the camera
    frame is not mirrored), which is exactly what LatLonBox + rotation can express."""
    A = np.asarray(px_to_m, float)
    hd = frame.h
    F = np.array([[math.cos(hd), math.sin(hd)], [-math.sin(hd), math.cos(hd)]])  # local (x, y) -> (east, north)
    J = F @ A[:, :2]                       # east/north metres per image px (u right, v down)
    if np.linalg.det(J) > 0:
        raise ValueError("mosaic frame is mirrored; LatLonBox cannot express it")
    s = math.hypot(J[0, 0], J[1, 0])       # metres per px
    rot = math.degrees(math.atan2(J[1, 0], J[0, 0]))  # direction of the image's +u, CCW from east
    cx, cy = A @ np.array([w / 2, h / 2, 1.0])
    lat_c, lon_c = frame.to_latlon(cx, cy)
    dlat = (h * s / 2) / M_PER_DEG_LAT
    dlon = (w * s / 2) / (M_PER_DEG_LAT * math.cos(math.radians(frame.lat0)))
    return lat_c + dlat, lat_c - dlat, lon_c + dlon, lon_c - dlon, rot


def build_kmz(png, meta, frame, max_side=2048, opacity=1.0, name="T10 camera mosaic"):
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    alpha = np.where(img.max(axis=2) > 0, 255, 0).astype(np.uint8)  # mosaic leaves uncovered areas pure black
    k = min(1.0, max_side / max(img.shape[:2]))  # big textures are slow (or refused) in TAK clients
    rgba = np.dstack([img, alpha])
    if k < 1:
        rgba = cv2.resize(rgba, (round(img.shape[1] * k), round(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
    h, w = rgba.shape[:2]
    A = np.asarray(meta["px_to_m"], float).copy()
    A[:, 0] *= img.shape[1] / w            # px of the resized image -> px of the original
    A[:, 1] *= img.shape[0] / h
    n, s, e, wst, rot = overlay_geometry(A, w, h, frame)
    color = f"{round(255 * opacity):02x}ffffff"
    drops = ", ".join(f"N{d['id']}" for d in meta.get("drops", [])) or "none"
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{name}</name>
<GroundOverlay><name>{name}</name>
<description>Drone camera mosaic, {meta.get('keyframes', '?')} keyframes, nodes dropped: {drops}. Built {time.strftime('%H:%M:%S')}.</description>
<color>{color}</color><Icon><href>files/mosaic.png</href></Icon>
<LatLonBox><north>{n:.8f}</north><south>{s:.8f}</south><east>{e:.8f}</east><west>{wst:.8f}</west><rotation>{rot:.3f}</rotation></LatLonBox>
</GroundOverlay></Document></kml>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)  # KMZ convention: the first entry is the KML
        z.writestr("files/mosaic.png", cv2.imencode(".png", rgba)[1].tobytes())
    return buf.getvalue(), {"north": n, "south": s, "east": e, "west": wst, "rotation": rot, "size": [w, h]}


def network_link(url, refresh_s, name="T10 camera mosaic (live)"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><NetworkLink><name>{name}</name>
<Link><href>{url}</href><refreshMode>onInterval</refreshMode><refreshInterval>{refresh_s}</refreshInterval></Link>
</NetworkLink></kml>"""


def serve(a, frame):
    cache = {"key": None, "kmz": b""}

    def latest():
        png, meta = load_mosaic(a.mosaic)
        key = (meta.get("version"), meta.get("t"), len(meta.get("drops", [])))
        if key != cache["key"]:
            cache["kmz"], info = build_kmz(png, meta, frame, a.max_side, a.opacity)
            cache["key"] = key
            print(f"# overlay rebuilt: {meta.get('keyframes')} keyframes, {info['size'][0]}x{info['size'][1]} px, "
                  f"rotation {info['rotation']:.1f} deg", flush=True)
        return cache["kmz"]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/link.kml":
                host = self.headers.get("Host") or f"127.0.0.1:{a.serve}"
                body = network_link(f"http://{host}/t10_mosaic.kmz", a.refresh).encode()
                return self._send(200, body, "application/vnd.google-earth.kml+xml")
            if path == "/t10_mosaic.kmz":
                try:
                    return self._send(200, latest(), "application/vnd.google-earth.kmz")
                except Exception as e:  # camera down / no mosaic yet: TAK keeps the last overlay it had
                    return self._send(503, str(e).encode(), "text/plain")
            self._send(404, b"try /link.kml or /t10_mosaic.kmz", "text/plain")

    srv = ThreadingHTTPServer((a.bind, a.serve), H)
    print(f"# serving the live overlay: in WinTAK import http://<this-host>:{a.serve}/link.kml "
          f"(refresh every {a.refresh} s); file: /t10_mosaic.kmz", flush=True)
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser(description="Drone camera mosaic -> georeferenced KMZ overlay for TAK.")
    ap.add_argument("--mosaic", required=True, help="camera address (http://PI-IP:8080 or :8080) or a file prefix")
    ap.add_argument("--lat", type=float, required=True, help="latitude of local (0,0) = the first dropped node")
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--heading", type=float, default=0.0, help="true bearing of the camera's 'up' at the start")
    ap.add_argument("--out", default="data/tak/t10_mosaic.kmz", help="one-off KMZ file")
    ap.add_argument("--serve", type=int, default=None, help="serve a live KMZ + link.kml on this port instead")
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--refresh", type=int, default=15, help="network-link refresh, seconds")
    ap.add_argument("--max-side", type=int, default=2048)
    ap.add_argument("--opacity", type=float, default=1.0)
    a = ap.parse_args()
    frame = Frame(a.lat, a.lon, a.heading)
    if a.serve:
        return serve(a, frame)
    png, meta = load_mosaic(a.mosaic)
    kmz, info = build_kmz(png, meta, frame, a.max_side, a.opacity)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "wb") as f:
        f.write(kmz)
    print(f"wrote {a.out} ({len(kmz) // 1024} kB): {info['size'][0]}x{info['size'][1]} px, "
          f"N {info['north']:.6f} S {info['south']:.6f} E {info['east']:.6f} W {info['west']:.6f}, "
          f"rotation {info['rotation']:.1f} deg. Drag it into WinTAK.")


if __name__ == "__main__":
    main()
