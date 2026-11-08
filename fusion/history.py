"""Rolling per-node sensor history for the ops dashboard's graphs (last WINDOW_S seconds).

Registered as a FusionState observer, so it sees every accepted gateway line (stamped by serial_ingest:
t_ingest_ms = host receipt time). Keeps only what the charts draw:
  audio   from feat:        (t, rms_db, peak_db)                  1 Hz per node
  events  from event:       (t, kind, peak_db, count, conf)       LOUD / VOICE_LIKE / TAP_PATTERN / VIBRATION
  ble     from device_seen: (t, n_devs, strongest_dbm, {kind: n}) every 10 s per node
  devices from device_seen: hash -> latest {t, kind, rssi (strongest at any node), src}, for unique-device counts
"""

import threading
import time
from collections import defaultdict, deque

WINDOW_S = 300.0
NO_DB = -128  # firmware sentinel: not available


class History:
    def __init__(self, window_s=WINDOW_S):
        self.window_s = window_s
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.audio = defaultdict(deque)
            self.events = defaultdict(deque)
            self.ble = defaultdict(deque)
            self.dev = {}

    def ingest(self, m):
        kind, src = m.get("type"), m.get("src")
        if src is None or kind not in ("feat", "event", "device_seen"):
            return
        t = m.get("t_ingest_ms", time.time() * 1000) / 1000.0
        with self.lock:
            if kind == "feat":
                self.audio[src].append((t, _db(m.get("rms_db")), _db(m.get("peak_db"))))
            elif kind == "event":
                self.events[src].append((t, m.get("kind"), _db(m.get("peak_db")), m.get("count"), m.get("conf")))
            else:
                devs = m.get("devs") or []
                kinds = defaultdict(int)
                for digest, dev_kind, rssi, _count in devs:
                    kinds[dev_kind] += 1
                    old = self.dev.get(digest)  # keep the strongest reading, refreshed if older than 30 s
                    if old is None or t - old["t"] > 30 or rssi >= old["rssi"]:
                        self.dev[digest] = {"t": t, "kind": dev_kind, "rssi": rssi, "src": src}
                    else:
                        old["t"] = t
                strongest = max((d[2] for d in devs), default=None)
                self.ble[src].append((t, len(devs), strongest, dict(kinds)))

    def series(self, now_s):
        """{node_id: {"audio": [[t, rms, peak]], "events": [[t, kind, peak, count, conf]], "ble": [[t, n, dbm, kinds]]}}"""
        cut = now_s - self.window_s
        out = {}
        with self.lock:
            for name, table in (("audio", self.audio), ("events", self.events), ("ble", self.ble)):
                for src, rows in table.items():
                    while rows and rows[0][0] < cut:
                        rows.popleft()
                    out.setdefault(src, {"audio": [], "events": [], "ble": []})[name] = [
                        [round(r[0], 2), *r[1:]] for r in rows]
        return out

    def devices(self, now_s, window_s):
        """Unique device hashes heard in the last window_s: [{"hash", "t", "kind", "rssi", "src"}]."""
        with self.lock:
            for digest in [k for k, v in self.dev.items() if now_s - v["t"] > self.window_s]:
                del self.dev[digest]
            return [dict(v, hash=k) for k, v in self.dev.items() if now_s - v["t"] <= window_s]


def _db(value):
    return None if value is None or value == NO_DB else value
