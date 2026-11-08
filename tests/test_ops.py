"""Ops dashboard: rolling sensor history, the /ops picture (dropped vs operational, distance matrix), routes."""

import unittest

from fastapi.testclient import TestClient

from fusion.history import History
from fusion.serial_ingest import accept_line
from fusion.server import build_ops, create_app
from fusion.state import FusionState

NOW = 1_700_000_000_000


def beacon(src, nbrs):
    return ('{"type":"beacon","src":%d,"seq":1,"hops":0,"rssi_last":-40,"batt_mv":0,'
            '"uptime_s":5,"floor_db":-22,"nbrs":%s}' % (src, nbrs))


FEAT = ('{"type":"feat","src":1,"seq":2,"hops":0,"rssi_last":-40,"t_ms":1000,"rms_db":-20,'
        '"low_db":-128,"voice_db":-128,"high_db":-128,"peak_db":-12}')
FELT = ('{"type":"event","src":2,"seq":3,"hops":0,"rssi_last":-40,"t_ms":1000,'
        '"kind":"VIBRATION","peak_db":-15,"voice_db":-128,"count":14,"conf":90}')
SEEN = ('{"type":"device_seen","src":1,"seq":4,"hops":0,"rssi_last":-40,"t_ms":1000,'
        '"devs":[["9f3a01c2","BLE_APPLE",-52,3],["07bb4e10","WIFI_PROBE",-70,1]]}')


def feed(state, *lines, at=NOW):
    for line in lines:
        accept_line(line, state, lambda _m: None, at)


class HistoryTest(unittest.TestCase):
    def test_keeps_each_sensor_and_prunes_old_rows(self):
        state, hist = FusionState(), History(window_s=60)
        state.observers.append(hist.ingest)
        feed(state, FEAT, FELT, SEEN)
        s = hist.series(NOW / 1000.0)
        self.assertEqual(s[1]["audio"], [[NOW / 1000.0, -20, -12]])
        self.assertEqual(s[2]["events"][0][1:], ["VIBRATION", -15, 14, 90])
        self.assertEqual(s[1]["ble"][0][1:], [2, -52, {"BLE_APPLE": 1, "WIFI_PROBE": 1}])
        self.assertEqual(hist.series(NOW / 1000.0 + 61), {1: {"audio": [], "events": [], "ble": []},
                                                          2: {"audio": [], "events": [], "ble": []}})


class OpsPictureTest(unittest.TestCase):
    def test_dropped_operational_and_matrix(self):
        state = FusionState()
        # N1 hears N2 at -40, N2 hears N1 at -50 -> link -45. N3 is dropped but silent. N4 is heard, not dropped.
        feed(state, beacon(1, "[[2,-40]]"), beacon(2, "[[1,-50]]"), beacon(4, "[]"))
        snap = state.snapshot(NOW)
        snap["tak_bridge"] = {"polling": False}
        pos = {1: (0.0, 0.0), 2: (3.0, 4.0), 3: (0.0, 1.0)}
        d = build_ops(snap, None, pos, {}, ":8080", NOW)
        self.assertEqual(d["dropped"], [1, 2, 3])
        self.assertEqual(d["operational"], [1, 2])
        self.assertEqual(d["heard_not_dropped"], [4])
        m = d["matrix"]
        self.assertEqual(m["ids"], [1, 2, 3, 4])
        self.assertEqual(m["metres"][0][1], 5.0)
        self.assertEqual(m["metres"][1][0], 5.0)
        self.assertIsNone(m["metres"][0][3])   # N4 has no position
        self.assertEqual(m["dbm"][0][1], -45)
        self.assertEqual(m["dbm"][1][0], -45)
        self.assertIsNone(m["dbm"][0][2])       # no link reported
        self.assertIsNone(m["dbm"][0][0])
        self.assertEqual(d["mosaic_url"], ":8080")

    def test_ops_endpoint_carries_history_and_heat(self):
        from fusion.heatmap import Fusion

        state = FusionState()
        heat = Fusion({1: (0.0, 0.0), 2: (3.0, 0.0)})
        state.observers.append(heat.ingest)
        client = TestClient(create_app(state, now_ms=lambda: NOW, heatmap=heat, positions={1: (0.0, 0.0), 2: (3.0, 0.0)}))
        feed(state, beacon(1, "[]"), FEAT)
        d = client.get("/ops").json()
        self.assertEqual(d["operational"], [1])
        self.assertEqual(d["history"]["1"]["audio"][0][1], -20)
        self.assertEqual(sorted(d["heat"]), sorted(["bounds", "res", "nx", "ny", "heat", "peak", "hail_age", "warmup"]))


class RoutesTest(unittest.TestCase):
    def test_root_is_the_ops_dashboard_and_review_keeps_the_evidence_page(self):
        client = TestClient(create_app(FusionState(), now_ms=lambda: NOW))
        root, review = client.get("/"), client.get("/review")
        self.assertIn("T10 Ops", root.text)
        self.assertIn("/assets/ops.js", root.text)
        self.assertIn("Operations overview", review.text)
        self.assertEqual(client.get("/assets/ops.js").status_code, 200)
        self.assertEqual(client.get("/assets/ops.css").status_code, 200)


if __name__ == "__main__":
    unittest.main()
