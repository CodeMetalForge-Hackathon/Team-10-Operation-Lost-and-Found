"""In-memory fusion state. This is not a location estimate."""

import threading


STALE_AFTER_MS = 6000
ACOUSTIC_KINDS = {"LOUD", "TAP_PATTERN", "VOICE_LIKE", "VIBRATION"}


SENSOR_TYPES = {"beacon", "feat", "event", "range", "device_seen"}
DIAGNOSTIC_TYPES = {"gw", "log", "host_cmd"}


def db_status(value):
    """-128 is the firmware sentinel for a dB field that was not computed."""
    if value is None:
        return "absent"
    if value == -128:
        return "unavailable"
    return "reported"


def measurement_status(value):
    """Current node firmware hardcodes batt_mv and floor_db to 0 until measured.

    Zero is that sentinel, not a reading. A non-zero value is reported as sent.
    A future firmware that measures a true 0 dB floor must stop using this sentinel.
    """
    if value is None:
        return "absent"
    if value == 0:
        return "unimplemented"
    return "reported"


class FusionState:
    def __init__(self, stale_after_ms=STALE_AFTER_MS, store=None):
        self.stale_after_ms = stale_after_ms
        self.simulated = False
        self.source = "live"
        self.playback = None
        self.store = store
        self._lock = threading.Lock()
        self._nodes = {}
        self._devices = {}
        self._ranges = {}
        self._packets = []
        self._gateway = None
        self._logs = []
        self._host_cmds = []

    def accept(self, observation):
        with self._lock:
            if self.store is not None:
                self.store.append(observation, source=self._provenance())
            kind = observation.get("type")
            t_host = observation.get("t_host")
            if kind == "gw":
                self._gateway = {
                    "id": observation.get("id"),
                    "t_ms": observation.get("t_ms"),
                    "rx_dropped": observation.get("rx_dropped"),
                    "t_host": t_host,
                    "t_recorded_s": observation.get("t_recorded_s"),
                }
                return
            if kind == "log":
                self._remember(self._logs, observation, t_host)
                return
            if kind == "host_cmd":
                self._remember(self._host_cmds, observation, t_host)
                return
            encoded = _nbytes(observation)
            self._packets.append((t_host, encoded))
            if kind == "range":
                node = self._touch(observation["src"], t_host)
                if "hops" in observation:
                    node["hops"] = observation["hops"]
                if "seq" in observation:
                    node["seq"] = observation["seq"]
                if "rssi_last" in observation:
                    node["rssi_last"] = observation["rssi_last"]
                key = (observation["src"], observation["chirper"])
                record = {
                    "src": observation["src"],
                    "chirper": observation["chirper"],
                    "delay_us": observation["delay_us"],
                    "snr_db": observation["snr_db"],
                    "t_host": t_host,
                }
                if "hops" in observation:
                    record["hops"] = observation["hops"]
                self._ranges[key] = record
                return
            src = observation["src"]
            node = self._touch(src, t_host)
            node["seq"] = observation.get("seq")
            node["hops"] = observation.get("hops")
            node["rssi_last"] = observation.get("rssi_last")
            if kind == "beacon":
                node["batt_mv"] = observation.get("batt_mv")
                node["floor_db"] = observation.get("floor_db")
                node["uptime_s"] = observation.get("uptime_s", node.get("uptime_s"))
                node["nbrs"] = observation.get("nbrs") or []
            elif kind == "feat":
                node["latest_feat"] = _feat(observation, t_host)
            elif kind == "event":
                evidence = {
                    "kind": observation.get("kind"),
                    "t_ms": observation.get("t_ms"),
                    "t_host": t_host,
                    "peak_db": observation.get("peak_db"),
                    "peak_db_status": db_status(observation.get("peak_db")),
                    "voice_db": observation.get("voice_db"),
                    "voice_db_status": db_status(observation.get("voice_db")),
                    "count": observation.get("count"),
                    "conf": observation.get("conf"),
                }
                node["evidence"].append(evidence)
                node["evidence"] = node["evidence"][-8:]
                if evidence["kind"] in ACOUSTIC_KINDS:
                    node["search_priority"] = "elevated"
            elif kind == "device_seen":
                for digest, dev_kind, rssi, count in observation.get("devs") or []:
                    key = (digest.lower(), src)
                    self._devices[key] = {
                        "hash": digest.lower(),
                        "kind": dev_kind,
                        "rssi_max": rssi,
                        "count": count,
                        "heard_by": src,
                        "t_ms": observation.get("t_ms"),
                        "t_host": t_host,
                    }

    def reset(self):
        """Drop retained observations. Keep the source flag and stale window."""
        with self._lock:
            self._nodes.clear()
            self._devices.clear()
            self._ranges.clear()
            self._packets.clear()
            self._gateway = None
            self._logs.clear()
            self._host_cmds.clear()

    def snapshot(self, now_ms):
        with self._lock:
            nodes = []
            for node_id in sorted(self._nodes):
                node = self._nodes[node_id]
                age = now_ms - node["last_t_host"]
                status = "active" if age <= self.stale_after_ms else "inactive"
                nodes.append(
                    {
                        "id": node_id,
                        "status": status,
                        "last_t_host": node["last_t_host"],
                        "seq": node["seq"],
                        "hops": node["hops"],
                        "rssi_last": node["rssi_last"],
                        "batt_mv": node["batt_mv"],
                        "batt_mv_status": measurement_status(node["batt_mv"]),
                        "floor_db": node["floor_db"],
                        "floor_db_status": measurement_status(node["floor_db"]),
                        "uptime_s": node["uptime_s"],
                        "nbrs": node["nbrs"],
                        "latest_feat": node["latest_feat"],
                        "evidence": list(node["evidence"]),
                        "search_priority": node["search_priority"],
                        "position": None,
                    }
                )
            recent = [item for item in self._packets if now_ms - item[0] <= 1000]
            acoustic = sum(1 for node in nodes if node["search_priority"] == "elevated")
            devices = list(self._devices.values())
            if not nodes:
                banner = "Waiting for a gateway line"
            elif acoustic == 0:
                banner = "0 possible survivors"
            else:
                noun = "cue" if acoustic == 1 else "cues"
                banner = (
                    f"{acoustic} possible acoustic {noun} — not a confirmed location"
                )
            source = self.source
            if self.simulated and source == "live":
                source = "simulation"
            return {
                "v": 1,
                "simulated": source == "simulation",
                "source": source,
                "playback": self.playback,
                "gateway": self._gateway,
                "diagnostics": {
                    "logs": list(self._logs),
                    "host_cmds": list(self._host_cmds),
                },
                "t_host": now_ms,
                "localization_mode": "UNLOCALIZED",
                "stale_after_ms": self.stale_after_ms,
                "nodes": nodes,
                "links": _links(nodes),
                "devices": devices,
                "ranges": [self._ranges[key] for key in sorted(self._ranges)],
                "banner": {
                    "possible_acoustic": acoustic,
                    "text": banner,
                    "disclaimer": (
                        "No dig coordinate. Positions are not estimated. "
                        "A device hash is not a person."
                    ),
                },
                "counts": {
                    "nodes_seen": len(nodes),
                    "nodes_active": sum(1 for node in nodes if node["status"] == "active"),
                    "acoustic_events": sum(len(node["evidence"]) for node in nodes),
                    "devices": len(devices),
                    "packets": len(self._packets),
                    "packets_per_s": len(recent),
                    "bytes_per_s": sum(item[1] for item in recent),
                },
            }

    def _touch(self, src, t_host):
        node = self._nodes.get(src)
        if node is None:
            node = {
                "last_t_host": t_host,
                "seq": None,
                "hops": None,
                "rssi_last": None,
                "batt_mv": None,
                "floor_db": None,
                "uptime_s": None,
                "nbrs": [],
                "latest_feat": None,
                "evidence": [],
                "search_priority": "quiet",
            }
            self._nodes[src] = node
        if t_host >= node["last_t_host"]:
            node["last_t_host"] = t_host
        return node

    def _provenance(self):
        if self.simulated and self.source == "live":
            return "simulation"
        return self.source

    def _remember(self, bucket, observation, t_host):
        bucket.append(
            {
                "text": observation.get("text"),
                "t_host": t_host,
                "t_recorded_s": observation.get("t_recorded_s"),
            }
        )
        del bucket[:-20]


def _feat(observation, t_host):
    feat = {
        "t_ms": observation.get("t_ms"),
        "t_host": t_host,
        "rms_db": observation.get("rms_db"),
        "low_db": observation.get("low_db"),
        "voice_db": observation.get("voice_db"),
        "high_db": observation.get("high_db"),
        "peak_db": observation.get("peak_db"),
    }
    for key in ("rms_db", "low_db", "voice_db", "high_db", "peak_db"):
        feat[key + "_status"] = db_status(feat[key])
    return feat


def _links(nodes):
    links = []
    for node in nodes:
        for pair in node["nbrs"]:
            if not isinstance(pair, list) or len(pair) != 2:
                continue
            links.append({"a": node["id"], "b": pair[0], "rssi": pair[1]})
    return links


def _nbytes(observation):
    import json

    return len(json.dumps(observation, separators=(",", ":")).encode("utf-8"))
