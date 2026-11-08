import unittest

from fusion.serial_ingest import accept_line
from fusion.state import FusionState
from sim.demo import KEEPALIVE_SRC, SCRIPT, keepalive_line


class DemoScriptTest(unittest.TestCase):
    def test_the_script_is_simulated_and_covers_the_five_gateway_types(self):
        state = FusionState(stale_after_ms=6000)
        state.simulated = True
        errors = []
        for _at, line in SCRIPT:
            accept_line(line, state, errors.append, now_ms=2_200)

        self.assertEqual(errors, [])
        kinds = {json_type(line) for _at, line in SCRIPT}
        self.assertEqual(kinds, {"beacon", "feat", "event", "range", "device_seen"})

        early = state.snapshot(now_ms=2_200)
        by_id = {node["id"]: node for node in early["nodes"]}
        self.assertEqual(by_id[3]["status"], "active")
        self.assertEqual(by_id[3]["search_priority"], "elevated")
        self.assertEqual(by_id[3]["evidence"][0]["kind"], "TAP_PATTERN")
        self.assertEqual(early["devices"][0]["kind"], "BLE_APPLE")
        self.assertTrue(early["simulated"])
        self.assertIsNone(by_id[3]["position"])

        accept_line(keepalive_line(10), state, errors.append, now_ms=9_000)
        later = state.snapshot(now_ms=9_000)
        later_by_id = {node["id"]: node for node in later["nodes"]}
        self.assertEqual(later_by_id[3]["status"], "inactive")
        self.assertEqual(later_by_id[KEEPALIVE_SRC]["status"], "active")
        self.assertEqual(later_by_id[3]["search_priority"], "elevated")
        self.assertIn("not a confirmed location", later["banner"]["text"])


def json_type(line):
    import json

    return json.loads(line)["type"]
