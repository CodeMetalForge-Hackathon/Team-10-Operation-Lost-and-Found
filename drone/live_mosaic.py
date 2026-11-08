"""live_mosaic.py: run the stitcher live on the Pi camera (or on a video file) and serve the result over HTTP.

  python3 drone/live_mosaic.py                         # Pi: Camera Module 3 Wide, serve on :8080
  python3 drone/live_mosaic.py --record data/walk2 --mask-bottom 0.2   # hand-carried: save frames, hide feet
  python drone/live_mosaic.py --video data/walk2/%06d.jpg              # laptop: same server fed from a recording

HTTP (any browser on the same network, e.g. http://<pi-ip>:8080/):
  GET  /              a page showing the live frame and the growing mosaic
  GET  /mosaic.png    latest mosaic            GET /mosaic.json   its metadata (px_to_m etc., see mosaic.py)
  GET  /frame.jpg     latest camera frame      GET /status        counters
  POST /reset         start a new mosaic
The heatmap page uses /mosaic.png + /mosaic.json as its background.
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mosaic import Mosaicker, default_px_to_m  # noqa: E402

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>T10 camera mosaic</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;background:#111;color:#ddd;font:14px system-ui}header{padding:8px 12px;display:flex;gap:12px;align-items:center}
main{display:flex;flex-wrap:wrap;gap:8px;padding:0 8px}figure{margin:0}img{max-width:100%;background:#000}
#m{max-height:80vh}#f{width:320px}button{background:#333;color:#ddd;border:1px solid #555;padding:4px 10px}</style></head>
<body><header><b>T10 camera mosaic</b><span id="s">...</span><button onclick="fetch('/reset',{method:'POST'})">New mosaic</button></header>
<main><figure><img id="f"><figcaption>live frame</figcaption></figure><figure><img id="m"><figcaption>mosaic</figcaption></figure></main>
<script>
function tick(){const t=Date.now();document.getElementById('f').src='/frame.jpg?'+t;
fetch('/status').then(r=>r.json()).then(s=>{document.getElementById('s').textContent=
`${s.state} | ${s.keyframes} keyframes | ${s.fps} fps | lost ${s.lost}/${s.frames}`;
const m=document.getElementById('m');if(m.dataset.v!=s.version){m.dataset.v=s.version;m.src='/mosaic.png?'+s.version}}).catch(()=>{})}
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
        self.status = {"state": "starting", "frames": 0, "lost": 0, "keyframes": 0, "fps": 0.0, "version": 0}
        self.m = self._new()

    def _new(self):
        return Mosaicker(work_width=self.a.work_width, mask_bottom=self.a.mask_bottom)

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
                    # Cap the sensor frame rate: at walking/drone speed 5 fps is plenty, and full speed on all
                    # cores draws current spikes that brown out a Pi 5 running from a power bank.
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
        img, M = self.m.render(max_side=self.a.max_side)
        h0 = self.m.keyframes[0][0].shape[0]
        px_to_m, m_per_px = default_px_to_m(M, self.a.work_width, h0, self.a.hfov, self.a.cam_height)
        ok, png = cv2.imencode(".png", img)
        meta = {"width": img.shape[1], "height": img.shape[0], "m_per_px": round(float(m_per_px), 5),
                "px_to_m": [[round(float(v), 6) for v in row] for row in px_to_m], "aligned": False,
                "keyframes": len(self.m.keyframes), "hfov_deg": self.a.hfov, "height_m": self.a.cam_height,
                "t": time.time()}
        with self.lock:
            self.version += 1
            self.mosaic_png, self.meta = png.tobytes(), dict(meta, version=self.version)
            self.status["version"] = self.version
        if self.a.out:
            for path, data in ((self.a.out + ".png", png.tobytes()), (self.a.out + ".json", json.dumps(meta).encode())):
                with open(path + ".tmp", "wb") as f:
                    f.write(data)
                os.replace(path + ".tmp", path)

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
                self.m, self.reset_flag, dirty = self._new(), False, False
            if self.a.record:
                # One JPEG per frame + a disk sync every 2 s: a power cut loses at most ~2 s of the walk.
                # (An .mp4 written by VideoWriter is unreadable unless it is closed cleanly.)
                n_rec += 1
                cv2.imwrite(os.path.join(self.a.record, f"{n_rec:06d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                if time.time() - t_sync >= 2 and hasattr(os, "sync"):  # os.sync is Linux/Pi only
                    os.sync()
                    t_sync = time.time()
            result = self.m.add(frame)
            dirty |= result == "keyframe"
            n_fps += 1
            now = time.time()
            small = cv2.resize(frame, (480, round(frame.shape[0] * 480 / frame.shape[1])))
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
                }
            if path not in routes:
                return self._send(404, b"not found", "text/plain")
            body, ctype = routes[path]
            if not body and path in ("/frame.jpg", "/mosaic.png"):
                return self._send(503, b"not ready", "text/plain")
            self._send(200, body, ctype)

        def do_POST(self):
            if self.path.split("?")[0] == "/reset":
                live.reset_flag = True
                return self._send(200, b'{"ok":true}', "application/json")
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
    ap.add_argument("--fps", type=float, default=5.0, help="camera frame rate (low = less power; Pi max ~14)")
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
