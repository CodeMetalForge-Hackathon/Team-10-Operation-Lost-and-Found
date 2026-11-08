"""heatmap.py: test acoustic/vibration heatmap from gateway events, served as a live web page.

Sources (pick one):
  python fusion/heatmap.py --port COM13                      # live gateway (S3) on USB; also records to data/live_*.jsonl
  python fusion/heatmap.py --replay data/some_run.jsonl      # replay a recording (t_host pacing, --speed 2 for 2x)
  python fusion/heatmap.py --sim --sim-src 2.2,0.8           # built-in simulator: taps from a hidden source + room noise
Then open http://localhost:8000

Node positions (metres, local frame) default to the 3-node test layout: N1 (0,0), N2 (3,0), N5 (0,3).
Override with --pos 1=0,0 --pos 2=3,0 --pos 5=0,3 ...

Model (docs/SENSORS.md section 1, field meanings in docs/ARCHITECTURE.md section 2):
  * Events from different nodes arriving within GROUP_S of each other, of the same kind, are one sound.
  * Per group, on a GRID_M grid: level_i = S - 20*log10(max(d_i, 0.3)) + g_i, S solved in closed form.
    Nodes that heard it fit their peak_db (a clipped reading >= -3 dBFS is only a lower bound).
    Alive nodes that reported nothing (or only felt it) must be predicted below floor_i + 10 dB.
    SW-420 "felt" adds a proximity term exp(-d^2 / 2*FELT_SIGMA_M^2) around that node.
  * likelihood = exp(-SSR / 2*SIGMA_DB^2), weighted by conf and kind, accumulated with HALF_LIFE_S decay.
  * Change detection: a slow baseline (BG_HALF_LIFE_S) of the same evidence is subtracted, so steady room
    chatter cancels and new/growing activity (tapping, HAIL replies) stands out. --no-bg shows raw evidence.
  * Per-node gain g_i = floor_i - median(floor): assumes the room noise is the same at every node,
    so a node whose floor reads higher has a hotter mic (disable with --no-gain).
"""
import argparse
import json
import math
import os
import queue
import random
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GROUP_S = 0.15         # one sound reaches all nodes within ~10 ms + mesh jitter; wider windows group unrelated chatter
CLOSE_S = 0.6          # a group is evaluated 0.6 s after its first event
GRID_M = 0.1
MARGIN_M = 1.0
SIGMA_DB = 5.0         # model misfit (reflections, mic differences, clipping)
ONSET_DB = 10.0        # node firmware onset threshold above floor
CLIP_DB = -3.0         # readings at/above this are clipped: lower bound only
FELT_SIGMA_M = 0.7     # SW-420 feels taps within roughly 0.5-1 m
HALF_LIFE_S = 20.0
BG_HALF_LIFE_S = 120.0  # slow baseline of the same evidence; the map shows fast - baseline (change detection)
ALIVE_S = 6.0
# Evidence weights. Measured on N2: the SW-420 has no false triggers at rest, while the hall produces
# ~1 mic event per node per second from chatter, so felt/rhythmic evidence counts most, and mic-only
# sounds count by how far above the floor they were and how many nodes heard them.
KIND_W = {"TAP_PATTERN": 1.0, "VIBRATION": 1.0, "LOUD": 0.3, "VOICE_LIKE": 0.2}
SNR_LO, SNR_HI = 8.0, 20.0     # mic-only weight ramps from 0.1 at 8 dB over floor to 1.0 at 20 dB
OUTSIDE_SIGMA_M = 0.5          # prior: sources are inside the area the nodes were dropped around
HAIL_REPLY = (3.5, 13.5)  # seconds after HAIL: node blanking ends ~3.5 s, listen ~10 s
HAIL_BOOST = 2.0


