"""bench.py: fast offline accuracy check for heatmap.Fusion (simulated time, no web server).

Scenario per trial: room chatter on every node for WARM s, then HAIL, then the survivor knocks
(3-knock bursts) from a random position inside the node area. Reports the peak error after the reply.
    python fusion/bench.py                    # default 3-node test layout, 20 trials
    python fusion/bench.py --trials 50 --chatter 1.0 --group 0.15
"""
import argparse
import math
import random
import statistics
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heatmap  # noqa: E402


def run_trial(pos, rnd, chatter, warm, src=None):
    F = heatmap.Fusion(pos)
    gain = {i: rnd.uniform(-3, 3) for i in pos}
    floor = {i: -22 + gain[i] + rnd.uniform(-1, 1) for i in pos}
    xs = [p[0] for p in pos.values()]; ys = [p[1] for p in pos.values()]
    if src is None:
        src = (rnd.uniform(min(xs), max(xs)), rnd.uniform(min(ys), max(ys)))
    t0 = 1_000_000.0
    F.started = t0
    F.last_decay = t0
    msgs = []

    def ev(t, i, kind, peak, count, conf):
        msgs.append({"type": "event", "src": i, "kind": kind, "peak_db": int(round(peak)), "voice_db": -128,
                     "count": count, "conf": int(max(0, min(100, conf))), "hops": 0,
                     "t_host": t + 0.25 + rnd.uniform(0, 0.03)})  # 250 ms LOUD hold + mesh jitter

    end = warm + 25
    t = 0.0
    while t < end:
        if abs(t % 2) < 1e-9:
            for i in pos:
                msgs.append({"type": "beacon", "src": i, "floor_db": int(round(floor[i])), "hops": 0, "t_host": t0 + t})
        for i in pos:
            if rnd.random() < chatter * 0.05:
                ev(t0 + t, i, "LOUD", floor[i] + rnd.uniform(10, 14), 1, rnd.uniform(40, 55))
        t = round(t + 0.05, 2)
    hail = t0 + warm
    msgs.append({"type": "host_cmd", "text": "CMD HAIL 0 255", "t_host": hail})
    # survivor replies 4-12 s after HAIL: three 3-knock bursts
    for burst in (4.0, 7.5, 11.0):
        for k in range(3):
            tk = hail + burst + 0.6 * k
            S = -8 + rnd.uniform(-2, 2)
            for i, p in pos.items():
                d = max(math.dist(src, p), 0.3)
                L = min(S - 20 * math.log10(d) + gain[i] + rnd.gauss(0, 3), -1)
                heard = L >= floor[i] + heatmap.ONSET_DB
                if heard:
                    ev(tk, i, "LOUD", L, 1, 4 * (L - floor[i]))
                if d < 0.8 and rnd.random() < 0.5:
                    ev(tk, i, "VIBRATION", L if heard else floor[i], rnd.randint(2, 20), 90 if heard else 60)
    msgs.sort(key=lambda m: m["t_host"])
    j = 0
    tt = t0
    while tt < t0 + end:
        while j < len(msgs) and msgs[j]["t_host"] <= tt:
            F.ingest(msgs[j]); j += 1
        F.tick(tt)
        tt += 0.1
    s = F.snapshot(tt)
    pk = s["peak"]
    return (math.dist((pk["x"], pk["y"]), src) if pk else None), src, pk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=20)
    ap.add_argument("--chatter", type=float, default=0.7, help="mic events per node per second")
    ap.add_argument("--warm", type=float, default=150)
    ap.add_argument("--group", type=float, default=None, help="override GROUP_S")
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    if a.group is not None:
        heatmap.GROUP_S = a.group
    pos = {1: (0.0, 0.0), 2: (3.0, 0.0), 5: (0.0, 3.0)}
    rnd = random.Random(a.seed)
    errs, miss = [], 0
    for _ in range(a.trials):
        e, src, pk = run_trial(pos, rnd, a.chatter, a.warm)
        if e is None:
            miss += 1
        else:
            errs.append(e)
    errs.sort()
    if errs:
        print(f"GROUP_S={heatmap.GROUP_S} chatter={a.chatter}/s: median error {statistics.median(errs):.2f} m, "
              f"80th pct {errs[int(0.8 * (len(errs) - 1))]:.2f} m, within 1 m {sum(e <= 1 for e in errs)}/{a.trials}, no peak {miss}")
    else:
        print("no peaks")


if __name__ == "__main__":
    main()
