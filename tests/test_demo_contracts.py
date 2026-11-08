"""Clocks, unknown event kinds, retention, and ingest survival."""

import json
import tempfile
import unittest
from pathlib import Path

from fusion.serial_ingest import accept_line, read_lines
from fusion.state import CUE_FRESH_MS, FusionState
from fusion.store import ObservationStore
from fusion.time_contract import (
    UNIX_MS_MIN,
    as_unix_seconds,
    freshness_age_ms,
    recorded_seconds,
)


RECORDING = Path(__file__).resolve().parents[1] / "data" / "live_3node_test1.jsonl"
UNKNOWN = (
    '{"type":"event","src":5,"seq":96,"hops":0,"rssi_last":-26,"t_ms":43149,'
    '"kind":"UNKNOWN","peak_db":-24,"voice_db":-128,"count":255,"conf":60,'
    '"t_host":1794107316.334}'
)
VIBRATION = (
    '{"type":"event","src":1,"seq":3,"hops":0,"rssi_last":-40,"t_ms":900,'
    '"kind":"VIBRATION","peak_db":-11,"voice_db":-128,"count":4,"conf":60}'
)
LOUD = (
    '{"type":"event","src":1,"seq":4,"hops":0,"rssi_last":-40,"t_ms":1000,'
    '"kind":"LOUD","peak_db":-9,"voice_db":-128,"count":1,"conf":45}'
)


class ClockContractTest(unittest.TestCase):
    def test_seconds_and_milliseconds_are_not_the_same_instant(self):
        recorded = 1794107316.334
        ingest = 1_700_000_000_000
        self.assertEqual(recorded_seconds(recorded), recorded)
        self.assertIsNone(recorded_seconds(ingest))
        self.assertLess(recorded, UNIX_MS_MIN)
        self.assertGreaterEqual(ingest, UNIX_MS_MIN)
        self.assertEqual(as_unix_seconds(recorded), recorded)
        self.assertEqual(as_unix_seconds(ingest), ingest / 1000.0)
        self.assertNotEqual(int(recorded), ingest)
        self.assertEqual(freshness_age_ms(ingest + 1500, ingest), 1500)
        mixed = ingest - recorded
        self.assertGreater(mixed, 1_000_000_000)
        self.assertLess(freshness_age_ms(ingest + 1500, ingest), 10_000)

    def test_recording_line_keeps_capture_time_and_stamps_ingest_time(self):
        state = FusionState()
        errors = []
        accept_line(UNKNOWN, state, errors.append, now_ms=1_700_000_000_000)
        evidence = state.snapshot(1_700_000_000_000)["nodes"][0]["evidence"][0]
        self.assertEqual(errors, [])
        self.assertEqual(evidence["t_recorded_s"], 1794107316.334)
        self.assertEqual(evidence["t_ingest_ms"], 1_700_000_000_000)
        self.assertEqual(evidence["t_device_ms"], 43149)
        self.assertNotEqual(evidence["t_host"], evidence["t_recorded_s"])
        self.assertNotEqual(int(evidence["t_recorded_s"]), evidence["t_ingest_ms"])


class UnknownKindTest(unittest.TestCase):
    def test_unknown_kind_is_kept_and_vibration_still_passes(self):
        state = FusionState()
        errors = []
        accept_line(UNKNOWN, state, errors.append, now_ms=1_000)
        accept_line(VIBRATION, state, errors.append, now_ms=1_100)
        snap = state.snapshot(1_100)
        kinds = {row["kind"]: row for node in snap["nodes"] for row in node["evidence"]}
        self.assertEqual(errors, [])
        self.assertEqual(kinds["UNKNOWN"]["kind_status"], "unclassified")
        self.assertEqual(kinds["VIBRATION"]["kind_status"], "known")
        self.assertEqual(snap["diagnostics"]["unclassified_kinds"]["UNKNOWN"], 1)
        self.assertEqual(snap["nodes"][0]["search_priority"], "elevated")

    def test_gateway_hash_line_is_a_diagnostic_not_a_rejected_observation(self):
        state = FusionState()
        errors = []
        accepted = read_lines(
            ["# sent CMD HAIL arg=0 target=255", UNKNOWN],
            state,
            errors.append,
            now_ms=2_000,
        )
        snap = state.snapshot(2_000)
        self.assertEqual(accepted, 2)
        self.assertEqual(errors, [])
        self.assertEqual(snap["diagnostics"]["logs"][0]["text"], "# sent CMD HAIL arg=0 target=255")
        self.assertEqual(len(snap["nodes"][0]["evidence"]), 1)

    def test_three_node_recording_keeps_unknown_events(self):
        state = FusionState()
        errors = []
        kept = 0
        with RECORDING.open(encoding="utf-8") as handle:
            for line in handle:
                if '"kind": "UNKNOWN"' not in line and '"kind":"UNKNOWN"' not in line:
                    continue
                accept_line(line, state, errors.append, now_ms=5_000)
                kept += 1
                if kept == 3:
                    break
        self.assertEqual(errors, [])
        self.assertEqual(kept, 3)
        self.assertEqual(state.snapshot(5_000)["diagnostics"]["unclassified_kinds"]["UNKNOWN"], 3)