# ----------------------------------------------------------------------------- model
class Fusion:
    def __init__(self, pos, use_gain=True, use_bg=True):
        self.lock = threading.Lock()
        self.pos = {int(k): np.array(v, float) for k, v in pos.items()}
        xs = [p[0] for p in self.pos.values()]
        ys = [p[1] for p in self.pos.values()]
        self.x0, self.x1 = min(xs) - MARGIN_M, max(xs) + MARGIN_M
        self.y0, self.y1 = min(ys) - MARGIN_M, max(ys) + MARGIN_M
        self.gx = np.arange(self.x0, self.x1 + 1e-9, GRID_M)
        self.gy = np.arange(self.y0, self.y1 + 1e-9, GRID_M)
        X, Y = np.meshgrid(self.gx, self.gy)  # shape (ny, nx)
        self.dist = {i: np.hypot(X - p[0], Y - p[1]) for i, p in self.pos.items()}
        self.att = {i: 20 * np.log10(np.maximum(d, 0.3)) for i, d in self.dist.items()}
        nx0, nx1, ny0, ny1 = min(xs), max(xs), min(ys), max(ys)
        dout = np.hypot(np.maximum(0, np.maximum(nx0 - X, X - nx1)), np.maximum(0, np.maximum(ny0 - Y, Y - ny1)))
        self.prior = np.exp(-dout ** 2 / (2 * OUTSIDE_SIGMA_M ** 2))
        self.heat = np.zeros_like(X)
        self.bg = np.zeros_like(X)
        self.started = time.time()
        self.last_decay = time.time()
        self.use_gain = use_gain
        self.use_bg = use_bg
        self.nodes = {i: {"floor": None, "last": 0.0, "rssi": None, "hops": None, "batt": 0} for i in self.pos}
        self.groups = []          # open groups: {"kind", "t0", "ev": {node: msg}}
        self.log = []             # recent processed groups for the UI
        self.recent = []          # recent raw events (for node flashes)
        self.hail_t = None
        self.unknown = set()
        self.counts = {}

    def gains(self):
        fl = {i: n["floor"] for i, n in self.nodes.items() if n["floor"] is not None and n["floor"] < 0}
        if not self.use_gain or len(fl) < 2:
            return {i: 0.0 for i in self.pos}
        med = statistics.median(fl.values())
        return {i: (fl[i] - med) if i in fl else 0.0 for i in self.pos}

    def alive(self, i, now):
        return now - self.nodes[i]["last"] < ALIVE_S

    def ingest(self, m):
        t = m.get("t_host", time.time())
        typ = m.get("type")
        with self.lock:
            if typ == "host_cmd" and "HAIL" in m.get("text", ""):
                self.hail_t = t
                return
            src = m.get("src")
            if src is None:
                return
            if src not in self.pos:
                self.unknown.add(src)
                return
            n = self.nodes[src]
            n["last"] = t
            if m.get("hops") is not None:
                n["hops"], n["rssi"] = m["hops"], m.get("rssi_last")
            if typ == "beacon":
                if m.get("floor_db", 0) < 0:
                    n["floor"] = m["floor_db"]
                n["batt"] = m.get("batt_mv", 0)
            elif typ == "event" and m.get("kind") in KIND_W:
                self.counts[m["kind"]] = self.counts.get(m["kind"], 0) + 1
                self.recent.append((t, src, m["kind"]))
                for g in self.groups:
                    if g["kind"] == m["kind"] and t - g["t0"] <= GROUP_S:
                        old = g["ev"].get(src)
                        if old is None or m["peak_db"] > old["peak_db"]:
                            g["ev"][src] = m
                        break
                else:
                    self.groups.append({"kind": m["kind"], "t0": t, "ev": {src: m}})

    def tick(self, now):
        with self.lock:
            # decay
            dt = now - self.last_decay
            self.heat *= 0.5 ** (dt / HALF_LIFE_S)
            self.bg *= 0.5 ** (dt / BG_HALF_LIFE_S)
            self.last_decay = now
            self.recent = [r for r in self.recent if now - r[0] < 3.0]
            done = [g for g in self.groups if now - g["t0"] >= CLOSE_S]
            self.groups = [g for g in self.groups if now - g["t0"] < CLOSE_S]
            for g in done:
                self.evaluate(g, now)

    def evaluate(self, g, now):
        gain = self.gains()
        heard, felt_only = {}, []
        for i, m in g["ev"].items():
            floor = self.nodes[i]["floor"] if self.nodes[i]["floor"] is not None else -22.0
            if m["peak_db"] > floor + 3:  # mic actually heard it (felt-only VIBRATION carries the floor)
                heard[i] = m["peak_db"] - gain[i]
            if m["kind"] == "VIBRATION" and m["peak_db"] <= floor + 3:
                felt_only.append(i)
        felt = [i for i, m in g["ev"].items() if m["kind"] == "VIBRATION"]
        silent = [i for i in self.pos if self.alive(i, now) and i not in heard]

        shape = self.heat.shape
        if heard:
            # closed-form source level S per cell, using non-clipped heard nodes (all if all clipped)
            fit = [i for i in heard if heard[i] < CLIP_DB] or list(heard)
            S = sum(heard[i] + self.att[i] for i in fit) / len(fit)
            ssr = np.zeros(shape)
            for i, L in heard.items():
                pred = S - self.att[i]
                r = (L - pred) if L < CLIP_DB else np.maximum(0.0, L - pred)  # clipped: only "at least"
                ssr += r * r
            for i in silent:
                fl = self.nodes[i]["floor"] if self.nodes[i]["floor"] is not None else -22.0
                thr = fl - gain[i] + ONSET_DB
                ssr += np.maximum(0.0, (S - self.att[i]) - thr) ** 2
            like = np.exp(-ssr / (2 * SIGMA_DB ** 2))
        else:
            like = np.ones(shape)
        for i in felt:
            like = like * np.exp(-self.dist[i] ** 2 / (2 * FELT_SIGMA_M ** 2))
        like = like * self.prior
        if like.max() <= 0:
            return
        like = like / like.max()

        conf = max(m.get("conf", 50) for m in g["ev"].values()) / 100.0
        w = KIND_W[g["kind"]] * max(conf, 0.2)
        if g["kind"] in ("LOUD", "VOICE_LIKE") and not felt:
            snr = max((m["peak_db"] - (self.nodes[i]["floor"] or -22.0)) for i, m in g["ev"].items())
            w *= min(1.0, max(0.1, 0.1 + 0.9 * (snr - SNR_LO) / (SNR_HI - SNR_LO)))
        w *= len(heard) if len(heard) > 1 else 1.0  # agreement across nodes
        in_reply = self.hail_t is not None and HAIL_REPLY[0] <= g["t0"] - self.hail_t <= HAIL_REPLY[1]
        if in_reply:
            w *= HAIL_BOOST
        self.heat += w * like
        if not in_reply:  # HAIL replies are wanted signal: keep them out of the background
            self.bg += w * like
        iy, ix = np.unravel_index(int(np.argmax(like)), shape)
        self.log.append({
            "t": round(g["t0"], 2), "kind": g["kind"], "w": round(w, 2), "reply": in_reply,
            "nodes": {str(i): {"peak": m["peak_db"], "count": m.get("count"), "conf": m.get("conf"),
                               "heard": i in heard, "felt": i in felt} for i, m in g["ev"].items()},
            "best": [round(float(self.gx[ix]), 2), round(float(self.gy[iy]), 2)],
        })
        self.log = self.log[-40:]

    def snapshot(self, now):
        with self.lock:
            # Steady background accumulates in both maps in the ratio of their half-lives, so
            # heat - bg * ratio cancels it; new or growing activity stays positive.
            ratio = HALF_LIFE_S / BG_HALF_LIFE_S
            h = np.maximum(0.0, self.heat - self.bg * ratio) if self.use_bg else self.heat
            hmax = float(h.max())
            peak = None
            if hmax > 0.3:  # about one confident event's worth
                iy, ix = np.unravel_index(int(np.argmax(h)), h.shape)
                mask = h >= 0.5 * hmax
                Y, X = np.nonzero(mask)
                spread = float(np.sqrt(((self.gx[X] - self.gx[ix]) ** 2 + (self.gy[Y] - self.gy[iy]) ** 2).mean()))
                peak = {"x": round(float(self.gx[ix]), 2), "y": round(float(self.gy[iy]), 2),
                        "strength": round(hmax, 2), "radius": round(max(spread, GRID_M), 2)}
            gain = self.gains()
            hail_age = (now - self.hail_t) if self.hail_t else None
            return {
                "bounds": [self.x0, self.x1, self.y0, self.y1], "res": GRID_M,
                "nx": len(self.gx), "ny": len(self.gy),
                "heat": np.round(h / hmax, 3).ravel().tolist() if hmax > 0 else [],
                "hmax": round(hmax, 3), "peak": peak,
                "nodes": [{"id": i, "x": float(p[0]), "y": float(p[1]), "alive": self.alive(i, now),
                           "floor": self.nodes[i]["floor"], "gain": round(gain[i], 1),
                           "rssi": self.nodes[i]["rssi"], "hops": self.nodes[i]["hops"],
                           "flash": sorted({k for (t, s, k) in self.recent if s == i})}
                          for i, p in self.pos.items()],
                "log": self.log[-15:][::-1], "counts": self.counts,
                "hail_age": round(hail_age, 1) if hail_age is not None and hail_age < 20 else None,
                "unknown": sorted(self.unknown),
                "warmup": round(max(0.0, BG_HALF_LIFE_S - (now - self.started))) if self.use_bg else 0,
            }

    def reset(self):
        with self.lock:
            self.heat[:] = 0
            self.bg[:] = 0
            self.started = time.time()
            self.log.clear()


