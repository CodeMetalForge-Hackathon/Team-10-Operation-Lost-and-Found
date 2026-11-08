"""live_mosaic.py: run the stitcher live on the Pi camera (or on a video file) and serve the result over HTTP.

  python3 drone/live_mosaic.py                         # Pi: Camera Module 3 Wide, serve on :8080
  python3 drone/live_mosaic.py --record data/walk2 --mask-bottom 0.2   # hand-carried: save frames, hide feet
  python drone/live_mosaic.py --video data/walk2/%06d.jpg              # laptop: same server fed from a recording

HTTP (any browser on the same network, e.g. http://<pi-ip>:8080/):
  GET  /              a page showing the live frame and the growing mosaic (SPACE = drop the next node here)
  GET  /mosaic.png    latest mosaic            GET /mosaic.json   its metadata (px_to_m etc., see mosaic.py)
  GET  /frame.jpg     latest camera frame      GET /status        counters
  POST /drop[?id=N]   node N (default: the next in --drop-order) was dropped right under the camera now
  POST /undo          forget the last drop     GET  /drops        node positions in metres (for heatmap.py)
  POST /reset         start a new mosaic (and forget the drops; the published TAK map is kept)
  POST /scan_done     "the scan is finished": freeze the current mosaic as the map TAK shows (again = republish)
  GET  /final.png     the published mosaic      GET /final.json   its metadata (+ final_version, published_at)
                      (503 until the first Scan done; fusion/tak_overlay.py serves these to WinTAK)
The heatmap page uses /mosaic.png + /mosaic.json as its background and /drops as the node positions.

Metre frame: origin at the first dropped node, x right / y up in the camera's first frame, scale from the camera
height and field of view. Nodes and photo share it, so the photo needs no manual alignment.
"""
import argparse
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mosaic import Mosaicker  # noqa: E402

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>T10 camera mosaic</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;background:#111;color:#ddd;font:14px system-ui}header{padding:8px 12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
main{display:flex;flex-wrap:wrap;gap:8px;padding:0 8px}figure{margin:0}img{max-width:100%;background:#000}
#m{max-height:80vh}#f{width:320px}button{background:#333;color:#ddd;border:1px solid #555;padding:4px 10px}
#d{color:#fc6}#sd{background:#264;border-color:#4a8}#tk{color:#8c8}</style></head>
<body><header><b>T10 camera mosaic</b><span id="s">...</span>
<button onclick="post('/drop')">Drop node (SPACE)</button><button onclick="post('/undo')">Undo drop</button>
<button onclick="if(confirm('Start a new mosaic and forget all drops?'))post('/reset')">New mosaic</button><span id="d"></span>
<button id="sd" onclick="post('/scan_done')" title="Freeze this mosaic as the floor map TAK shows">Scan done &rarr; TAK</button><span id="tk">TAK map: not published</span></header>
<main><figure><img id="f"><figcaption>live frame (+ = where a dropped node lands)</figcaption></figure>
<figure><img id="m"><figcaption>mosaic</figcaption></figure></main>
<script>
function post(p){fetch(p,{method:'POST'}).then(r=>r.json()).then(j=>{if(!j.ok)alert(j.error);tick()})}
document.addEventListener('keydown',e=>{if(e.code==='Space'&&!e.repeat){e.preventDefault();post('/drop')}});
function tick(){const t=Date.now();document.getElementById('f').src='/frame.jpg?'+t;
fetch('/status').then(r=>r.json()).then(s=>{document.getElementById('s').textContent=
`${s.state} | ${s.keyframes} keyframes | ${s.fps} fps | lost ${s.lost}/${s.frames}`;
const m=document.getElementById('m');if(m.dataset.v!=s.version){m.dataset.v=s.version;m.src='/mosaic.png?'+s.version}
document.getElementById('tk').textContent=s.final_version?`TAK map: v${s.final_version}, ${new Date(s.final_t*1000).toLocaleTimeString()} (${s.final_keyframes} keyframes)`:'TAK map: not published'}).catch(()=>{});
fetch('/drops').then(r=>r.json()).then(d=>{document.getElementById('d').textContent=
(d.drops.length?'dropped: '+d.drops.map(x=>`N${x.id} (${x.x.toFixed(1)}, ${x.y.toFixed(1)}) m`).join(', '):'no nodes dropped')+
(d.next_id!=null?` | next: N${d.next_id}`:' | all dropped')}).catch(()=>{})}
setInterval(tick,1000);tick();
</script></body></html>"""


class Live:
    def __init__(self, a):
        self.a = a
        self.lock = threading.Lock()
        self.reset_flag = False
        self.frame_jpg = b""
        self.mosaic_png = b""
        self.meta = {}
        self.version = 0
        self.status = {"state": "starting", "frames": 0, "lost": 0, "keyframes": 0, "fps": 0.0, "version": 0,
                       "final_version": 0, "final_t": None, "final_keyframes": 0}
        self.publish_lock = threading.Lock()  # the camera loop and Scan done both render
        # The published ("final") mosaic: what TAK shows. Changes only on Scan done; kept across /reset and restarts.
        self.final_png, self.final_meta = b"", {}
        self._load_final()
        self.m = self._new()
        self.drop_order = [int(v) for v in a.drop_order.split(",")]
        self.drops = []          # {"id", "ref": [u, v] first-frame px, "t"}
        self.here = None         # camera centre (point under the camera) in first-frame px, last tracked frame
        self.drops_changed = False
        # metres per first-frame pixel, from the camera height and field of view
        self.m_per_ref = a.cam_height / ((a.work_width / 2) / np.tan(np.radians(a.hfov) / 2))

    def _new(self):
        return Mosaicker(work_width=self.a.work_width, mask_bottom=self.a.mask_bottom)

    # ---- node drops (call with self.lock held) ----
    def ref_to_m(self):
        """First-frame px -> metres: origin at the first drop (before any drop: the first frame's centre)."""
        if self.drops:
            ox, oy = self.drops[0]["ref"]
        else:
            ox, oy = self.a.work_width / 2, self.a.work_width * self.a.height_px / self.a.width / 2
        k = self.m_per_ref
        return [[k, 0.0, -k * ox], [0.0, -k, k * oy]]

    def drops_info(self):
        A = self.ref_to_m()
        to_m = lambda u, v: (A[0][0] * u + A[0][2], A[1][1] * v + A[1][2])  # noqa: E731
        drops = [dict(d, x=round(to_m(*d["ref"])[0], 3), y=round(to_m(*d["ref"])[1], 3)) for d in self.drops]
        nxt = self.next_id()
        here = [round(v, 3) for v in to_m(*self.here)] if self.here is not None else None
        return {"nodes": {str(d["id"]): [d["x"], d["y"]] for d in drops}, "drops": drops, "next_id": nxt,
                "camera_m": here, "ref_to_m": A}

    def next_id(self):
        done = {d["id"] for d in self.drops}
        return next((i for i in self.drop_order if i not in done), None)

    def drop(self, node=None):
        """node: the ID dropped (the heatmap page sends the next node that is reporting); default: next in order."""
        if self.here is None:
            return {"ok": False, "error": "camera not tracking yet"}
        node = node if node is not None else self.next_id()
        if node is None:
            return {"ok": False, "error": "all nodes in --drop-order already dropped"}
        if any(d["id"] == node for d in self.drops):
            return {"ok": False, "error": f"N{node} was already dropped (Undo drop first to move it)"}
        self.drops.append({"id": node, "ref": [round(float(v), 2) for v in self.here], "t": round(time.time(), 2)})
        self.m.restart_after = float("inf")  # never auto-restart the mosaic under placed nodes
        self.drops_changed = True
        self._save_drops()
        return {"ok": True, "id": node, **self.drops_info()}

    def undo(self):
        if not self.drops:
            return {"ok": False, "error": "nothing to undo"}
        d = self.drops.pop()
        self.drops_changed = True
        self._save_drops()
        return {"ok": True, "undone": d["id"], **self.drops_info()}

    def _save_drops(self):
        if self.a.out:  # keep the drops next to the saved mosaic (a power cut keeps them too)
            with open(self.a.out + "_drops.json.tmp", "w") as f:
                json.dump(self.drops_info(), f)
            os.replace(self.a.out + "_drops.json.tmp", self.a.out + "_drops.json")

    def frames(self):
        """Yield BGR frames from the Pi camera or a video file."""
        if self.a.video:
            cap = cv2.VideoCapture(self.a.video)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            i = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    return
                if i % self.a.step == 0:
                    yield frame
                    if self.a.realtime:
                        time.sleep(self.a.step / fps)
                i += 1
        from picamera2 import Picamera2  # Pi only
        cam = Picamera2()
        # Full-sensor binned mode (2304x1296) keeps the whole 102 deg field of view; the 1536x864 mode is a crop.
        cfg = cam.create_video_configuration(main={"size": (self.a.width, self.a.height_px), "format": "RGB888"},
                                             raw={"size": (2304, 1296)}, buffer_count=4)
        cam.configure(cfg)
        # Camera Module 3 has autofocus. Lock focus at the floor (lens position is in dioptres = 1/metres):
        # continuous AF would hunt while walking, and an unset lens can sit anywhere, which blurs every frame.
        controls = {"AfMode": 0, "LensPosition": 1.0 / self.a.focus_m if self.a.focus_m else 1.0 / self.a.cam_height,
                    # Cap the sensor frame rate (default 10). Measured with drone/fps_ramp.sh: up to 14 fps holds >= 4.74 V on the
                    # team power bank; an early brownout happened at start-up with all cores. Re-check any new power bank.
                    "FrameDurationLimits": (int(1e6 / self.a.fps), int(1e6 / self.a.fps))}
        if self.a.shutter_us:
            controls.update({"ExposureTime": self.a.shutter_us, "AnalogueGain": self.a.gain})
        cam.set_controls(controls)
        cam.start()
        time.sleep(1.0)  # let auto-exposure settle
        try:
            while True:
                yield cam.capture_array("main")  # "RGB888" is BGR byte order, what OpenCV expects
        finally:
            cam.stop()

    def publish(self):
        with self.publish_lock:
            self._publish()

    def _publish(self):
        img, M = self.m.render(max_side=self.a.max_side)
        ok, png = cv2.imencode(".png", img)
        px_to_ref = np.linalg.inv(M)[:2]
        with self.lock:
            info = self.drops_info()
        ref_to_m = np.array(info["ref_to_m"])
        px_to_m = ref_to_m[:, :2] @ px_to_ref
        px_to_m[:, 2] += ref_to_m[:, 2]
        r6 = lambda A: [[round(float(v), 6) for v in row] for row in A]  # noqa: E731
        meta = {"width": img.shape[1], "height": img.shape[0], "m_per_px": round(self.m_per_ref * px_to_ref[0, 0], 5),
                "px_to_m": r6(px_to_m), "aligned": False,
                # first-frame pixels: stable while the mosaic grows, so the heatmap stores its alignment in these
                "px_to_ref": r6(px_to_ref), "ref_to_m": r6(ref_to_m), "drops": info["drops"],
                "keyframes": len(self.m.keyframes), "hfov_deg": self.a.hfov, "height_m": self.a.cam_height,
                "t": time.time()}
        with self.lock:
            self.version += 1
            self.mosaic_png, self.meta = png.tobytes(), dict(meta, version=self.version)
            self.status["version"] = self.version
        if self.a.out:
            _write_atomic(self.a.out + ".png", png.tobytes())
            _write_atomic(self.a.out + ".json", json.dumps(meta).encode())

    # ---- Scan done: the published map ----
    def scan_done(self):
        """Freeze a fresh render of the mosaic as the map TAK shows. Pressing again republishes."""
        with self.lock:
            empty = not self.m.keyframes
        if empty:
            return {"ok": False, "error": "no mosaic yet: fly (walk) the area first"}
        self.publish()  # fresh render: includes keyframes added since the last periodic publish
        with self.lock:
            fv = int(self.final_meta.get("final_version", 0)) + 1
            self.final_meta = dict(self.meta, final_version=fv, published_at=round(time.time(), 2))
            self.final_png = self.mosaic_png
            meta, png = self.final_meta, self.final_png
            self._final_status()
        if self.a.out:
            _write_atomic(self.a.out + "_final.png", png)
            _write_atomic(self.a.out + "_final.json", json.dumps(meta).encode())
        return {"ok": True, "final_version": fv, "published_at": meta["published_at"],
                "keyframes": meta.get("keyframes"), "drops": [d["id"] for d in meta.get("drops", [])]}

    def _final_status(self):
        m = self.final_meta
        self.status.update(final_version=m.get("final_version", 0), final_t=m.get("published_at"),
                           final_keyframes=m.get("keyframes", 0))

    def _load_final(self):
        """After a restart, keep serving the map TAK already has."""
        if not self.a.out:
            return
        try:
            with open(self.a.out + "_final.json") as f:
                meta = json.load(f)
            with open(self.a.out + "_final.png", "rb") as f:
                png = f.read()
        except (OSError, ValueError):
            return
        if meta.get("final_version") and png:
            self.final_png, self.final_meta = png, meta
            self._final_status()
            print(f"# published TAK map v{meta['final_version']} restored from {self.a.out}_final.png", flush=True)

    def run(self):
        try:
            self._loop()
        finally:  # also on Ctrl+C / pkill: write the final mosaic
            if self.m.keyframes:
                self.publish()
            with self.lock:
                self.status["state"] = "ended"
            print(f"# done: {len(self.m.keyframes)} keyframes, lost {self.m.stats['lost']}/{self.m.stats['frames']}",
                  flush=True)

    def _loop(self):
        if self.a.record:
            os.makedirs(self.a.record, exist_ok=True)
        n_rec, t_sync = 0, time.time()
        t_last_pub, t_fps, n_fps, dirty = 0.0, time.time(), 0, False
        for frame in self.frames():
            if self.reset_flag:
                with self.lock:
                    self.m, self.reset_flag, dirty = self._new(), False, False
                    self.drops, self.here, self.drops_changed = [], None, True
                    self._save_drops()
            if self.a.record:
                # One JPEG per frame + a disk sync every 2 s: a power cut loses at most ~2 s of the walk.
                # (An .mp4 written by VideoWriter is unreadable unless it is closed cleanly.)
                n_rec += 1
                cv2.imwrite(os.path.join(self.a.record, f"{n_rec:06d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if time.time() - t_sync >= 2 and hasattr(os, "sync"):  # os.sync is Linux/Pi only
                    os.sync()
                    t_sync = time.time()
            with self.lock:  # add() swaps state that drop() reads
                result = self.m.add(frame)
                if result != "lost":
                    h, w = self.m.keyframes[0][0].shape[:2]
                    self.here = (self.m.last[2] @ [w / 2, h / 2, 1.0])[:2]  # the point straight below the camera
                dirty |= result == "keyframe" or self.drops_changed
                self.drops_changed = False
            n_fps += 1
            now = time.time()
            small = cv2.resize(frame, (480, round(frame.shape[0] * 480 / frame.shape[1])))
            cx, cy = small.shape[1] // 2, small.shape[0] // 2
            cv2.drawMarker(small, (cx, cy), (0, 255, 255), cv2.MARKER_CROSS, 24, 2)  # where a dropped node lands
            if result == "lost":
                cv2.putText(small, "LOST: slow down / go back", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            with self.lock:
                self.frame_jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
                st = self.status
                st.update(state=result, frames=self.m.stats["frames"], lost=self.m.stats["lost"],
                          keyframes=len(self.m.keyframes))
                if now - t_fps >= 2:
                    st["fps"], t_fps, n_fps = round(n_fps / (now - t_fps), 1), now, 0
            if dirty and now - t_last_pub >= self.a.publish_s:
                self.publish()
                t_last_pub, dirty = now, False


def _write_atomic(path, data):
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)


def make_handler(live):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")  # the heatmap page on another host reads these
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            with live.lock:
                routes = {
                    "/": (PAGE.encode(), "text/html; charset=utf-8"),
                    "/frame.jpg": (live.frame_jpg, "image/jpeg"),
                    "/mosaic.png": (live.mosaic_png, "image/png"),
                    "/mosaic.json": (json.dumps(live.meta).encode(), "application/json"),
                    "/status": (json.dumps(live.status).encode(), "application/json"),
                    "/drops": (json.dumps(live.drops_info()).encode(), "application/json"),
                    "/final.png": (live.final_png, "image/png"),
                    "/final.json": (json.dumps(live.final_meta).encode() if live.final_meta else b"", "application/json"),
                }
            if path not in routes:
                return self._send(404, b"not found", "text/plain")
            body, ctype = routes[path]
            if not body and path in ("/frame.jpg", "/mosaic.png"):
                return self._send(503, b"not ready", "text/plain")
            if not body and path in ("/final.png", "/final.json"):
                return self._send(503, b"not published: press Scan done", "text/plain")
            self._send(200, body, ctype)

        def do_POST(self):
            path = self.path.split("?")[0]
            if path == "/reset":
                live.reset_flag = True
                return self._send(200, b'{"ok":true}', "application/json")
            if path == "/scan_done":
                r = live.scan_done()
                if r["ok"]:
                    print(f"# scan done: TAK map v{r['final_version']}, {r['keyframes']} keyframes, "
                          f"drops {r['drops']}", flush=True)
                return self._send(200 if r["ok"] else 409, json.dumps(r).encode(), "application/json")
            if path in ("/drop", "/undo"):
                q = self.path.split("id=")[1] if "id=" in self.path else ""
                with live.lock:
                    r = live.drop(int(q) if q.isdigit() else None) if path == "/drop" else live.undo()
                if r["ok"]:
                    print(f"# {path[1:]}: {r.get('id', r.get('undone'))} -> nodes {r['nodes']}", flush=True)
                return self._send(200 if r["ok"] else 409, json.dumps(r).encode(), "application/json")
            self._send(404, b"not found", "text/plain")

    return H


def main():
    ap = argparse.ArgumentParser(description="Live downward-camera mosaic, served over HTTP.")
    ap.add_argument("--video", help="read this file instead of the Pi camera")
    ap.add_argument("--realtime", action="store_true", help="with --video: play at the file's frame rate")
    ap.add_argument("--step", type=int, default=2, help="with --video: use every Nth frame")
    ap.add_argument("--record", help="also save every camera frame as DIR/000001.jpg ... (re-stitch: DIR/%%06d.jpg)")
    ap.add_argument("--out", default=None, help="also write <out>.png/.json on every update")
    ap.add_argument("--width", type=int, default=1280, help="camera frame width")
    ap.add_argument("--height-px", type=int, default=720, help="camera frame height")
    ap.add_argument("--fps", type=float, default=10.0, help="camera frame rate (processing max ~14; see drone/fps_ramp.sh)")
    ap.add_argument("--threads", type=int, default=2, help="OpenCV worker threads (fewer = less peak power)")
    ap.add_argument("--gain", type=float, default=16.0, help="analogue gain with --shutter-us (imx708 max 16)")
    ap.add_argument("--shutter-us", type=int, default=None, help="fixed exposure (e.g. 4000) against motion blur")
    ap.add_argument("--focus-m", type=float, default=None, help="focus distance, metres (default: --cam-height)")
    ap.add_argument("--mask-bottom", type=float, default=0.0, help="ignore this bottom fraction (hand-carried: ~0.2)")
    ap.add_argument("--work-width", type=int, default=640)
    ap.add_argument("--hfov", type=float, default=102.0)
    ap.add_argument("--cam-height", type=float, default=2.2, help="camera height above the floor, metres")
    ap.add_argument("--max-side", type=int, default=2000, help="mosaic size limit, px")
    ap.add_argument("--publish-s", type=float, default=3.0, help="re-render the mosaic at most this often")
    ap.add_argument("--drop-order", default="1,2,3,4,5", help="node IDs in the order they are dropped (drone bays)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()

    def stop(*_):
        raise KeyboardInterrupt  # pkill -> the same clean stop as Ctrl+C

    signal.signal(signal.SIGTERM, stop)
    cv2.setNumThreads(a.threads)
    live = Live(a)
    server = ThreadingHTTPServer((a.host, a.port), make_handler(live))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"# mosaic server on http://{a.host}:{a.port}/  source: {a.video or 'Pi camera'}", flush=True)
    try:
        live.run()
        if a.video:  # keep serving the finished mosaic
            print("# video finished; still serving (Ctrl+C to stop)", flush=True)
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