class RetentionAndFailureTest(unittest.TestCase):
    def test_live_cap_does_not_drop_the_stored_row(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory) / "host.sqlite")
            state = FusionState(store=store)
            state.source = "live"
            for index in range(10):
                line = (
                    '{"type":"event","src":1,"seq":%d,"hops":0,"rssi_last":-40,"t_ms":%d,'
                    '"kind":"LOUD","peak_db":-9,"voice_db":-128,"count":1,"conf":45}'
                    % (index, 1000 + index)
                )
                accept_line(line, state, lambda _error: None, now_ms=10_000 + index)
            snap = state.snapshot(10_000)
            stored = store.get(1)
            self.assertIsNotNone(stored)
            store.close()
        self.assertEqual(len(snap["nodes"][0]["evidence"]), 8)
        self.assertEqual(snap["counts"]["stored_observations"], 10)
        self.assertEqual(stored["historical"], True)
        self.assertEqual(stored["raw"]["kind"], "LOUD")
        self.assertNotEqual(stored["t_host"], stored.get("t_recorded_s"))

    def test_a_failed_database_write_does_not_stop_the_next_line(self):
        class Broken:
            def append(self, _observation, source):
                raise OSError("disk full")

        state = FusionState(store=Broken())
        errors = []
        accept_line(LOUD, state, errors.append, now_ms=1_000)
        accept_line(VIBRATION, state, errors.append, now_ms=1_100)
        snap = state.snapshot(1_100)
        self.assertEqual(errors, [])
        self.assertEqual(snap["diagnostics"]["store_errors"], 2)
        self.assertEqual(len(snap["nodes"][0]["evidence"]), 2)
        self.assertIn("disk full", snap["diagnostics"]["last_store_error"])

    def test_acoustic_priority_expires_without_hiding_reporting(self):
        state = FusionState()
        accept_line(LOUD, state, lambda _error: None, now_ms=1_000)
        beacon = (
            '{"type":"beacon","src":1,"seq":9,"hops":0,"rssi_last":-40,'
            '"batt_mv":0,"floor_db":0,"nbrs":[]}'
        )
        later = 1_000 + CUE_FRESH_MS + 1
        accept_line(beacon, state, lambda _error: None, now_ms=later)
        snap = state.snapshot(later)
        node = snap["nodes"][0]
        self.assertEqual(node["status"], "active")
        self.assertEqual(node["search_priority"], "stale")
        self.assertEqual(snap["banner"]["possible_acoustic"], 0)
        self.assertNotIn("survivor", snap["banner"]["text"].lower())
        self.assertEqual(len(node["evidence"]), 1)

    def test_old_devices_leave_the_live_snapshot_and_stay_stored(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ObservationStore(Path(directory) / "host.sqlite")
            state = FusionState(store=store)
            device = (
                '{"type":"device_seen","src":1,"seq":1,"hops":0,"rssi_last":-50,"t_ms":1,'
                '"devs":[["9f3a01c2","BLE_APPLE",-52,1]]}'
            )
            accept_line(device, state, lambda _error: None, now_ms=1_000)
            snap = state.snapshot(1_000 + 180_000 + 1)
            count = store.count()
            store.close()
        self.assertEqual(snap["devices"], [])
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
