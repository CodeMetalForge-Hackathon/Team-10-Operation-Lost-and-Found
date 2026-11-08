import json
import unittest

from fusion.serial_ingest import accept_line
from fusion.state import FusionState


BEACON = (
    '{"type":"beacon","src":3,"seq":120,"hops":1,"rssi_last":-58,'
    '"batt_mv":3950,"floor_db":-62,"nbrs":[[1,-55],[2,-71]]}'
)
FEAT = (
    '{"type":"feat","src":3,"seq":121,"hops":1,"rssi_last":-58,"t_ms":51234,'
    '"rms_db":-40,"low_db":-50,"voice_db":-42,"high_db":-55,"peak_db":-30}'
)
EVENT = (
    '{"type":"event","src":3,"seq":122,"hops":2,"rssi_last":-70,"t_ms":51800,'
    '"kind":"TAP_PATTERN","peak_db":-20,"voice_db":-35,"count":3,"conf":80}'
)
RANGE = '{"type":"range","src":2,"chirper":3,"delay_us":10450,"snr_db":18}'
DEVICE = (
    '{"type":"device_seen","src":4,"seq":88,"hops":1,"rssi_last":-61,"t_ms":60000,'
    '"devs":[["9f3a01c2","BLE_APPLE",-52,14],["07bb4e10","WIFI_PROBE",-70,2]]}'
)


def feed(state, line, now_ms):
    errors = []
    accept_line(line, state, errors.append, now_ms=now_ms)
    return errors


class NodeAppearsTest(unittest.TestCase):
    def test_a_beacon_adds_an_active_unlocalized_node(self):
        state = FusionState(stale_after_ms=6000)

        errors = feed(state, BEACON, 1_000)

        snap = state.snapshot(now_ms=1_000)
        self.assertEqual(errors, [])
        self.assertEqual(snap["localization_mode"], "UNLOCALIZED")
        self.assertEqual(snap["nodes"][0]["id"], 3)
        self.assertEqual(snap["nodes"][0]["status"], "active")
        self.assertEqual(snap["nodes"][0]["search_priority"], "quiet")
        self.assertIsNone(snap["nodes"][0]["position"])
        self.assertNotIn("confirmed", json.dumps(snap).lower())
        self.assertNotIn("lat", snap)
        self.assertNotIn("lon", snap)


class AcousticEvidenceTest(unittest.TestCase):
    def test_a_tap_event_raises_search_priority_without_a_location(self):
        state = FusionState()
        feed(state, BEACON, 1_000)
        errors = feed(state, EVENT, 1_500)

        node = state.snapshot(now_ms=1_500)["nodes"][0]
        self.assertEqual(errors, [])
        self.assertEqual(node["search_priority"], "elevated")
        self.assertEqual(node["evidence"][0]["kind"], "TAP_PATTERN")
        self.assertEqual(node["evidence"][0]["count"], 3)
        self.assertEqual(node["evidence"][0]["conf"], 80)
        self.assertIsNone(node["position"])
        banner = state.snapshot(now_ms=1_500)["banner"]["text"]
        self.assertIn("not a confirmed location", banner)
        self.assertNotIn("confirmed survivor", banner.lower())


class InactiveNodeTest(unittest.TestCase):
    def test_a_silent_node_becomes_inactive_after_the_stale_window(self):
        state = FusionState(stale_after_ms=6000)
        feed(state, BEACON, 1_000)

        self.assertEqual(state.snapshot(now_ms=7_000)["nodes"][0]["status"], "active")
        self.assertEqual(state.snapshot(now_ms=7_001)["nodes"][0]["status"], "inactive")


class DeviceSeenTest(unittest.TestCase):
    def test_device_seen_keeps_the_hash_and_does_not_count_a_survivor(self):
        state = FusionState()
        errors = feed(state, DEVICE, 2_000)

        snap = state.snapshot(now_ms=2_000)
        self.assertEqual(errors, [])
        self.assertEqual(snap["banner"]["possible_acoustic"], 0)
        self.assertEqual(snap["devices"][0]["hash"], "9f3a01c2")
        self.assertEqual(snap["devices"][0]["kind"], "BLE_APPLE")
        self.assertEqual(snap["devices"][0]["rssi_max"], -52)
        self.assertEqual(snap["devices"][0]["count"], 14)
        self.assertEqual(snap["devices"][0]["heard_by"], 4)
        self.assertEqual(snap["devices"][1]["kind"], "WIFI_PROBE")
        self.assertNotIn(":", snap["devices"][0]["hash"])
        self.assertIsNone(snap["nodes"][0]["position"])


class ContractPathTest(unittest.TestCase):
    def test_all_five_gateway_types_reach_one_snapshot(self):
        state = FusionState()
        errors = []
        for line in (BEACON, FEAT, EVENT, RANGE, DEVICE):
            errors.extend(feed(state, line, 3_000))

        snap = state.snapshot(now_ms=3_000)
        self.assertEqual(errors, [])
        ids = [node["id"] for node in snap["nodes"]]
        self.assertEqual(ids, [2, 3, 4])
        node3 = snap["nodes"][1]
        self.assertEqual(node3["latest_feat"]["rms_db"], -40)
        self.assertEqual(node3["evidence"][0]["kind"], "TAP_PATTERN")
        self.assertEqual(snap["ranges"][0]["delay_us"], 10450)
        self.assertEqual(snap["ranges"][0]["chirper"], 3)
        self.assertEqual(len(snap["devices"]), 2)
        self.assertEqual(snap["links"][0], {"a": 3, "b": 1, "rssi": -55})
        self.assertTrue(all(node["position"] is None for node in snap["nodes"]))