# ----------------------------------------------------------------------------- sources
def serial_source(port, out_q, cmd_q, rec_path, meta):
    import serial
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = port, 921600, 0.05
    s.dtr = s.rts = False
    for _ in range(40):
        try:
            s.open()
            break
        except serial.SerialException:
            time.sleep(0.25)
    else:
        raise SystemExit(f"cannot open {port} (close Arduino Serial Monitor / WinTAK)")
    with open(rec_path.replace(".jsonl", ".meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    rec = open(rec_path, "w", encoding="utf-8")
    buf = b""
    while True:
        try:
            while True:
                c = cmd_q.get_nowait()
                s.write((c + "\n").encode())
                m = {"type": "host_cmd", "text": c, "t_host": round(time.time(), 3)}
                rec.write(json.dumps(m) + "\n")
                out_q.put(m)
        except queue.Empty:
            pass
        buf += s.read(2048)
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            line = raw.decode(errors="replace").strip()
            if not line.startswith("{"):
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:
                continue
            m["t_host"] = round(time.time(), 3)
            rec.write(json.dumps(m) + "\n")
            rec.flush()
            out_q.put(m)


def replay_source(path, out_q, speed):
    msgs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip().startswith("{")]
    msgs = [m for m in msgs if "t_host" in m]
    t_first, wall0 = msgs[0]["t_host"], time.time()
    for m in msgs:
        target = wall0 + (m["t_host"] - t_first) / speed
        while time.time() < target:
            time.sleep(0.01)
        m = dict(m, t_host=time.time())
        out_q.put(m)
    print("# replay finished")


def sim_source(pos, src_xy, out_q, cmd_q):
    """Gateway-like messages: beacons, room chatter, and a tapping 'survivor' at src_xy."""
    rnd = random.Random(1)
    gain = {i: rnd.uniform(-3, 3) for i in pos}
    floor = {i: -22 + gain[i] + rnd.uniform(-1, 1) for i in pos}
    seq = {i: 0 for i in pos}
    t_beacon = t_tap = time.time()
    hail_t = None

    def ev(i, kind, peak, count, conf, v2=-128):
        seq[i] += 1
        out_q.put({"type": "event", "src": i, "seq": seq[i], "hops": 0, "rssi_last": -40, "t_ms": 0,
                   "kind": kind, "peak_db": int(round(peak)), "voice_db": v2, "count": count,
                   "conf": int(max(0, min(100, conf))), "t_host": time.time() + rnd.uniform(0, 0.05)})

    while True:
        now = time.time()
        try:
            c = cmd_q.get_nowait()
            out_q.put({"type": "host_cmd", "text": c, "t_host": now})
            if "HAIL" in c:
                hail_t = now
        except queue.Empty:
            pass
        if now - t_beacon >= 2:
            t_beacon = now
            for i in pos:
                seq[i] += 1
                out_q.put({"type": "beacon", "src": i, "seq": seq[i], "hops": 0, "rssi_last": -40,
                           "batt_mv": 0, "floor_db": int(round(floor[i])), "nbrs": [], "t_host": now})
        # room chatter: ~0.7 events/s per node, a few dB over the onset threshold
        for i in pos:
            if rnd.random() < 0.7 * 0.05:
                if rnd.random() < 0.6:
                    ev(i, "LOUD", floor[i] + rnd.uniform(10, 14), 1, rnd.uniform(40, 55))
                else:
                    ev(i, "VOICE_LIKE", floor[i] + rnd.uniform(8, 12), rnd.randint(4, 20), rnd.uniform(35, 45),
                       v2=int(floor[i] + 7))
        # the survivor knocks every ~6 s (more eagerly right after a HAIL)
        period = 6.0
        if hail_t and 4 <= now - hail_t <= 6:
            period = 0.5
        if now - t_tap >= period:
            t_tap = now
            S = -8 + rnd.uniform(-2, 2)  # level at 1 m
            for i, p in pos.items():
                d = max(math.dist(src_xy, p), 0.3)
                L = min(S - 20 * math.log10(d) + gain[i] + rnd.gauss(0, 3), -1)
                heard = L >= floor[i] + ONSET_DB
                if heard:
                    ev(i, "LOUD", L, 1, 4 * (L - floor[i]))
                if d < 0.8 and rnd.random() < 0.5:
                    ev(i, "VIBRATION", L if heard else floor[i], rnd.randint(2, 20), 90 if heard else 60)
        time.sleep(0.05)


# ----------------------------------------------------------------------------- web
PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Team 10 heatmap (test)</title>
<style>
body{margin:0;font:14px system-ui,sans-serif;background:#111;color:#ddd;display:flex;gap:16px;padding:16px}
canvas{background:#1b1b1b;border:1px solid #333}
#side{min-width:380px;max-width:460px} h2{margin:4px 0 8px;font-size:16px}
button{background:#2a2a2a;color:#eee;border:1px solid #555;padding:6px 12px;margin:0 6px 8px 0;cursor:pointer}
.ev{font:12px ui-monospace,monospace;border-bottom:1px solid #2a2a2a;padding:3px 0}
.reply{color:#7fd} .muted{color:#888} #peak{font-size:15px;margin:8px 0}
</style></head><body>
<canvas id="c" width="640" height="640"></canvas>
<div id="side"><h2>Team 10: where to dig (test heatmap)</h2>
<div><button onclick="cmd('HAIL')">HAIL</button><button onclick="cmd('PING')">PING</button><button onclick="cmd('BLINK')">BLINK</button><button onclick="fetch('/reset',{method:'POST'})">Reset map</button></div>
<div id="peak"></div><div id="hail" class="reply"></div><div id="nodes"></div>
<h2>Sound / vibration groups</h2><div id="log"></div><div id="counts" class="muted"></div></div>
<script>
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
function cmd(n){fetch('/cmd?name='+n,{method:'POST'})}
function col(v){ // transparent -> blue -> yellow -> red
  if(v<0.05)return null; const a=Math.min(1,0.25+v);
  const r=v<0.5?Math.round(510*v):255, g=v<0.5?Math.round(160+190*v):Math.round(255*(1-v)*2), b=v<0.5?Math.round(255*(1-2*v)):0;
  return `rgba(${r},${g},${b},${a})`;}
async function tick(){
  let s; try{s=await (await fetch('/state')).json()}catch(e){return}
  const [x0,x1,y0,y1]=s.bounds, W=cv.width,H=cv.height, sc=Math.min(W/(x1-x0),H/(y1-y0));
  const px=x=>(x-x0)*sc, py=y=>H-(y-y0)*sc;
  ctx.clearRect(0,0,W,H);
  if(s.heat.length){const cw=s.res*sc+1;
    for(let j=0;j<s.ny;j++)for(let i=0;i<s.nx;i++){const c=col(s.heat[j*s.nx+i]); if(!c)continue;
      ctx.fillStyle=c; ctx.fillRect(px(x0+i*s.res-s.res/2),py(y0+j*s.res+s.res/2),cw,cw);}}
  ctx.strokeStyle='#333';ctx.lineWidth=1;ctx.fillStyle='#666';ctx.font='11px sans-serif';
  for(let x=Math.ceil(x0);x<=x1;x++){ctx.beginPath();ctx.moveTo(px(x),0);ctx.lineTo(px(x),H);ctx.stroke();ctx.fillText(x+' m',px(x)+2,H-4)}
  for(let y=Math.ceil(y0);y<=y1;y++){ctx.beginPath();ctx.moveTo(0,py(y));ctx.lineTo(W,py(y));ctx.stroke();ctx.fillText(y+' m',2,py(y)-2)}
  for(const n of s.nodes){const X=px(n.x),Y=py(n.y);
    if(n.flash.length){ctx.strokeStyle=n.flash.includes('VIBRATION')?'#f0f':'#0ff';ctx.lineWidth=3;ctx.beginPath();ctx.arc(X,Y,20,0,7);ctx.stroke()}
    ctx.fillStyle=n.alive?'#4c4':'#a33';ctx.beginPath();ctx.arc(X,Y,9,0,7);ctx.fill();
    ctx.fillStyle='#fff';ctx.font='bold 13px sans-serif';ctx.fillText('N'+n.id,X+12,Y-10);}
  const p=s.peak; const pk=document.getElementById('peak');
  if(p){const X=px(p.x),Y=py(p.y);ctx.strokeStyle='#fff';ctx.lineWidth=2;
    ctx.beginPath();ctx.arc(X,Y,Math.max(8,p.radius*sc),0,7);ctx.stroke();
    ctx.beginPath();ctx.moveTo(X-10,Y);ctx.lineTo(X+10,Y);ctx.moveTo(X,Y-10);ctx.lineTo(X,Y+10);ctx.stroke();
    pk.innerHTML=`<b>Dig here:</b> (${p.x.toFixed(1)}, ${p.y.toFixed(1)}) m &plusmn;${p.radius.toFixed(1)} m &middot; strength ${p.strength}`;}
  else pk.innerHTML='<span class="muted">No confident source yet</span>';
  if(s.warmup>0) pk.innerHTML+=`<div class="muted">learning room background: ${s.warmup}s left (map may show steady noise until then)</div>`;
  document.getElementById('hail').textContent=s.hail_age!=null?`HAIL ${s.hail_age}s ago ${s.hail_age<3.5?'(nodes deaf until 3.5 s)':s.hail_age<13.5?'- LISTENING for replies (x2 weight)':''}`:'';
  document.getElementById('nodes').innerHTML=s.nodes.map(n=>`<div class="ev">N${n.id} ${n.alive?'alive':'<b style="color:#e55">LOST</b>'} floor ${n.floor??'?'} dBFS gain ${n.gain>=0?'+':''}${n.gain} dB ${n.hops!=null?'hops '+n.hops:''}</div>`).join('')+(s.unknown.length?`<div class="muted">ignored unknown nodes: ${s.unknown}</div>`:'');
  document.getElementById('log').innerHTML=s.log.map(g=>`<div class="ev ${g.reply?'reply':''}">${new Date(g.t*1000).toLocaleTimeString()} ${g.kind} w${g.w} &rarr; (${g.best}) `+Object.entries(g.nodes).map(([k,v])=>`N${k}:${v.peak}${v.felt?'F':''}${v.heard?'':'(not heard)'}`).join(' ')+'</div>').join('');
  document.getElementById('counts').textContent='events received: '+JSON.stringify(s.counts);
}
setInterval(tick,500);tick();
</script></body></html>"""


def make_handler(fusion, cmd_q):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            b = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path.startswith("/state"):
                self._send(200, json.dumps(fusion.snapshot(time.time())), "application/json")
            else:
                self._send(200, PAGE, "text/html; charset=utf-8")

        def do_POST(self):
            if self.path.startswith("/cmd"):
                name = self.path.split("name=")[-1].upper()
                if name in ("HAIL", "PING", "BLINK"):
                    cmd_q.put(f"CMD {name} 0 255")
                self._send(200, "ok", "text/plain")
            elif self.path.startswith("/reset"):
                fusion.reset()
                self._send(200, "ok", "text/plain")
            else:
                self._send(404, "no", "text/plain")
    return H


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--port", help="gateway serial port, e.g. COM13")
    g.add_argument("--replay", help="data/*.jsonl recording")
    g.add_argument("--sim", action="store_true")
    ap.add_argument("--pos", action="append", default=[], help="ID=x,y metres (default: 1=0,0 2=3,0 5=0,3)")
    ap.add_argument("--sim-src", default="2.0,1.0", help="simulated survivor position x,y")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--http", type=int, default=8000)
    ap.add_argument("--no-gain", action="store_true")
    ap.add_argument("--no-bg", action="store_true", help="show raw accumulated evidence (no background subtraction)")
    ap.add_argument("--name", default=None, help="recording name for --port (default live_<time>)")
    ap.add_argument("--note", default="")
    a = ap.parse_args()

    pos = {1: (0.0, 0.0), 2: (3.0, 0.0), 5: (0.0, 3.0)}
    if a.pos:
        pos = {}
        for it in a.pos:
            k, xy = it.split("=")
            pos[int(k)] = tuple(float(v) for v in xy.split(","))
    fusion = Fusion(pos, use_gain=not a.no_gain, use_bg=not a.no_bg)
    msg_q, cmd_q = queue.Queue(), queue.Queue()

    if a.port:
        name = a.name or time.strftime("live_%Y%m%d_%H%M%S")
        rec = os.path.join(ROOT, "data", name + ".jsonl")
        meta = {"name": name, "port": a.port, "start": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "positions_m": {str(k): list(v) for k, v in pos.items()}, "note": a.note, "tool": "fusion/heatmap.py"}
        threading.Thread(target=serial_source, args=(a.port, msg_q, cmd_q, rec, meta), daemon=True).start()
        print(f"# recording to {rec}")
    elif a.replay:
        threading.Thread(target=replay_source, args=(a.replay, msg_q, a.speed), daemon=True).start()
    else:
        src = tuple(float(v) for v in a.sim_src.split(","))
        threading.Thread(target=sim_source, args=(pos, src, msg_q, cmd_q), daemon=True).start()
        print(f"# simulator: survivor at {src}")

    srv = ThreadingHTTPServer(("127.0.0.1", a.http), make_handler(fusion, cmd_q))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"# open http://localhost:{a.http}")
    last_print = 0
    try:
        while True:
            try:
                while True:
                    fusion.ingest(msg_q.get(timeout=0.1))
            except queue.Empty:
                pass
            now = time.time()
            fusion.tick(now)
            if now - last_print > 5:
                last_print = now
                s = fusion.snapshot(now)
                alive = [n["id"] for n in s["nodes"] if n["alive"]]
                print(f"# alive {alive} peak {s['peak']} counts {s['counts']}", flush=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
