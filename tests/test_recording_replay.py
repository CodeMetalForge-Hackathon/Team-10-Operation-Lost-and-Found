"""Playback of committed gateway recordings through the real ingest path."""

import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from fusion.recording import RecordingPlayer
from fusion.server import create_app
from fusion.state import FusionState


ROOT = Path(__file__).resolve().parents[1]
RECORDING = ROOT / "data" / "beacons_line_2nodes.jsonl"


def _clock(values):
    seq = iter(values)

    def clock():
        return next(seq)

    return clock


class IntervalTest(unittest.TestCase):
    def test_playback_keeps_recorded_intervals_and_can_run_faster(self):
        lines = RECORDING.read_text(encoding="utf-8").splitlines()[:3]
        sleeps = []
        state = FusionState()
        player = RecordingPlayer(
            state,
            lambda _error: None,
            _clock([1_000, 1_201, 2_218]),
            lines,
            speed=1,
            sleep=sleeps.append,
            path=str(RECORDING),
        )

        accepted = player.play()

        self.assertEqual(accepted, 3)
        self.assertEqual(len(sleeps), 2)
        self.assertAlmostEqual(sleeps[0], 0.201, places=3)
        self.assertAlmostEqual(sleeps[1], 1.017, places=3)

        faster = []
        RecordingPlayer(
            FusionState(),
            lambda _error: None,
            _clock([1, 2, 3]),
            lines,
            speed=4,
            sleep=faster.append,
        ).play()
        self.assertAlmostEqual(faster[0], 0.201 / 4, places=3)
        self.assertAlmostEqual(faster[1], 1.017 / 4, places=3)

    def test_recording_is_not_labeled_live_or_simulation(self):
        lines = RECORDING.read_text(encoding="utf-8").splitlines()[:3]
        state = FusionState()
        player = RecordingPlayer(
            state,
            lambda _error: None,
            _clock([1_000_000, 1_000_201, 1_001_218]),
            lines,
            speed=8,
            sleep=lambda _delay: None,
            path=RECORDING.name,
        )
        player.play()

        snap = state.snapshot(now_ms=1_001_218)
        self.assertEqual(snap["source"], "recording")
        self.assertFalse(snap["simulated"])
        self.assertEqual(snap["playback"]["status"], "ended")
        self.assertEqual(snap["playback"]["lines"], 3)
        self.assertEqual(snap["gateway"]["rx_dropped"], 0)
        node = next(item for item in snap["nodes"] if item["id"] == 2)
        self.assertEqual(node["status"], "active")
        self.assertEqual(node["uptime_s"], 186)
        self.assertEqual(node["batt_mv_status"], "unimplemented")
        self.assertEqual(node["last_t_host"], 1_000_201)
        self.assertEqual(state.snapshot(now_ms=1_001_218 + 6001)["nodes"][0]["status"], "inactive")

    def test_a_bad_line_does_not_abort_playback(self):
        lines = [
            '{"type":"beacon","src":1,"seq":1,"hops":0,"rssi_last":-40,"batt_mv":0,"uptime_s":3,"floor_db":0,"nbrs":[],"t_host":100.0}',
            "not-json",
            '{"type":"beacon","src":1,"seq":2,"hops":0,"rssi_last":-41,"batt_mv":0,"uptime_s":5,"floor_db":0,"nbrs":[],"t_host":102.0}',
        ]
        errors = []
        state = FusionState()
        accepted = RecordingPlayer(
            state,
            errors.append,
            _clock([10, 20]),
            lines,
            sleep=lambda _delay: None,
        ).play()

        self.assertEqual(accepted, 2)
        self.assertEqual(len(errors), 1)
        self.assertEqual(state.snapshot(now_ms=20)["playback"]["status"], "ended")
        self.assertEqual(state.snapshot(now_ms=20)["nodes"][0]["seq"], 2)

    def test_state_and_websocket_show_the_recording(self):
        state = FusionState()
        RecordingPlayer(
            state,
            lambda _error: None,
            _clock([5_000]),
            [RECORDING.read_text(encoding="utf-8").splitlines()[1]],
            sleep=lambda _delay: None,
        ).play()
        app = create_app(state, now_ms=lambda: 5_000)

        with TestClient(app) as client:
            body = client.get("/state").json()
            with client.websocket_connect("/ws") as socket:
                pushed = socket.receive_json()

        self.assertEqual(body["source"], "recording")
        self.assertEqual(pushed["source"], "recording")
        self.assertEqual(body["nodes"][0]["id"], pushed["nodes"][0]["id"])
        self.assertFalse(body["simulated"])
        self.assertIsNone(body["nodes"][0]["position"])
