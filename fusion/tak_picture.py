"""Build the picture fusion/tak.py sends to TAK: node markers with simple evidence text in the remarks.
fusion/server.py adds the heatmap peak ("T10 LOOK HERE") as "sources" (docs/DECISIONS.md 2026-11-08 ~07:10).

Shape (the one tak.py already understands, see docs/TAK.md):
  {"nodes": [{"id", "x", "y", "alive", "callsign", "remarks"}], "sources": [], "note": str}

Node positions come from the drone camera's drops or --pos. A node the gateway reports without a position
cannot be placed on a map, so it is listed in "unplaced" and not sent.
"""

import time

from fusion.state import CUE_FRESH_MS

# Short, field-readable names for the remarks.
SHORT = {"TAP_PATTERN": "TAP", "VIBRATION": "FELT", "VOICE_LIKE": "VOICE", "LOUD": "LOUD"}


def build_picture(snapshot, positions, now_ms):
    by_id = {node["id"]: node for node in snapshot.get("nodes", [])}
    nodes = []
    for node_id in sorted(positions):
        x, y = positions[node_id]
        node = by_id.get(node_id)
        alive = node is not None and node.get("status") == "active"
        fresh = _fresh_cues(node, now_ms) if node else []
        # Fixed callsign: every callsign change re-sends the marker, and a re-send while its details pane is
        # open crashes WinTAK (docs/DECISIONS.md). The cue goes in the remarks, refreshed every 20 s.
        callsign = f"T10 N{node_id}" + ("" if alive else " LOST")
        nodes.append({
            "id": node_id, "x": float(x), "y": float(y), "alive": alive,
            "callsign": callsign, "remarks": _remarks(node_id, node, alive, fresh),
        })
    unplaced = sorted(i for i in by_id if i not in positions)
    note = f"nodes without a position: {unplaced}" if unplaced else ""
    return {"nodes": nodes, "sources": [], "note": note, "unplaced": unplaced}


def _fresh_cues(node, now_ms):
    fresh = []
    for evidence in node.get("evidence") or []:
        if evidence.get("kind") not in SHORT or evidence.get("kind_status") == "unclassified":
            continue
        ingest = evidence.get("t_ingest_ms", evidence.get("t_host"))
        if ingest is not None and 0 <= now_ms - ingest <= CUE_FRESH_MS:
            fresh.append(evidence)
    return fresh


def _remarks(node_id, node, alive, fresh):
    if node is None:
        return f"Sensor node {node_id}. Not heard yet."
    if not alive:
        return f"Sensor node {node_id}. NOT reporting (lost or out of range)."
    if not fresh:
        return f"Sensor node {node_id}. Reporting. No sound or vibration in the last {CUE_FRESH_MS // 1000} s."
    last = fresh[-1]
    when = time.strftime("%H:%M:%S", time.localtime(last["t_ingest_ms"] / 1000.0)) if last.get("t_ingest_ms") else "?"
    count = f" x{last['count']}" if last.get("count") and last["kind"] == "TAP_PATTERN" else ""
    kinds = ", ".join(sorted({SHORT[e["kind"]] for e in fresh}))
    return (f"Sensor node {node_id}. Last: {SHORT[last['kind']]}{count} at {when}. "
            f"Heard in last {CUE_FRESH_MS // 1000} s: {kinds}. "
            "Evidence at this node, not a survivor location.")
