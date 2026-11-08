"""In-memory fusion state. This is not a location estimate."""

import threading


STALE_AFTER_MS = 6000
CUE_FRESH_MS = 30_000
DEVICE_RETAIN_MS = 180_000
DEVICE_CAP = 64
PACKET_WINDOW_MS = 60_000
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
        self._link = {
            "transport": None,
            "connected": None,
            "last_error": None,
            "last_line_ms": None,
        }
        self._store_errors = 0
        self._last_store_error = None
        self._rejected = 0
        self._unclassified = {}
        self._packet_total = 0
        # Extra consumers of every accepted line (e.g. the heatmap estimator).
        # Called after this state is updated, outside its lock. A failing
        # observer is counted as a store error and never blocks ingest.
        self.observers = []
        self.reset_hooks = []

    def accept(self, observation):
        self._accept(observation)
        for observer in list(self.observers):
            try:
                observer(observation)
            except Exception as exc:
                self.note_store_error(f"observer {type(exc).__name__}: {exc}")

    def _accept(self, observation):
        with self._lock:
            store_id = self._persist(observation)
            kind = observation.get("type")
            t_host = observation.get("t_host")
            if t_host is not None:
                self._link["last_line_ms"] = t_host
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
            self._packet_total += 1
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
                    "kind_status": observation.get("kind_status") or "known",
                    "t_ms": observation.get("t_ms"),
                    "t_device_ms": observation.get("t_device_ms", observation.get("t_ms")),
                    "t_host": t_host,
                    "t_ingest_ms": observation.get("t_ingest_ms", t_host),
                    "t_recorded_s": observation.get("t_recorded_s"),
                    "seq": observation.get("seq"),
                    "hops": observation.get("hops"),
                    "rssi_last": observation.get("rssi_last"),
                    "peak_db": observation.get("peak_db"),
                    "peak_db_status": db_status(observation.get("peak_db")),
                    "voice_db": observation.get("voice_db"),
                    "voice_db_status": db_status(observation.get("voice_db")),
                    "count": observation.get("count"),
                    "conf": observation.get("conf"),
                    "store_id": store_id,
                }
                if evidence["kind_status"] == "unclassified":
                    self._count_unclassified(evidence["kind"])
                node["evidence"].append(evidence)
                node["evidence"] = node["evidence"][-8:]
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
            self._packet_total = 0
            self._rejected = 0
            self._unclassified = {}
        for hook in list(self.reset_hooks):
            hook()

    def snapshot(self, now_ms):
        with self._lock:
            nodes = []
            for node_id in sorted(self._nodes):
                node = self._nodes[node_id]
                age = now_ms - node["last_t_host"]
                status = "active" if age <= self.stale_after_ms else "inactive"
                priority = _cue_priority(node, now_ms)
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
                        "search_priority": priority,
                        "position": None,
                    }
                )
            self._packets = [item for item in self._packets if now_ms - item[0] <= PACKET_WINDOW_MS]
            recent = [item for item in self._packets if now_ms - item[0] <= 1000]
            acoustic = sum(1 for node in nodes if node["search_priority"] == "elevated")
            devices = _live_devices(self._devices.values(), now_ms)
            if not nodes and self._link.get("connected") is False:
                banner = "Gateway link is down"
            elif not nodes:
                banner = "Waiting for a gateway line"
            elif acoustic == 0:
                banner = "No fresh acoustic cue"
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
                    "store_errors": self._store_errors,
                    "last_store_error": self._last_store_error,
                    "rejected": self._rejected,
                    "unclassified_kinds": dict(self._unclassified),
                },
                "link": dict(self._link),
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
                    "stored_observations": self.store.count() if self.store is not None and hasattr(self.store, "count") else None,
                    "devices": len(devices),
                    "packets": self._packet_total,
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

    def note_link(self, transport=None, connected=None, last_error=None, last_line_ms=None):
        with self._lock:
            if transport is not None:
                self._link["transport"] = transport
            if connected is not None:
                self._link["connected"] = connected
            if last_error is not None or connected is True:
                self._link["last_error"] = last_error
            if last_line_ms is not None:
                self._link["last_line_ms"] = last_line_ms

    def note_reject(self, _reason):
        with self._lock:
            self._rejected += 1

    def note_store_error(self, reason):
        with self._lock:
            self._store_errors += 1
            self._last_store_error = str(reason)

    def _persist(self, observation):
        if self.store is None:
            return None
        try:
            return self.store.append(observation, source=self._provenance())
        except Exception as exc:
            self._store_errors += 1
            self._last_store_error = f"{type(exc).__name__}: {exc}"
            return None

    def _count_unclassified(self, kind):
        key = kind or "UNKNOWN"
        self._unclassified[key] = self._unclassified.get(key, 0) + 1

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


def _cue_priority(node, now_ms):
    saw_acoustic = False
    for evidence in node["evidence"]:
        if evidence.get("kind") not in ACOUSTIC_KINDS:
            continue
        if evidence.get("kind_status") == "unclassified":
            continue
        saw_acoustic = True
        ingest = evidence.get("t_ingest_ms", evidence.get("t_host"))
        if ingest is None:
            continue
        age = now_ms - ingest
        if 0 <= age <= CUE_FRESH_MS:
            return "elevated"
    return "stale" if saw_acoustic else "quiet"


def _live_devices(devices, now_ms):
    fresh = [
        device
        for device in devices
        if device.get("t_host") is not None and now_ms - device["t_host"] <= DEVICE_RETAIN_MS
    ]
    fresh.sort(key=lambda device: device.get("t_host") or 0, reverse=True)
    return fresh[:DEVICE_CAP]


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
