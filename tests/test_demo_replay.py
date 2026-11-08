import unittest
import warnings

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
)

from fastapi.testclient import TestClient

from fusion.demo_player import DemoPlayer
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


class ReplayRefusesLiveSession(unittest.TestCase):
    def test_replay_does_not_clear_a_live_gateway_session(self):
        state = FusionState()
        accept_line(BEACON, state, lambda _message: None, now_ms=1_000)
        app = create_app(state, now_ms=lambda: 1_000, demo=object())

        with TestClient(app) as client:
            response = client.post("/demo/replay")

        self.assertEqual(response.status_code, 409)
        snap = state.snapshot(1_000)
        self.assertFalse(snap["simulated"])
        self.assertEqual(snap["counts"]["packets"], 1)
        self.assertEqual(snap["nodes"][0]["id"], 3)
        self.assertIsNone(snap["nodes"][0]["position"])
        self.assertIn("simulation", response.json()["error"].lower())


class ReplayResetsSimulation(unittest.TestCase):
    def test_replay_clears_prior_counts_and_ingests_the_script_again(self):
        state = FusionState()
        state.simulated = True
        accept_line(BEACON, state, lambda _message: None, now_ms=1_000)
        accept_line(EVENT, state, lambda _message: None, now_ms=1_100)
        player = DemoPlayer(
            state,
            log=lambda _message: None,
            clock=lambda: 5_000,
            script=[(0.0, EVENT)],
            keepalive=None,
        )
        app = create_app(state, now_ms=lambda: 5_000, demo=player)

        with TestClient(app) as client:
            first = client.post("/demo/replay")
            player.join(timeout=2)
            second = client.post("/demo/replay")
            player.join(timeout=2)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.json()["ok"])
        self.assertEqual(first.json()["mode"], "simulation")
        self.assertFalse(first.json()["sends_hardware_commands"])
        snap = state.snapshot(5_000)
        self.assertTrue(snap["simulated"])
        self.assertEqual(snap["counts"]["packets"], 1)
        self.assertEqual(snap["banner"]["possible_acoustic"], 1)
        self.assertEqual(snap["nodes"][0]["evidence"][0]["kind"], "TAP_PATTERN")
        self.assertIsNone(snap["nodes"][0]["position"])
        self.assertNotIn("confirmed survivor", str(snap).lower())


class DemoStatusTest(unittest.TestCase):
    def test_status_is_unavailable_without_a_simulation_player(self):
        state = FusionState()
        state.simulated = True
        app = create_app(state, now_ms=lambda: 1_000)

        with TestClient(app) as client:
            response = client.get("/demo")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])
        self.assertFalse(response.json()["sends_hardware_commands"])

    def test_status_is_available_only_for_a_simulated_player(self):
        state = FusionState()
        state.simulated = True
        player = DemoPlayer(
            state,
            log=lambda _message: None,
            clock=lambda: 0,
            script=[],
            keepalive=None,
        )
        app = create_app(state, now_ms=lambda: 0, demo=player)

        with TestClient(app) as client:
            response = client.get("/demo")

        self.assertTrue(response.json()["available"])
        self.assertEqual(response.json()["mode"], "simulation")
        self.assertFalse(response.json()["sends_hardware_commands"])
