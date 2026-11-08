"""One fusion host: heatmap page, gateway commands, and the TAK picture come from server.py."""

import os
import queue
import sys
import unittest

from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "fusion"))  # so tak.py imports as a module

from fusion.serial_ingest import accept_line, run_port  # noqa: E402
from fusion.server import create_app, heatmap_page, parse_positions  # noqa: E402
from fusion.state import FusionState  # noqa: E402

NOW = 1_700_000_000_000
POS = {1: (0.0, 0.0), 2: (3.0, 0.0), 5: (0.0, 3.0)}


def beacon(src):
    return ('{"type":"beacon","src":%d,"seq":1,"hops":0,"rssi_last":-40,"batt_mv":0,'
            '"uptime_s":5,"floor_db":-22,"nbrs":[]}' % src)


def tap(src, seq=2):
    return ('{"type":"event","src":%d,"seq":%d,"hops":0,"rssi_last":-40,"t_ms":1000,'
            '"kind":"TAP_PATTERN","peak_db":-10,"voice_db":-30,"count":3,"conf":80}' % (src, seq))


def loud(src, seq=3):
    return ('{"type":"event","src":%d,"seq":%d,"hops":0,"rssi_last":-40,"t_ms":1000,'
            '"kind":"LOUD","peak_db":-10,"voice_db":-30,"count":1,"conf":50}' % (src, seq))


def feed(state, *lines, at=NOW):
    for line in lines:
        accept_line(line, state, lambda _m: None, at)


class TakPictureTest(unittest.TestCase):
    def picture(self, state, now=NOW):
        client = TestClient(create_app(state, now_ms=lambda: now, positions=POS))
        return client.get("/tak").json()

    def test_without_heatmap_nodes_only(self):
        state = FusionState()
        feed(state, beacon(1), beacon(2))
        pic = self.picture(state)
        self.assertEqual(pic["sources"], [])
        by_id = {n["id"]: n for n in pic["nodes"]}
        self.assertEqual(sorted(by_id), [1, 2, 5])
        self.assertEqual(by_id[1]["callsign"], "T10 N1")
        self.assertEqual((by_id[2]["x"], by_id[2]["y"]), (3.0, 0.0))
        self.assertFalse(by_id[5]["alive"])  # never heard
        self.assertEqual(by_id[5]["callsign"], "T10 N5 LOST")

    def test_fresh_tap_shows_in_remarks_callsign_stays_fixed(self):
        # a callsign change re-sends the marker, which crashes WinTAK with a details pane open
        state = FusionState()
        feed(state, beacon(2), tap(2))
        node = {n["id"]: n for n in self.picture(state)["nodes"]}[2]
        self.assertEqual(node["callsign"], "T10 N2")
        self.assertIn("TAP x3", node["remarks"])
        self.assertIn("not a survivor location", node["remarks"])
        # 31 s later the node is stale, and the cue is no longer fresh
        feed(state, beacon(2), at=NOW + 31_000)
        node = {n["id"]: n for n in self.picture(state, NOW + 31_000)["nodes"]}[2]
        self.assertEqual(node["callsign"], "T10 N2")
        self.assertNotIn("TAP", node["remarks"])

    def test_heatmap_peak_is_sent_as_the_look_here_source(self):
        class Heat:
            def snapshot(self, _now_s):
                return {"nodes": [], "peak": {"x": 1.5, "y": 0.5, "radius": 0.8, "strength": 12}}

        client = TestClient(create_app(FusionState(), now_ms=lambda: NOW, positions=POS, heatmap=Heat()))
        self.assertEqual(client.get("/tak").json()["sources"], [{"x": 1.5, "y": 0.5, "radius": 0.8, "strength": 12}])

    def test_drops_replace_the_positions_tak_uses(self):
        state = FusionState()
        feed(state, beacon(4))
        app = create_app(state, now_ms=lambda: NOW, positions={})
        client = TestClient(app)
        self.assertEqual(client.get("/tak").json()["unplaced"], [4])
        app.state.positions["now"] = {4: (1.0, 2.0)}  # what the drops poller does
        node = client.get("/tak").json()["nodes"][0]
        self.assertEqual((node["id"], node["x"], node["y"], node["alive"]), (4, 1.0, 2.0, True))

    def test_loud_is_not_in_the_callsign(self):
        state = FusionState()
        feed(state, beacon(1), loud(1))
        node = {n["id"]: n for n in self.picture(state)["nodes"]}[1]
        self.assertEqual(node["callsign"], "T10 N1")
        self.assertIn("LOUD", node["remarks"])

    def test_node_without_position_is_reported_not_sent(self):
        state = FusionState()
        feed(state, beacon(7))
        pic = self.picture(state)
        self.assertEqual(pic["unplaced"], [7])
        self.assertNotIn(7, [n["id"] for n in pic["nodes"]])

    def test_tak_poll_lights_the_dashboard_badge(self):
        state = FusionState()
        client = TestClient(create_app(state, now_ms=lambda: NOW, positions=POS))
        self.assertFalse(client.get("/state").json()["tak_bridge"]["polling"])
        client.get("/tak")
        self.assertTrue(client.get("/state").json()["tak_bridge"]["polling"])


