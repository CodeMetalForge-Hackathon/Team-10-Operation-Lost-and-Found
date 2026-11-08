"""Append-only history is not the live node table."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from fusion.serial_ingest import accept_line
from fusion.server import create_app
from fusion.state import FusionState
from fusion.store import ObservationStore


BEACON = (
    '{"type":"beacon","src":2,"seq":91,"hops":0,"rssi_last":-36,'
    '"batt_mv":0,"uptime_s":186,"floor_db":0,"nbrs":[[1,-43]],'
    '"t_host":1794088158.947}'
)
VIBRATION = (
    '{"type":"event","src":2,"seq":92,"hops":0,"rssi_last":-36,"t_ms":4000,'
    '"kind":"VIBRATION","peak_db":-11,"voice_db":-128,"count":4,"conf":60}'
)


class StoreRoundTripTest(unittest.TestCase):
    def test_restart_keeps_history_and_does_not_revive_a_live_node(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "host.sqlite"
            first = FusionState(store=ObservationStore(path))
            first.source = "live"
            accept_line(BEACON, first, lambda _error: None, now_ms=1_700_000_000_000)
            accept_line(VIBRATION, first, lambda _error: None, now_ms=1_700_000_000_500)
            first.store.close()

            restarted = FusionState(store=ObservationStore(path))
            snap = restarted.snapshot(now_ms=1_700_000_006_000)
            rows = restarted.store.recent(limit=10)
            restarted.store.close()  # Windows cannot delete an open SQLite file

        self.assertEqual(snap["nodes"], [])
        self.assertEqual(snap["source"], "live")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["historical"] for row in rows))
        self.assertEqual(rows[0]["msg_type"], "event")
        self.assertEqual(rows[0]["source"], "live")
        self.assertEqual(rows[0]["src"], 2)
        self.assertEqual(rows[0]["hops"], 0)
        self.assertEqual(rows[1]["t_recorded_s"], 1794088158.947)
        self.assertEqual(rows[1]["t_host"], 1_700_000_000_000)
        self.assertEqual(rows[1]["raw"]["uptime_s"], 186)
        self.assertNotEqual(rows[1]["t_host"], rows[1]["t_recorded_s"])

    def test_repeated_events_are_not_collapsed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "host.sqlite"
            state = FusionState(store=ObservationStore(path))
            state.source = "recording"
            accept_line(VIBRATION, state, lambda _error: None, now_ms=10)
            accept_line(VIBRATION, state, lambda _error: None, now_ms=20)
            rows = state.store.recent(limit=10)
            state.store.close()

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["t_host"], 20)
        self.assertEqual(rows[1]["t_host"], 10)
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])

    def test_history_route_does_not_change_the_live_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "host.sqlite"
            store = ObservationStore(path)
            state = FusionState(store=store)
            state.source = "live"
            accept_line(BEACON, state, lambda _error: None, now_ms=4_000)
            app = create_app(state, now_ms=lambda: 4_000)
            with TestClient(app) as client:
                live = client.get("/state").json()
                history = client.get("/history?limit=5").json()
            store.close()

        self.assertEqual(live["nodes"][0]["id"], 2)
        self.assertEqual(history["persistent"], True)
        self.assertEqual(history["observations"][0]["historical"], True)
        self.assertEqual(history["observations"][0]["source"], "live")
        self.assertNotIn("nodes", history)
