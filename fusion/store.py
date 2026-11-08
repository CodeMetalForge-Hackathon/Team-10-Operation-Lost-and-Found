"""Append-only SQLite history. This is not the live node table."""

import json
import sqlite3
import threading
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  msg_type TEXT NOT NULL,
  src INTEGER,
  gateway_id INTEGER,
  seq INTEGER,
  hops INTEGER,
  t_host INTEGER,
  t_recorded_s REAL,
  t_ms INTEGER,
  raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_recent ON observations (id DESC);
"""


class ObservationStore:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1')"
        )
        self._conn.commit()

    def append(self, observation, source):
        raw = json.dumps(observation, separators=(",", ":"), sort_keys=True)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO observations (
                  source, msg_type, src, gateway_id, seq, hops,
                  t_host, t_recorded_s, t_ms, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    observation.get("type"),
                    observation.get("src"),
                    observation.get("id") if observation.get("type") == "gw" else None,
                    observation.get("seq"),
                    observation.get("hops"),
                    observation.get("t_host"),
                    observation.get("t_recorded_s"),
                    observation.get("t_ms"),
                    raw,
                ),
            )
            self._conn.commit()

    def recent(self, limit=50, source=None, src=None, msg_type=None):
        limit = max(1, min(int(limit), 200))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM observations
                WHERE (? IS NULL OR source = ?)
                  AND (? IS NULL OR src = ?)
                  AND (? IS NULL OR msg_type = ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (source, source, src, src, msg_type, msg_type, limit),
            ).fetchall()
        return [_row(row) for row in rows]

    def close(self):
        with self._lock:
            self._conn.close()


def _row(row):
    raw = json.loads(row["raw_json"])
    return {
        "id": row["id"],
        "historical": True,
        "source": row["source"],
        "msg_type": row["msg_type"],
        "src": row["src"],
        "gateway_id": row["gateway_id"],
        "seq": row["seq"],
        "hops": row["hops"],
        "t_host": row["t_host"],
        "t_recorded_s": row["t_recorded_s"],
        "t_ms": row["t_ms"],
        "raw": raw,
    }
