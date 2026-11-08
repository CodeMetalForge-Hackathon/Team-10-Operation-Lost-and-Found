"""Rough estimate of how many people the system is detecting. A planning number, not a headcount.

Each channel counts separate sources over the last WINDOW_S seconds:
  sound      separate evidence hotspots on the heatmap (fusion/heatmap.py Fusion._hotspots; None during warm-up)
  vibration  groups of nodes that felt taps (SW-420 VIBRATION, >= FELT_MIN_EDGES edges), nodes closer than
             FELT_SEP_M grouped together: the switch only feels taps within about 1 m, so separate groups mean
             separate tappers
  ble        unique nearby personal devices (Apple / Find My / Google / Wi-Fi probe, >= NEAR_DBM at some node)
             / DEVICES_PER_PERSON (a phone plus, often, a watch or earbuds). Generic BLE (TVs, beacons, laptops)
             is left out.
The estimate is the LARGEST channel: one person can tap, talk and carry a phone, so adding channels would
double count. The breakdown is reported alongside so the operator sees which channel drives it.
"""

import math

WINDOW_S = 60.0
FELT_MIN_EDGES = 2
FELT_SEP_M = 1.5
NEAR_DBM = -75
DEVICES_PER_PERSON = 1.5
PERSONAL = {"BLE_APPLE", "BLE_FINDMY", "BLE_GOOGLE", "WIFI_PROBE"}


def estimate(sound, series, devices, positions, now_s):
    felt = sorted({int(src) for src, h in series.items() for e in h["events"]
                   if e[1] == "VIBRATION" and now_s - e[0] <= WINDOW_S and (e[3] or 0) >= FELT_MIN_EDGES})
    groups = []
    for n in felt:
        p = positions.get(n)
        near = [g for g in groups if p is not None and any(
            positions.get(m) is not None and math.dist(p, positions[m]) < FELT_SEP_M for m in g)]
        if near:
            near[0].append(n)
        else:
            groups.append([n])
    nearby = [d for d in devices if d["kind"] in PERSONAL and d["rssi"] is not None and d["rssi"] >= NEAR_DBM
              and now_s - d["t"] <= WINDOW_S]
    ble = math.ceil(len(nearby) / DEVICES_PER_PERSON)
    channels = [v for v in (sound, len(groups), ble) if v is not None]
    return {"est": max(channels) if channels else None, "sound": sound, "vibration": len(groups),
            "felt_nodes": felt, "ble": ble, "ble_devices": len(nearby)}
