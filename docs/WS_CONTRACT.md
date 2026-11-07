# Proposed WebSocket contract (v1)

Status: proposed on `feat/sim-ws-dashboard` so the dashboard can run. This is not a change to the gateway JSON in `docs/ARCHITECTURE.md`. William has not agreed to freeze this shape. If it changes, change this file in the same commit and say so on issue #2.

`GET /ws` pushes this object about twice a second. `GET /state` returns the same object. There is no second schema.

## Payload

```json
{
  "v": 1,
  "simulated": true,
  "t_host": 1700000000000,
  "localization_mode": "UNLOCALIZED",
  "stale_after_ms": 6000,
  "nodes": [
    {
      "id": 3,
      "status": "active",
      "last_t_host": 1700000000000,
      "seq": 122,
      "hops": 2,
      "rssi_last": -70,
      "batt_mv": 3950,
      "floor_db": -62,
      "nbrs": [[1, -55], [2, -71]],
      "latest_feat": {
        "t_ms": 51234,
        "t_host": 1700000000000,
        "rms_db": -40,
        "low_db": -50,
        "voice_db": -42,
        "high_db": -55,
        "peak_db": -30
      },
      "evidence": [
        {
          "kind": "TAP_PATTERN",
          "t_ms": 51800,
          "t_host": 1700000000000,
          "peak_db": -20,
          "voice_db": -35,
          "count": 3,
          "conf": 80
        }
      ],
      "search_priority": "elevated",
      "position": null
    }
  ],
  "links": [{"a": 3, "b": 1, "rssi": -55}],
  "devices": [
    {
      "hash": "9f3a01c2",
      "kind": "BLE_APPLE",
      "rssi_max": -52,
      "count": 14,
      "heard_by": 4,
      "t_ms": 60000,
      "t_host": 1700000000000
    }
  ],
  "ranges": [
    {"src": 2, "chirper": 3, "delay_us": 10450, "snr_db": 18, "t_host": 1700000000000}
  ],
  "banner": {
    "possible_acoustic": 1,
    "text": "1 possible acoustic cue — not a confirmed location",
    "disclaimer": "No dig coordinate. Positions are not estimated. A device hash is not a person."
  },
  "counts": {
    "nodes_seen": 1,
    "nodes_active": 1,
    "acoustic_events": 1,
    "devices": 1,
    "packets": 5,
    "packets_per_s": 1,
    "bytes_per_s": 120
  }
}
```

`simulated` is true only when the process was started with `--demo` or `--simulate`. A serial session leaves it false. That flag does not mean the numbers were checked against a tape measure.

## Rules this host actually applies

- `position` is always `null`. `localization_mode` is always `UNLOCALIZED`. There is no latitude, longitude, or heatmap in this object.
- `status` is `inactive` when `t_host - last_t_host > stale_after_ms`. The default window is 6000 ms. A later line from the same `src` makes it active again.
- `search_priority` becomes `elevated` only for `LOUD`, `TAP_PATTERN`, or `VOICE_LIKE`. `RADAR_PRESENCE` and `GAS` are stored as evidence and do not raise it. Priority does not expire when the node goes inactive; the card shows both facts.
- `possible_acoustic` counts nodes with elevated priority. It is not a confirmed survivor count, and a `device_seen` line does not increment it.
- `device_seen` is copied from the gateway line: 8 hex characters, a kind from the contract, `rssi_max`, `count`, and the hearing `src`. The host does not reverse the hash and does not invent a device position.
- `ranges` keep `delay_us`. They are not converted to metres. Bias is not calibrated.
- `links` are the neighbor pairs from the latest beacon. A neighbor id in that list is not a node until that id sends its own line.
- `packets_per_s` and `bytes_per_s` count accepted JSON on the host in the last 1000 ms. They are not mesh bandwidth.
- Unknown `v` must be ignored by the page. This page only renders `v == 1`.

## Not in this contract

`POST /cmd`, `POST /anchor`, and `POST /baseline` still have no body. This server returns 404 for them. Outbound serial text such as `CMD HAIL 0 255` is not sent.

Do not treat this file as permission to change the five gateway JSON types.