class TakBridgeTest(unittest.TestCase):
    def test_bridge_accepts_server_picture_and_rejects_dashboard_state(self):
        import tak

        state = FusionState()
        feed(state, beacon(2), tap(2))
        client = TestClient(create_app(state, now_ms=lambda: NOW, positions=POS))
        pic = tak.picture_from_json(client.get("/tak").json())
        self.assertEqual(pic["sources"], [])
        with self.assertRaises(ValueError):
            tak.picture_from_json(client.get("/state").json())

    def test_publisher_sends_callsign_and_resends_only_on_change(self):
        import tak

        sent = []

        class Capture:
            def send(self, payload):
                sent.append(payload.decode())

        pub = tak.Publisher(Capture(), tak.Frame(42.0, -71.0))
        node = {"id": 2, "x": 3.0, "y": 0.0, "alive": True, "callsign": "T10 N2 TAP", "remarks": "r1"}
        self.assertEqual(pub.update({"nodes": [node], "sources": []}, now=0.0), 1)
        self.assertIn('callsign="T10 N2 TAP"', sent[-1])
        # remarks-only change: no resend until the refresh interval
        self.assertEqual(pub.update({"nodes": [dict(node, remarks="r2")], "sources": []}, now=1.0), 0)
        # callsign change: resend now
        self.assertEqual(pub.update({"nodes": [dict(node, callsign="T10 N2")], "sources": []}, now=2.0), 1)


class CommandTest(unittest.TestCase):
    def test_cmd_queues_hail_for_the_gateway(self):
        commands = queue.Queue()
        state = FusionState()
        state.note_link(transport="serial", connected=True)
        client = TestClient(create_app(state, now_ms=lambda: NOW, commands=commands))
        response = client.post("/cmd?name=hail")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(commands.get_nowait(), "CMD HAIL 0 255")

    def test_cmd_refused_while_gateway_unplugged(self):
        # queued, it would beep minutes later when the cable is back and spoil the heatmap's reply window
        commands = queue.Queue()
        state = FusionState()
        state.note_link(transport="serial", connected=False, last_error="unplugged")
        client = TestClient(create_app(state, now_ms=lambda: NOW, commands=commands))
        self.assertEqual(client.post("/cmd?name=HAIL").status_code, 409)
        self.assertTrue(commands.empty())

    def test_cmd_refuses_without_serial_and_unknown_names(self):
        client = TestClient(create_app(FusionState(), now_ms=lambda: NOW))
        self.assertEqual(client.post("/cmd?name=HAIL").status_code, 409)
        commands = queue.Queue()
        client = TestClient(create_app(FusionState(), now_ms=lambda: NOW, commands=commands))
        self.assertEqual(client.post("/cmd?name=REBOOT").status_code, 400)
        self.assertTrue(commands.empty())

    def test_run_port_writes_queued_command_and_records_host_cmd(self):
        commands = queue.Queue()
        commands.put("CMD HAIL 0 255")
        state = FusionState()
        written = []
        reads = iter([b""])
        stopped = {"n": 0}

        class Port:
            def write(self, data):
                written.append(data)

            def readline(self):
                return next(reads, b"")

            def close(self):
                pass

        def stop():
            stopped["n"] += 1
            return stopped["n"] > 2

        run_port(lambda: Port(), state, lambda _m: None, lambda: NOW, lambda _s: None, stop, commands=commands)
        self.assertEqual(written, [b"CMD HAIL 0 255\n"])
        cmds = state.snapshot(NOW)["diagnostics"]["host_cmds"]
        self.assertEqual([c["text"] for c in cmds], ["CMD HAIL 0 255"])


