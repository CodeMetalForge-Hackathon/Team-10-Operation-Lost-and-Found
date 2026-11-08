"""Contract tests against William's committed gateway recordings.

These lines are the physical evidence. The host must accept them without
requiring a firmware schema change.
"""

import json
import unittest
from pathlib import Path

from fusion.serial_ingest import accept_line, read_lines
from fusion.state import FusionState


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RECORDING = DATA / "beacons_line_2nodes.jsonl"


def _line(path, index):
    return path.read_text(encoding="utf-8").splitlines()[index]


class RecordingNormalizationTest(unittest.TestCase):
    def test_a_recorded_beacon_keeps_raw_fields_and_uses_the_ingestion_clock(self):
        line = _line(RECORDING, 1)
        sink_items = []

        class Sink:
            def accept(self, observation):
                sink_items.append(observation)

        accepted = accept_line(line, Sink(), lambda _error: None, now_ms=1_700_000_000_000)

        self.assertEqual(accepted, 1)
        obs = sink_items[0]
        self.assertEqual(obs["type"], "beacon")
        self.assertEqual(obs["src"], 2)
        self.assertEqual(obs["uptime_s"], 186)
        self.assertEqual(obs["hops"], 0)
        self.assertEqual(obs["batt_mv"], 0)
        self.assertEqual(obs["floor_db"], 0)
        self.assertEqual(obs["t_recorded_s"], 1794088158.947)
        self.assertEqual(obs["t_host"], 1_700_000_000_000)
        self.assertNotEqual(obs["t_host"], obs["t_recorded_s"])

    def test_unimplemented_zeros_stay_raw_and_are_labeled_in_state(self):
        state = FusionState()
        accept_line(_line(RECORDING, 1), state, lambda _error: None, now_ms=5_000)

        node = state.snapshot(now_ms=5_000)["nodes"][0]
        self.assertEqual(node["status"], "active")
        self.assertEqual(node["batt_mv"], 0)
        self.assertEqual(node["floor_db"], 0)
        self.assertEqual(node["batt_mv_status"], "unimplemented")
        self.assertEqual(node["floor_db_status"], "unimplemented")
        self.assertEqual(node["uptime_s"], 186)
        self.assertEqual(node["last_t_host"], 5_000)

    def test_a_nonzero_battery_reading_is_not_called_unimplemented(self):
        state = FusionState()
        line = (
            '{"type":"beacon","src":3,"seq":120,"hops":1,"rssi_last":-58,'
            '"batt_mv":3950,"floor_db":-62,"nbrs":[[1,-55]]}'
        )
        accept_line(line, state, lambda _error: None, now_ms=5_000)

        node = state.snapshot(now_ms=5_000)["nodes"][0]
        self.assertEqual(node["batt_mv"], 3950)
        self.assertEqual(node["batt_mv_status"], "reported")
        self.assertEqual(node["floor_db"], -62)
        self.assertEqual(node["floor_db_status"], "reported")

    def test_gateway_diagnostics_do_not_become_a_sensor_node(self):
        state = FusionState()
        errors = []
        accepted = read_lines(
            [_line(RECORDING, 0), _line(RECORDING, 1)],
            state,
            errors.append,
            now_ms=8_000,
        )

        snap = state.snapshot(now_ms=8_000)
        self.assertEqual(errors, [])
        self.assertEqual(accepted, 2)
        self.assertEqual([node["id"] for node in snap["nodes"]], [2])
        self.assertEqual(snap["gateway"]["id"], 0)
        self.assertEqual(snap["gateway"]["t_ms"], 306574)
        self.assertEqual(snap["gateway"]["rx_dropped"], 0)
        self.assertEqual(snap["gateway"]["t_recorded_s"], 1794088158.746)
        self.assertEqual(snap["gateway"]["t_host"], 8_000)

    def test_log_and_host_cmd_do_not_stop_the_next_beacon(self):
        state = FusionState()
        errors = []
        lines = [
            '{"type":"host_cmd","text":"CMD BLINK 0 255","t_host":1794088218.083}',
            '{"type":"log","text":"# sent CMD BLINK arg=0 target=255","t_host":1794088218.287}',
            "{not json",
            _line(RECORDING, 1),
        ]
        accepted = read_lines(lines, state, errors.append, now_ms=9_000)

        snap = state.snapshot(now_ms=9_000)
        self.assertEqual(accepted, 3)
        self.assertEqual(len(errors), 1)
        self.assertEqual(snap["diagnostics"]["host_cmds"][0]["text"], "CMD BLINK 0 255")
        self.assertEqual(snap["diagnostics"]["logs"][0]["text"], "# sent CMD BLINK arg=0 target=255")
        self.assertEqual(snap["nodes"][0]["id"], 2)
        self.assertNotIn(0, [node["id"] for node in snap["nodes"]])

    def test_an_observed_relay_copy_keeps_hops(self):
        relay = _line(RECORDING, 112)
        parsed = json.loads(relay)
        self.assertEqual(parsed["hops"], 1)
        state = FusionState()
        accept_line(relay, state, lambda _error: None, now_ms=12_000)

        node = state.snapshot(now_ms=12_000)["nodes"][0]
        self.assertEqual(node["id"], 2)
        self.assertEqual(node["hops"], 1)
        self.assertEqual(node["rssi_last"], -57)

    def test_every_committed_recording_is_accepted(self):
        paths = sorted(DATA.glob("*.jsonl"))
        self.assertGreaterEqual(len(paths), 6)
        for path in paths:
            state = FusionState()
            errors = []
            accepted = read_lines(path.read_text(encoding="utf-8").splitlines(), state, errors.append, now_ms=20_000)
            self.assertEqual(errors, [], path.name)
            self.assertGreater(accepted, 0, path.name)
            snap = state.snapshot(now_ms=20_000)
            self.assertTrue(snap["nodes"] or snap["gateway"], path.name)
            for node in snap["nodes"]:
                self.assertIn(node["batt_mv_status"], {"unimplemented", "reported"})
                if node["uptime_s"] is not None:
                    self.assertIsInstance(node["uptime_s"], int)
