"""William's STEP 3 firmware examples, from docs/ARCHITECTURE.md after c69393f.

These lines are the documented wire shape. They are not a committed capture.
"""

import unittest

from fusion.serial_ingest import accept_line
from fusion.state import FusionState


BEACON = (
    '{"type":"beacon","src":3,"seq":120,"hops":1,"rssi_last":-58,'
    '"batt_mv":0,"floor_db":-22,"nbrs":[[1,-55],[2,-71]]}'
)
FEAT = (
    '{"type":"feat","src":3,"seq":121,"hops":1,"rssi_last":-58,"t_ms":51234,'
    '"rms_db":-21,"low_db":-128,"voice_db":-128,"high_db":-128,"peak_db":-12}'
)
VIBRATION = (
    '{"type":"event","src":3,"seq":123,"hops":2,"rssi_last":-70,"t_ms":51790,'
    '"kind":"VIBRATION","peak_db":-11,"voice_db":-128,"count":14,"conf":90}'
)
SUSTAINED = (
    '{"type":"event","src":3,"seq":124,"hops":2,"rssi_last":-70,"t_ms":53000,'
    '"kind":"VOICE_LIKE","peak_db":-10,"voice_db":-14,"count":38,"conf":42}'
)


class Step3ContractTest(unittest.TestCase):
    def test_new_firmware_lines_keep_raw_values_and_label_sentinels(self):
        state = FusionState()
        errors = []
        for line in (BEACON, FEAT, VIBRATION, SUSTAINED):
            accept_line(line, state, errors.append, now_ms=5_000)

        self.assertEqual(errors, [])
        node = state.snapshot(now_ms=5_000)["nodes"][0]
        self.assertEqual(node["batt_mv"], 0)
        self.assertEqual(node["batt_mv_status"], "unimplemented")
        self.assertEqual(node["floor_db"], -22)
        self.assertEqual(node["floor_db_status"], "reported")
        feat = node["latest_feat"]
        self.assertEqual(feat["rms_db"], -21)
        self.assertEqual(feat["low_db"], -128)
        self.assertEqual(feat["low_db_status"], "unavailable")
        self.assertEqual(feat["voice_db_status"], "unavailable")
        self.assertEqual(feat["high_db_status"], "unavailable")
        self.assertEqual(feat["peak_db_status"], "reported")
        kinds = [item["kind"] for item in node["evidence"]]
        self.assertEqual(kinds, ["VIBRATION", "VOICE_LIKE"])
        felt = node["evidence"][0]
        self.assertEqual(felt["count"], 14)
        self.assertEqual(felt["voice_db"], -128)
        self.assertEqual(felt["voice_db_status"], "unavailable")
        sustained = node["evidence"][1]
        self.assertEqual(sustained["voice_db"], -14)
        self.assertEqual(sustained["voice_db_status"], "reported")
        self.assertEqual(node["search_priority"], "elevated")
        self.assertIsNone(node["position"])