class HeatmapInProcessTest(unittest.TestCase):
    def test_lines_reach_the_heatmap_and_the_page_uses_server_routes(self):
        from fusion.heatmap import Fusion

        state = FusionState()
        heat = Fusion(POS)
        state.observers.append(heat.ingest)
        state.reset_hooks.append(heat.reset)
        client = TestClient(create_app(state, now_ms=lambda: NOW, heatmap=heat, positions=POS))
        feed(state, beacon(1), beacon(2))
        snap = client.get("/heatmap/state").json()
        alive = {n["id"]: n["alive"] for n in snap["nodes"]}
        self.assertTrue(alive[1] and alive[2])
        self.assertFalse(alive[5])
        page = client.get("/heatmap").text
        self.assertIn("fetch('/heatmap/state')", page)
        self.assertNotIn("Dig here", page)
        self.assertEqual(client.post("/heatmap/reset").json(), {"ok": True})

    def test_heatmap_off_is_a_clear_404(self):
        client = TestClient(create_app(FusionState(), now_ms=lambda: NOW))
        self.assertEqual(client.get("/heatmap").status_code, 404)
        self.assertEqual(client.get("/heatmap/state").status_code, 404)

    def test_heatmap_page_rewrites_are_all_applied(self):
        # If heatmap.py's PAGE changes, a silent no-op replace would point the page at the wrong routes.
        page = heatmap_page(":8080")
        for needle in ("fetch('/heatmap/state')", "fetch('/heatmap/reset'", "r.json()",
                       "where to look", "Look here:", 'href="/"', "let CLI_MOSAIC=':8080'"):
            self.assertIn(needle, page)

    def test_live_recording_is_replayable_by_both_tools(self):
        import json
        from pathlib import Path

        from fusion.server import start_recording

        state = FusionState()
        path = start_recording(state, "test_recording_tmp", {"positions_m": {}})
        try:
            feed(state, beacon(2), tap(2))
            lines = [json.loads(x) for x in Path(path).read_text().splitlines()]
            self.assertEqual([m["type"] for m in lines], ["beacon", "event"])
            self.assertEqual(lines[0]["t_host"], NOW / 1000.0)  # Unix seconds, like heatmap.py recordings
            self.assertNotIn("t_ingest_ms", lines[1])
            self.assertTrue(Path(str(path).replace(".jsonl", ".meta.json")).is_file())
        finally:
            for f in (Path(path), Path(str(path).replace(".jsonl", ".meta.json"))):
                f.unlink(missing_ok=True)

    def test_parse_positions(self):
        self.assertEqual(parse_positions([]), POS)
        self.assertEqual(parse_positions(["1=0,0", "4=2.5,1"]), {1: (0.0, 0.0), 4: (2.5, 1.0)})
        with self.assertRaises(ValueError):
            parse_positions(["1:0,0"])


if __name__ == "__main__":
    unittest.main()
