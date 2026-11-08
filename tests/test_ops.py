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
        self.assertEqual(sorted(d["people"]), ["ble", "ble_devices", "est", "felt_nodes", "sound", "vibration"])
        self.assertEqual(sorted(d["heat"]), sorted(["bounds", "res", "nx", "ny", "heat", "peak", "sources", "people_est",
                                                    "hail_age", "warmup"]))


class PeopleEstimateTest(unittest.TestCase):
    """EST. PEOPLE = separate evidence hotspots (rough): broad blobs count once, close or weak spots don't add."""

    def heat(self, *blobs):
        import numpy as np

        from fusion.heatmap import Fusion

        f = Fusion({1: (0, 0), 2: (4, 0), 3: (0, 4)}, use_bg=False)
        X, Y = np.meshgrid(f.gx, f.gy)
        f.heat = sum(a * np.exp(-((X - x) ** 2 + (Y - y) ** 2) / (2 * s * s)) for a, x, y, s in blobs)
        return f.snapshot(0)

    def test_counts(self):
        two = self.heat((2.0, 1, 1, 0.6), (1.6, 3.5, 3, 0.6))
        self.assertEqual(two["people_est"], 2)
        self.assertEqual((two["sources"][0]["x"], two["sources"][0]["y"]), (two["peak"]["x"], two["peak"]["y"]))
        self.assertEqual(self.heat((2.0, 1, 1, 1.5))["people_est"], 1)                     # one broad blob
        self.assertEqual(self.heat((2.0, 1, 1, 0.6), (1.8, 1.8, 1, 0.6))["people_est"], 1)  # 0.8 m apart: one
        self.assertEqual(self.heat((2.0, 1, 1, 0.6), (0.5, 3.5, 3, 0.6))["people_est"], 1)  # weak second
        self.assertEqual(self.heat((0.0, 1, 1, 0.6))["people_est"], 0)                     # nothing
        ridge = [(1.0 + 0.15 * (k % 2), 0, k * 0.5, 1.2) for k in range(9)]               # bumpy ridge (spread-out nodes)
        self.assertEqual(self.heat(*ridge)["people_est"], 1)

    def test_not_reported_while_learning_the_room(self):
        from fusion.heatmap import Fusion

        f = Fusion({1: (0, 0), 2: (4, 0)})
        self.assertIsNone(f.snapshot(f.started + 5)["people_est"])


class CombinedPeopleTest(unittest.TestCase):
    """fusion/people.py: the largest of sound hotspots, felt-tap spots and nearby personal devices / 1.5."""

    def test_channels_and_largest_wins(self):
        from fusion.people import estimate

        now = 1000.0
        pos = {1: (0, 0), 2: (1, 0), 3: (5, 0)}
        felt = lambda t, edges: [t, "VIBRATION", -15, edges, 90]
        series = {1: {"events": [felt(990, 6)]}, 2: {"events": [felt(995, 3)]}, 3: {"events": [felt(980, 9), felt(900, 9)]}}
        dev = lambda h, kind, rssi, t=995: {"hash": h, "kind": kind, "rssi": rssi, "t": t, "src": 1}
        devices = [dev("a", "BLE_APPLE", -50), dev("b", "BLE_APPLE", -60), dev("c", "BLE_FINDMY", -70),
                   dev("d", "BLE_OTHER", -40),          # generic BLE: not a person
                   dev("e", "BLE_APPLE", -85),          # too far
                   dev("f", "WIFI_PROBE", -55, t=900)]  # too old
        r = estimate(2, series, devices, pos, now)
        self.assertEqual((r["vibration"], r["felt_nodes"]), (2, [1, 2, 3]))  # N1+N2 are 1 m apart: one spot
        self.assertEqual((r["ble_devices"], r["ble"]), (3, 2))               # 3 devices / 1.5
        self.assertEqual(r["est"], 2)                                          # largest, not the sum
        self.assertEqual(estimate(None, {}, devices * 0, pos, now)["est"], 0)  # warm-up, nothing else: 0
        many = [dev(str(i), "BLE_APPLE", -55) for i in range(30)]
        self.assertEqual(estimate(1, series, many, pos, now)["est"], 20)       # a crowd of phones drives it

    def test_unique_devices_across_nodes(self):
        state, hist = FusionState(), History()
        state.observers.append(hist.ingest)
        feed(state, SEEN, SEEN.replace('"src":1', '"src":2').replace("-52", "-40"))
        devs = {d["hash"]: d for d in hist.devices(NOW / 1000.0, 60)}
        self.assertEqual(sorted(devs), ["07bb4e10", "9f3a01c2"])
        self.assertEqual((devs["9f3a01c2"]["rssi"], devs["9f3a01c2"]["src"]), (-40, 2))  # strongest reading kept


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
