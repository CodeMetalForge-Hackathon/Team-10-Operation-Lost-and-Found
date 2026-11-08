"""Scan done -> TAK: the camera freezes a published floor map, and the TAK overlay serves only that map."""

import argparse
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

try:
    import cv2  # noqa: F401  (opencv is apt-installed on the Pi, not in requirements.txt)
    import numpy as np
except ImportError:  # pragma: no cover
    cv2 = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "drone"))
sys.path.insert(0, os.path.join(ROOT, "fusion"))


def live_args(out):
    return argparse.Namespace(work_width=640, mask_bottom=0.0, drop_order="1,2,3", cam_height=2.2, hfov=102.0,
                              width=1280, height_px=720, out=out, max_side=800, video=None, publish_s=3.0)


def serve(handler):
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


@unittest.skipUnless(cv2, "opencv not installed")
class ScanDoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_mosaic_synth import make_floor, walk
        rng = np.random.default_rng(3)
        floor = make_floor(3000, 1500, 8.0, rng)
        cls.frames = [f for f, _ in walk(floor, 56, 20.0, rng)]

    def setUp(self):
        from live_mosaic import Live, make_handler
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "m")
        self.live = Live(live_args(self.out))
        self.cam, self.cam_url = serve(make_handler(self.live))

    def tearDown(self):
        self.cam.shutdown()
        self.cam.server_close()
        self.tmp.cleanup()

    def feed(self, frames):
        """What Live._loop does per frame, then one periodic publish."""
        for f in frames:
            with self.live.lock:
                self.live.m.add(f)
        self.live.publish()

    def overlay(self, source):
        import tak_overlay
        from tak import Frame
        a = argparse.Namespace(mosaic=self.cam_url, source=source, bind="127.0.0.1", serve=0, refresh=5,
                               max_side=2048, opacity=1.0)
        srv = tak_overlay.make_server(a, Frame(42.3594, -71.0566, 0.0))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def test_nothing_published_until_scan_done(self):
        self.assertEqual(get(self.cam_url + "/final.png")[0], 503)
        self.assertEqual(get(self.cam_url + "/final.json")[0], 503)
        code, body = post(self.cam_url + "/scan_done")  # no frames yet
        self.assertEqual(code, 409)
        self.assertFalse(body["ok"])

    def test_scan_done_freezes_the_map_and_republishes_on_demand(self):
        self.feed(self.frames[:24])
        code, body = post(self.cam_url + "/scan_done")
        self.assertEqual(code, 200)
        self.assertEqual(body["final_version"], 1)
        final1 = json.loads(get(self.cam_url + "/final.json")[1])
        png1 = get(self.cam_url + "/final.png")[1]
        self.assertEqual(final1["final_version"], 1)
        self.assertIn("published_at", final1)
        self.assertEqual(json.loads(get(self.cam_url + "/status")[1])["final_version"], 1)

        # the drone keeps flying: the live mosaic grows, the published map does not move
        live_v = json.loads(get(self.cam_url + "/mosaic.json")[1])["version"]
        self.feed(self.frames[24:])
        self.assertGreater(json.loads(get(self.cam_url + "/mosaic.json")[1])["version"], live_v)
        self.assertEqual(json.loads(get(self.cam_url + "/final.json")[1]), final1)
        self.assertEqual(get(self.cam_url + "/final.png")[1], png1)

        # second press: republish with everything flown so far
        code, body = post(self.cam_url + "/scan_done")
        self.assertEqual(body["final_version"], 2)
        final2 = json.loads(get(self.cam_url + "/final.json")[1])
        self.assertGreaterEqual(final2["keyframes"], final1["keyframes"])

        # saved next to --out, and restored by a restarted camera
        self.assertTrue(os.path.exists(self.out + "_final.png"))
        from live_mosaic import Live
        again = Live(live_args(self.out))
        self.assertEqual(again.final_meta["final_version"], 2)
        self.assertEqual(again.status["final_version"], 2)

    def test_reset_keeps_the_published_map(self):
        self.feed(self.frames[:16])
        post(self.cam_url + "/scan_done")
        self.assertEqual(post(self.cam_url + "/reset")[0], 200)
        self.assertEqual(get(self.cam_url + "/final.json")[0], 200)

    def test_overlay_serves_only_the_published_map(self):
        url = self.overlay("final")
        link = get(url + "/link.kml")[1].decode()
        self.assertIn("<refreshInterval>5</refreshInterval>", link)
        self.assertIn("/t10_mosaic.kmz", link)

        self.feed(self.frames[:24])  # a growing mosaic exists, but nothing is published yet
        self.assertEqual(get(url + "/t10_mosaic.kmz")[0], 503)

        post(self.cam_url + "/scan_done")
        code, kmz1 = get(url + "/t10_mosaic.kmz")
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(kmz1)) as z:
            kml = z.read("doc.kml").decode()
            self.assertIn("files/mosaic.png", z.namelist())
        self.assertIn("T10 floor map (final ", kml)
        self.assertIn("published by Scan done (v1)", kml)
        self.assertIn("<LatLonBox>", kml)

        self.feed(self.frames[24:])  # more flying: TAK's overlay is unchanged until the next press
        self.assertEqual(get(url + "/t10_mosaic.kmz")[1], kmz1)
        post(self.cam_url + "/scan_done")
        kmz2 = get(url + "/t10_mosaic.kmz")[1]
        self.assertNotEqual(kmz2, kmz1)
        with zipfile.ZipFile(io.BytesIO(kmz2)) as z:
            self.assertIn("(v2)", z.read("doc.kml").decode())

    def test_live_source_still_follows_the_growing_mosaic(self):
        url = self.overlay("live")
        self.feed(self.frames[:16])
        code, kmz = get(url + "/t10_mosaic.kmz")
        self.assertEqual(code, 200)
        with zipfile.ZipFile(io.BytesIO(kmz)) as z:
            self.assertIn("live, still growing", z.read("doc.kml").decode())

    def test_file_prefix_final(self):
        import tak_overlay
        with self.assertRaises(ValueError):
            tak_overlay.load_mosaic(self.out, final=True)
        self.feed(self.frames[:16])
        self.live.scan_done()
        png, meta = tak_overlay.load_mosaic(self.out, final=True)
        self.assertEqual(meta["final_version"], 1)
        self.assertTrue(png.startswith(b"\x89PNG"))


class OpsButtonTest(unittest.TestCase):
    def test_ops_page_has_the_scan_done_button(self):
        with open(os.path.join(ROOT, "ui", "ops.html"), encoding="utf-8") as f:
            html = f.read()
        with open(os.path.join(ROOT, "ui", "ops.js"), encoding="utf-8") as f:
            js = f.read()
        self.assertIn('id="scan-done"', html)
        self.assertIn('"/scan_done"', js)


if __name__ == "__main__":
    unittest.main()
