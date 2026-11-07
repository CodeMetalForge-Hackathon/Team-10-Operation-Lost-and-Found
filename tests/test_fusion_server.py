import json
import unittest
import warnings

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
)

from fastapi.testclient import TestClient

from fusion.serial_ingest import accept_line
from fusion.server import create_app
from fusion.state import FusionState


BEACON = (
    '{"type":"beacon","src":3,"seq":120,"hops":1,"rssi_last":-58,'
    '"batt_mv":3950,"floor_db":-62,"nbrs":[[1,-55],[2,-71]]}'
)
EVENT = (
    '{"type":"event","src":3,"seq":122,"hops":2,"rssi_last":-70,"t_ms":51800,'
    '"kind":"TAP_PATTERN","peak_db":-20,"voice_db":-35,"count":3,"conf":80}'
)


class DashboardSocketTest(unittest.TestCase):
    def test_ws_pushes_the_same_snapshot_the_page_will_render(self):
        state = FusionState()
        state.simulated = True
        accept_line(BEACON, state, lambda _error: None, now_ms=5_000)
        accept_line(EVENT, state, lambda _error: None, now_ms=5_100)
        app = create_app(state, now_ms=lambda: 5_100)

        with TestClient(app) as client:
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Operations overview", page.text)
            self.assertNotIn("Where to dig", page.text)
            self.assertIn("/ws", page.text)
            self.assertIn("msg.v !== 1", page.text)
            self.assertIn(
                "Acoustic cues require verification. Positions are not available.",
                page.text,
            )
            self.assertNotIn("display mapping not agreed", page.text)
            with client.websocket_connect("/ws") as socket:
                payload = socket.receive_json()

        self.assertEqual(payload["v"], 1)
        self.assertTrue(payload["simulated"])
        self.assertEqual(payload["nodes"][0]["id"], 3)
        self.assertEqual(payload["nodes"][0]["status"], "active")
        self.assertEqual(payload["nodes"][0]["search_priority"], "elevated")
        self.assertIsNone(payload["nodes"][0]["position"])
        self.assertIn("not a confirmed location", payload["banner"]["text"])
        self.assertNotIn("confirmed survivor", json.dumps(payload).lower())

        with TestClient(app) as client:
            self.assertEqual(client.post("/cmd").status_code, 404)


class CliGuardTest(unittest.TestCase):
    def test_missing_source_exits_without_guessing_a_port(self):
        import os
        import sys
        from io import StringIO
        from fusion.server import main

        env = os.environ.pop("GATEWAY_PORT", None)
        stderr = StringIO()
        old = sys.stderr
        sys.stderr = stderr
        try:
            code = main([])
        finally:
            sys.stderr = old
            if env is not None:
                os.environ["GATEWAY_PORT"] = env

        self.assertEqual(code, 2)
        self.assertNotIn("/dev/", stderr.getvalue())


class ModuleServeTest(unittest.TestCase):
    def test_module_serves_the_fixture_without_inventing_a_position(self):
        import json
        import subprocess
        import sys
        import time
        import urllib.request

        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "fusion.server",
                "--simulate",
                "tests/fixtures/sample_gateway.txt",
                "--listen",
                "8766",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        snap = None
        try:
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8766/state", timeout=1) as resp:
                        snap = json.load(resp)
                        break
                except Exception:
                    time.sleep(0.1)
            self.assertIsNotNone(snap)
            self.assertTrue(snap["simulated"])
            self.assertEqual(snap["devices"][0]["kind"], "BLE_APPLE")
            self.assertTrue(all(node["position"] is None for node in snap["nodes"]))
            self.assertNotIn("lat", snap)
        finally:
            proc.terminate()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
