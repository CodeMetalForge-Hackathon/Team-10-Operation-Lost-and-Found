// T10 ops dashboard. Polls GET /ops (fusion/server.py build_ops) once a second and draws:
// the heatmap over the drone camera's mosaic, the node fleet, the distance matrix, and per-sensor graphs.
"use strict";
(function () {
  // ---- colours (dataviz reference palette, dark steps). A node keeps its colour everywhere (by id).
  const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
  const GOOD = "#0ca30c", CRIT = "#d03b3b", INK = "#f0efec", INK2 = "#c3c2b7", MUTED = "#898781",
    GRID = "#2c2c2a", AXIS = "#383835", SURF = "#1a1a19";
  const BLUE = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#104281"];   // sequential: metres
  const ORANGE = ["#fbd5c2", "#f2a07a", "#d95926", "#a8401a", "#6e2a10"];  // sequential: dBm
  const colorOf = id => SERIES[(id - 1 + SERIES.length) % SERIES.length];
  const CUE_S = 30;            // "recent" window for cue badges and the sparkline
  const KIND = { TAP_PATTERN: "TAP", VIBRATION: "FELT", VOICE_LIKE: "VOICE", LOUD: "LOUD" };

  const $ = id => document.getElementById(id);
  const TAB0 = new URLSearchParams(location.search).get("tab");  // ?tab=audio|vib|ble
  const st = { d: null, sel: null, tab: ["audio", "vib", "ble"].includes(TAB0) ? TAB0 : "audio", mos: { url: null, img: null, meta: null, ver: null }, hit: [] };

  // ---------------------------------------------------------------- polling
  async function poll() {
    try {
      const r = await fetch("/ops", { cache: "no-store" });
      st.d = await r.json();
      render();
    } catch (e) {
      chip("c-src", "bad", "NO HOST");
    }
  }
  setInterval(poll, 1000);
  poll();

  function render() {
    const d = st.d;
    header(d);
    setMosaic(d.mosaic_url);
    drawMap();
    tiles(d);
    matrix(d);
    sensors(d);
  }

  // ---------------------------------------------------------------- header
  function chip(id, s, text) { const el = $(id); el.dataset.s = s; el.querySelector("span").textContent = text; }
  function header(d) {
    const src = (d.source || "live").toUpperCase();
    chip("c-src", src === "LIVE" ? "good" : "warn", src);
    const c = d.link && d.link.connected;
    chip("c-gw", c === true ? "good" : c === false ? "bad" : "", "GW");
    chip("c-tak", d.tak ? "good" : "", "TAK");
    $("scan-done").classList.toggle("off", !d.mosaic_url);
    $("n-up").textContent = d.operational.length;
    $("n-drop").textContent = d.dropped.length;
    $("n-bar").innerHTML = d.dropped.map(i =>
      `<i class="${d.operational.includes(i) ? "ok" : "bad"}" title="N${i} ${d.operational.includes(i) ? "up" : "lost"}"></i>`).join("");
    $("n-extra").textContent = d.heard_not_dropped.length ? `+${d.heard_not_dropped.length} not dropped` : "";
    // combined estimate (fusion/people.py); shown as the median of the last 10 s so it doesn't flicker
    const P = d.people || {};
    const raw = P.est;
    st.ppl = raw == null ? [] : (st.ppl || []).concat(raw).slice(-10);
    const ppl = raw == null ? null : st.ppl.slice().sort((a, b) => a - b)[Math.floor(st.ppl.length / 2)];
    $("ppl").textContent = ppl == null ? "…" : ppl;
    $("people").classList.toggle("on", ppl > 0);
    $("pps").textContent = d.packets_per_s;
    $("bps").textContent = d.bytes_per_s;
    $("clock").textContent = new Date(d.t * 1000).toLocaleTimeString([], { hour12: false });
  }

  // ---------------------------------------------------------------- commands
  document.querySelectorAll("[data-cmd]").forEach(b => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const r = await fetch("/cmd?name=" + b.dataset.cmd, { method: "POST" });
      const j = await r.json();
      toast(j.ok ? `${b.dataset.cmd} sent` : j.error, !j.ok);
    } catch (e) { toast("host not reachable", true); }
    setTimeout(() => { b.disabled = false; }, 1500);
  }));
  // Scan done: the camera (drone/live_mosaic.py) freezes its mosaic as the floor map TAK shows
  // (fusion/tak_overlay.py serves it to WinTAK, which picks it up within its refresh interval).
  $("scan-done").addEventListener("click", async () => {
    const b = $("scan-done");
    if (!st.mos.url) { toast("no live camera on this host (--mosaic :8080)", true); return; }
    b.disabled = true;
    try {
      const r = await fetch(st.mos.url + "/scan_done", { method: "POST" });
      const j = await r.json();
      toast(j.ok ? `Floor map v${j.final_version} sent to TAK (${j.keyframes} keyframes)` : j.error, !j.ok);
    } catch (e) { toast("camera not reachable", true); }
    setTimeout(() => { b.disabled = false; }, 1500);
  });
  let toastT;
  function toast(text, err) {
    const t = $("toast"); t.textContent = text; t.className = err ? "err" : ""; t.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 3000);
  }

  // ---------------------------------------------------------------- camera mosaic (as on /heatmap)
  function setMosaic(u) {
    let url = u || "";
    if (url.startsWith(":")) url = location.protocol + "//" + location.hostname + url;
    if (url === st.mos.url) return;
    st.mos = { url, img: null, meta: null, ver: null };
    pollMos();
  }
  async function pollMos() {
    const m = st.mos;
    if (m.url === null) return;
    try {
      const meta = await (await fetch(m.url + "/mosaic.json", { cache: "no-store" })).json();
      if (!meta.width || !meta.px_to_m) return;
      const v = String(meta.version ?? meta.t ?? meta.keyframes);
      if (v === m.ver) return;
      m.ver = v;
      const im = new Image();
      im.onload = () => { m.img = im; m.meta = meta; drawMap(); };
      im.src = m.url + "/mosaic.png?v=" + encodeURIComponent(v);
    } catch (e) { /* no camera: map without photo */ }
  }
  setInterval(pollMos, 2000);
  const ap = (A, p) => [A[0][0] * p[0] + A[0][1] * p[1] + A[0][2], A[1][0] * p[0] + A[1][1] * p[1] + A[1][2]];

  // ---------------------------------------------------------------- map
  const cv = $("cv"), ctx = cv.getContext("2d");
  const heatCv = document.createElement("canvas"), heatCtx = heatCv.getContext("2d");
  function heatRGBA(v) {  // one hue (orange), light -> deep, more opaque with evidence
    const a = [255, 176, 138], b = [235, 104, 52], c = [176, 52, 16];
    const [p, q, t] = v < 0.5 ? [a, b, v * 2] : [b, c, (v - 0.5) * 2];
    return [0, 1, 2].map(k => Math.round(p[k] + (q[k] - p[k]) * t)).concat(Math.round(255 * Math.min(0.85, 0.15 + v * 0.75)));
  }

  function drawMap() {
    const d = st.d;
    if (!d) return;
    const dpr = window.devicePixelRatio || 1;
    const W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr);
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = SURF; ctx.fillRect(0, 0, W, H);

    // view: the heat grid (nodes + margin), widened to the photo, padded
    const placed = d.nodes.filter(n => n.dropped);
    let b = d.heat ? d.heat.bounds.slice() : null;
    if (!b && placed.length) {
      const xs = placed.map(n => n.x), ys = placed.map(n => n.y);
      b = [Math.min(...xs) - 1, Math.max(...xs) + 1, Math.min(...ys) - 1, Math.max(...ys) + 1];
    }
    if (!b) b = [-2, 2, -2, 2];
    const m = st.mos;
    if (m.img && m.meta) {
      const A = m.meta.px_to_m, w = m.meta.width, h = m.meta.height;
      for (const p of [[0, 0], [w, 0], [w, h], [0, h]].map(q => ap(A, q))) {
        b[0] = Math.min(b[0], p[0]); b[1] = Math.max(b[1], p[0]); b[2] = Math.min(b[2], p[1]); b[3] = Math.max(b[3], p[1]);
      }
    }
    const pad = 28 * dpr;
    const sc = Math.min((W - 2 * pad) / (b[1] - b[0]), (H - 2 * pad) / (b[3] - b[2]));
    const ox = (W - sc * (b[1] - b[0])) / 2, oy = (H - sc * (b[3] - b[2])) / 2;
    const X = x => ox + (x - b[0]) * sc, Y = y => oy + (b[3] - y) * sc;

    // 1 m grid
    ctx.strokeStyle = GRID; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = Math.ceil(b[0]); x <= b[1]; x++) { ctx.moveTo(X(x), Y(b[2])); ctx.lineTo(X(x), Y(b[3])); }
    for (let y = Math.ceil(b[2]); y <= b[3]; y++) { ctx.moveTo(X(b[0]), Y(y)); ctx.lineTo(X(b[1]), Y(y)); }
    ctx.stroke();

    // camera mosaic: mosaic px -> metres (meta.px_to_m) -> canvas
    if (m.img && m.meta) {
      const A = m.meta.px_to_m;
      ctx.save();
      ctx.setTransform(sc * A[0][0], -sc * A[1][0], sc * A[0][1], -sc * A[1][1], ox + (A[0][2] - b[0]) * sc, oy + (b[3] - A[1][2]) * sc);
      ctx.globalAlpha = 0.9; ctx.drawImage(m.img, 0, 0);
      ctx.restore();
    }

    // evidence heat: one pixel per cell, scaled up
    const h = d.heat;
    if (h && h.heat && h.heat.length) {
      heatCv.width = h.nx; heatCv.height = h.ny;
      const img = heatCtx.createImageData(h.nx, h.ny);
      for (let j = 0; j < h.ny; j++) for (let i = 0; i < h.nx; i++) {
        const v = h.heat[j * h.nx + i];
        if (v < 0.12) continue;
        const o = ((h.ny - 1 - j) * h.nx + i) * 4, c = heatRGBA(v);
        img.data[o] = c[0]; img.data[o + 1] = c[1]; img.data[o + 2] = c[2]; img.data[o + 3] = c[3];
      }
      heatCtx.putImageData(img, 0, 0);
      ctx.imageSmoothingEnabled = true;
      const gx0 = h.bounds[0] - h.res / 2, gy1 = h.bounds[2] + (h.ny - 0.5) * h.res;
      ctx.drawImage(heatCv, X(gx0), Y(gy1), h.nx * h.res * sc, h.ny * h.res * sc);
    }

    // mesh links between dropped nodes: thicker + brighter = stronger
    const ids = d.matrix.ids;
    for (let a = 0; a < ids.length; a++) for (let c = a + 1; c < ids.length; c++) {
      const na = d.nodes[a], nc = d.nodes[c], dbm = d.matrix.dbm[a][c];
      if (!na.dropped || !nc.dropped || dbm == null) continue;
      const q = Math.max(0, Math.min(1, (dbm + 90) / 60));
      ctx.strokeStyle = `rgba(240,239,236,${0.15 + 0.45 * q})`; ctx.lineWidth = (1 + 2 * q) * dpr;
      ctx.setLineDash([4 * dpr, 4 * dpr]);
      ctx.beginPath(); ctx.moveTo(X(na.x), Y(na.y)); ctx.lineTo(X(nc.x), Y(nc.y)); ctx.stroke();
    }
    ctx.setLineDash([]);

    // LOOK HERE
    const pk = h && h.peak, t = performance.now() / 1000;
    if (pk) {
      const cx = X(pk.x), cy = Y(pk.y), r = Math.max(14 * dpr, pk.radius * sc);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 * dpr; ctx.setLineDash([7 * dpr, 5 * dpr]);
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.stroke(); ctx.setLineDash([]);
      ctx.globalAlpha = 0.5 + 0.5 * Math.sin(t * 4);
      ctx.beginPath(); ctx.arc(cx, cy, 10 * dpr, 0, 7); ctx.stroke(); ctx.globalAlpha = 1;
      ctx.beginPath(); ctx.moveTo(cx - 16 * dpr, cy); ctx.lineTo(cx + 16 * dpr, cy); ctx.moveTo(cx, cy - 16 * dpr); ctx.lineTo(cx, cy + 16 * dpr); ctx.stroke();
    }

    // other hotspots (each counts toward EST. PEOPLE): smaller dashed rings
    ((h && h.people_est && h.sources) || []).slice(1).forEach((q, k) => {
      const cx = X(q.x), cy = Y(q.y);
      ctx.strokeStyle = INK2; ctx.lineWidth = 1.5 * dpr; ctx.setLineDash([5 * dpr, 4 * dpr]);
      ctx.beginPath(); ctx.arc(cx, cy, 13 * dpr, 0, 7); ctx.stroke(); ctx.setLineDash([]);
      ctx.font = `700 ${11 * dpr}px system-ui, sans-serif`; ctx.fillStyle = INK2; ctx.textAlign = "center";
      ctx.fillText(String(k + 2), cx, cy + 4 * dpr); ctx.textAlign = "start";
    });

    // nodes: identity colour fill, status ring, flash ring on a fresh cue
    st.hit = [];
    const now = d.t;
    for (const n of placed) {
      const x = X(n.x), y = Y(n.y), R = 10 * dpr;
      const ev = (d.history[n.id] || {}).events || [];
      const fresh = ev.length && now - ev[ev.length - 1][0] < 2.5;
      if (fresh) {
        ctx.strokeStyle = ev[ev.length - 1][1] === "VIBRATION" || ev[ev.length - 1][1] === "TAP_PATTERN" ? "#f5a3c4" : "#7fdcb6";
        ctx.lineWidth = 3 * dpr; ctx.beginPath(); ctx.arc(x, y, R + 9 * dpr, 0, 7); ctx.stroke();
      }
      ctx.fillStyle = colorOf(n.id); ctx.beginPath(); ctx.arc(x, y, R, 0, 7); ctx.fill();
      ctx.strokeStyle = n.alive ? GOOD : CRIT; ctx.lineWidth = 3 * dpr; ctx.beginPath(); ctx.arc(x, y, R + 2 * dpr, 0, 7); ctx.stroke();
      if (!n.alive) {
        ctx.strokeStyle = CRIT; ctx.lineWidth = 2.5 * dpr; ctx.beginPath();
        ctx.moveTo(x - 6 * dpr, y - 6 * dpr); ctx.lineTo(x + 6 * dpr, y + 6 * dpr); ctx.moveTo(x + 6 * dpr, y - 6 * dpr); ctx.lineTo(x - 6 * dpr, y + 6 * dpr); ctx.stroke();
      }
      if (st.sel === n.id) { ctx.strokeStyle = "#fff"; ctx.lineWidth = 2 * dpr; ctx.beginPath(); ctx.arc(x, y, R + 7 * dpr, 0, 7); ctx.stroke(); }
      ctx.font = `700 ${13 * dpr}px system-ui, sans-serif`; ctx.fillStyle = INK;
      ctx.shadowColor = "#000"; ctx.shadowBlur = 4 * dpr;
      ctx.fillText("N" + n.id, x + R + 6 * dpr, y - R);
      ctx.shadowBlur = 0;
      st.hit.push({ id: n.id, x: x / dpr, y: y / dpr });
    }

    // overlay pills
    $("look").hidden = !pk;
    if (pk) $("look").innerHTML = `<b>LOOK HERE</b>${pk.x.toFixed(1)}, ${pk.y.toFixed(1)} m<span class="unc">±${pk.radius.toFixed(1)} m</span>`;
    const ha = h && h.hail_age;
    $("hail").hidden = ha == null;
    if (ha != null) {
      const listening = ha >= 3.5 && ha < 13.5;
      $("hail-txt").textContent = ha < 3.5 ? `HAIL · beeping` : listening ? `HAIL · LISTENING ${Math.ceil(13.5 - ha)} s` : `HAIL ${Math.round(ha)} s ago`;
      $("hail-bar").style.width = `${Math.max(0, Math.min(100, (13.5 - ha) / 10 * 100))}%`;
    }
    $("warm").hidden = !(h && h.warmup > 0);
    if (h && h.warmup > 0) $("warm").textContent = `learning background ${h.warmup} s`;
    const meters = 1 / (sc / dpr) * 80;
    $("scale").textContent = `▬ ${meters < 1 ? meters.toFixed(1) : Math.round(meters)} m / 80 px`;
  }
  cv.addEventListener("click", e => {
    const hit = st.hit.find(p => Math.hypot(p.x - e.offsetX, p.y - e.offsetY) < 18);
    select(hit ? hit.id : null);
  });
  // keep the LOOK HERE pulse alive between polls
  setInterval(() => { if (st.d && st.d.heat && st.d.heat.peak) drawMap(); }, 120);

  function select(id) {
    st.sel = st.sel === id ? null : id;
    drawMap(); tiles(st.d, true); sensors(st.d, true);
  }

  // ---------------------------------------------------------------- fleet tiles
  function recent(ev, now, kind) { return ev.filter(e => e[1] === kind && now - e[0] < CUE_S).length; }
  function tiles(d, force) {
    if (!d) return;
    const order = d.nodes.filter(n => n.dropped).concat(d.nodes.filter(n => !n.dropped && d.heard_not_dropped.includes(n.id)));
    $("fleet-sub").textContent = `${d.operational.length} up · ${d.dropped.length - d.operational.length} lost · ${d.heard_not_dropped.length} not dropped`;
    const box = $("tiles");
    const key = order.map(n => n.id).join(",");
    if (box.dataset.key !== key) {
      box.dataset.key = key;
      box.innerHTML = order.map(n => `<div class="tile" data-id="${n.id}" style="--c:${colorOf(n.id)}">
        <div class="t-head"><i class="sw"></i><span class="id">N${n.id}</span><span class="st"></span></div>
        <canvas class="spark"></canvas>
        <div class="cues"></div><div class="t-foot"></div></div>`).join("") ||
        `<p class="muted">No nodes heard yet.</p>`;
      box.querySelectorAll(".tile").forEach(el => el.addEventListener("click", () => select(+el.dataset.id)));
    }
    for (const n of order) {
      const el = box.querySelector(`.tile[data-id="${n.id}"]`);
      const h = d.history[n.id] || { audio: [], events: [], ble: [] };
      const state = !n.dropped ? "ghost" : n.alive ? "ok" : "bad";
      el.className = `tile ${state === "bad" ? "lost" : state === "ghost" ? "ghost" : ""} ${st.sel === n.id ? "sel" : ""}`;
      const s = el.querySelector(".st");
      s.className = "st " + state;
      s.textContent = state === "ok" ? "✓ UP" : state === "bad" ? "✕ LOST" : "○ NOT DROPPED";
      const nb = h.ble.length ? h.ble[h.ble.length - 1][1] : 0;
      const counts = [["tap", "TAP", recent(h.events, d.t, "TAP_PATTERN")], ["felt", "FELT", recent(h.events, d.t, "VIBRATION")],
        ["voice", "VOICE", recent(h.events, d.t, "VOICE_LIKE")], ["", "LOUD", recent(h.events, d.t, "LOUD")], ["ble", "BLE", nb]];
      el.querySelector(".cues").innerHTML = counts.map(([c, l, v]) =>
        `<span class="cue ${v ? "on " + c : ""}" title="${l === "BLE" ? "devices heard in the last scan" : l + " in the last " + CUE_S + " s"}">${l} ${v}</span>`).join("");
      const f = [];
      if (n.hops != null) f.push(`${n.hops} hop${n.hops === 1 ? "" : "s"}`);
      if (n.rssi != null) f.push(`${n.rssi} dBm`);
      if (n.age_s != null) f.push(n.age_s < 1.5 ? "now" : `${Math.round(n.age_s)} s`);
      if (n.floor_db) f.push(`floor ${n.floor_db}`);
      el.querySelector(".t-foot").textContent = f.join(" · ");
      spark(el.querySelector(".spark"), h.audio, d.t, colorOf(n.id), n.floor_db);
    }
  }
  function spark(c, audio, now, color, floor) {
    const dpr = window.devicePixelRatio || 1, W = c.clientWidth * dpr, H = c.clientHeight * dpr;
    if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
    const g = c.getContext("2d"); g.clearRect(0, 0, W, H);
    const pts = audio.filter(a => now - a[0] <= 60 && a[1] != null);
    const lo = -45, hi = 0, X = t => (1 - (now - t) / 60) * W, Y = v => H - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo) * H;
    g.fillStyle = "#1f1f1d"; g.fillRect(0, 0, W, H);
    if (floor) { g.strokeStyle = AXIS; g.setLineDash([3 * dpr, 3 * dpr]); g.beginPath(); g.moveTo(0, Y(floor)); g.lineTo(W, Y(floor)); g.stroke(); g.setLineDash([]); }
    if (!pts.length) return;
    g.strokeStyle = color; g.lineWidth = 2 * dpr; g.beginPath();
    pts.forEach((p, i) => (i ? g.lineTo : g.moveTo).call(g, X(p[0]), Y(p[1])));
    g.stroke();
  }

  // ---------------------------------------------------------------- distance matrix
  const mx = echarts.init($("mx"), null, { renderer: "canvas" });
  function matrix(d) {
    const ids = d.matrix.ids, lab = ids.map(i => "N" + i), up = [], lo = [], diag = [];
    ids.forEach((a, i) => ids.forEach((b, j) => {
      if (i === j) diag.push([j, i, "N" + a]);
      else if (j > i) up.push([j, i, d.matrix.metres[i][j]]);
      else lo.push([j, i, d.matrix.dbm[i][j]]);
    }));
    const cell = (data, name, unit) => ({
      type: "heatmap", name, data: data.map(p => ({ value: p, itemStyle: p[2] == null ? { color: "#242422" } : undefined })),
      label: { show: true, color: INK, fontSize: 11, formatter: p => p.value[2] == null ? "–" : p.value[2] + (unit === "m" ? "" : "") },
      itemStyle: { borderColor: SURF, borderWidth: 2, borderRadius: 3 },
      emphasis: { itemStyle: { borderColor: INK } },
    });
    mx.setOption({
      animation: false,
      grid: { left: 34, right: 8, top: 4, bottom: 22 },
      tooltip: {
        formatter: p => p.seriesIndex === 2 ? p.value[2] : `${lab[p.value[1]]} ↔ ${lab[p.value[0]]}: ` +
          (p.value[2] == null ? (p.seriesIndex === 0 ? "position unknown" : "no link") : p.value[2] + (p.seriesIndex === 0 ? " m apart" : " dBm link")),
      },
      xAxis: { type: "category", data: lab, position: "bottom", axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: MUTED } },
      yAxis: { type: "category", data: lab, inverse: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: MUTED } },
      visualMap: [
        { show: false, seriesIndex: 0, min: 0, max: Math.max(4, ...up.map(p => p[2] || 0)), inRange: { color: BLUE } },
        { show: false, seriesIndex: 1, min: -90, max: -20, inRange: { color: ORANGE } }  // weak = light, strong = dark,
      ],
      series: [cell(up, "metres", "m"), cell(lo, "dBm", "dBm"),
        { type: "heatmap", data: diag, label: { show: true, color: MUTED, fontWeight: 700, formatter: p => p.value[2] },
          itemStyle: { color: "transparent" }, silent: true }],
    }, { replaceMerge: ["series"] });
  }

  // ---------------------------------------------------------------- sensor tabs
  const sx = echarts.init($("sx"), null, { renderer: "canvas" });
  document.querySelectorAll("[data-tab]").forEach(b => b.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach(o => o.classList.toggle("on", o === b));
    st.tab = b.dataset.tab; sensors(st.d, true);
  }));
  document.querySelectorAll("[data-tab]").forEach(o => o.classList.toggle("on", o.dataset.tab === st.tab));
  const SHAPE = { TAP_PATTERN: "diamond", VIBRATION: "triangle", VOICE_LIKE: "rect", LOUD: "circle" };
  const fade = id => st.sel == null || st.sel === id ? 1 : 0.25;
  function base(d, yAxis, extra) {
    return Object.assign({
      animation: false,
      grid: { left: 52, right: 140, top: 14, bottom: 26 },
      legend: { type: "scroll", orient: "vertical", right: 6, top: 8, textStyle: { color: INK2, fontSize: 11 }, itemWidth: 14, itemHeight: 8 },
      tooltip: { trigger: "item", backgroundColor: "#232321", borderColor: AXIS, textStyle: { color: INK } },
      xAxis: { type: "value", min: -300, max: 0, interval: 60,  // seconds before now
        axisLabel: { color: MUTED, formatter: v => v === 0 ? "now" : `${v / 60} min` },
        axisLine: { lineStyle: { color: AXIS } }, splitLine: { show: false } },
      yAxis: Object.assign({ axisLabel: { color: MUTED }, splitLine: { lineStyle: { color: GRID } }, axisLine: { show: false } }, yAxis),
    }, extra);
  }
  function sensors(d) {
    if (!d) return;
    const ids = d.nodes.map(n => n.id).filter(i => d.history[i]);
    const H = i => d.history[i] || { audio: [], events: [], ble: [] };
    let opt, note = "";
    if (st.tab === "audio") {
      note = "sound level per node (dBFS, 1 s) · markers: ◆ tap pattern  ▲ felt  ■ sustained  ● loud";
      const lines = ids.map(i => ({
        name: "N" + i, type: "line", showSymbol: false, step: false, color: colorOf(i),
        lineStyle: { width: st.sel === i ? 3 : 2, opacity: fade(i) }, z: 2,
        data: H(i).audio.filter(a => a[1] != null).map(a => [a[0] - d.t, a[1]]),
        tooltip: { formatter: p => `N${i} · ${p.value[1]} dBFS` },
      }));
      const marks = Object.keys(SHAPE).map(k => ({
        name: KIND[k], type: "scatter", symbol: SHAPE[k], symbolSize: k === "LOUD" ? 6 : 10, z: 3,
        itemStyle: { borderColor: SURF, borderWidth: 1, color: MUTED },
        data: ids.flatMap(i => H(i).events.filter(e => e[1] === k && e[2] != null).map(e => ({
          value: [e[0] - d.t, e[2], i, e[3], e[4]], itemStyle: { color: colorOf(i), opacity: fade(i) } }))),
        tooltip: { formatter: p => `N${p.value[2]} · ${KIND[k]} · peak ${p.value[1]} dBFS · ×${p.value[3]} · conf ${p.value[4]}` },
      }));
      opt = base(d, { type: "value", min: -50, max: 0 }, { series: lines.concat(marks) });
    } else if (st.tab === "vib") {
      note = "SW-420 vibration per node · dot size = switch edges (strength) · ◆ tap pattern";
      const lanes = ids.map(i => "N" + i);
      const pts = (kind) => ids.flatMap(i => H(i).events.filter(e => e[1] === kind).map(e => ({
        value: [e[0] - d.t, "N" + i, e[3] || 1, e[4]], itemStyle: { color: colorOf(i), opacity: fade(i) } })));
      opt = base(d, { type: "category", data: lanes, inverse: true, splitLine: { show: true, lineStyle: { color: GRID } } }, {
        legend: { show: false },
        grid: { left: 52, right: 24, top: 14, bottom: 26 },
        series: [
          { name: "FELT", type: "scatter", data: pts("VIBRATION"), symbol: "circle",
            symbolSize: v => Math.min(34, 7 + Math.sqrt(v[2]) * 3), itemStyle: { borderColor: SURF, borderWidth: 1 },
            tooltip: { formatter: p => `${p.value[1]} · felt · ${p.value[2]} edges · conf ${p.value[3]}` } },
          { name: "TAP", type: "scatter", data: pts("TAP_PATTERN"), symbol: "diamond", symbolSize: 13,
            itemStyle: { borderColor: "#fff", borderWidth: 1.5 },
            tooltip: { formatter: p => `${p.value[1]} · tap pattern ×${p.value[2]} · conf ${p.value[3]}` } },
        ],
      });
    } else {
      note = "phones / wearables heard per node per scan (hashed, receive-only, max 20) · hover for strongest dBm and kinds";
      opt = base(d, { type: "value", min: 0, minInterval: 1 }, {
        series: ids.map(i => ({
          name: "N" + i, type: "line", step: "end", showSymbol: true, symbolSize: 5, color: colorOf(i),
          lineStyle: { width: st.sel === i ? 3 : 2, opacity: fade(i) }, itemStyle: { opacity: fade(i) },
          data: H(i).ble.map(b => [b[0] - d.t, b[1], b[2], b[3]]),
          tooltip: { formatter: p => `N${i} · ${p.value[1]} devices · strongest ${p.value[2] ?? "–"} dBm<br>` +
            Object.entries(p.value[3] || {}).map(([k, v]) => `${k} ${v}`).join(" · ") },
        })),
      });
    }
    $("tabnote").textContent = note;
    sx.setOption(opt, { notMerge: true });
  }

  // ---------------------------------------------------------------- fleet / matrix splitter (remembered per browser)
  const mainEl = document.querySelector("main"), fleetEl = $("fleet");
  function setFleetH(px) {
    if (px == null) { mainEl.style.removeProperty("--fleet-h"); mainEl.classList.remove("sized"); }
    else { mainEl.style.setProperty("--fleet-h", px + "px"); mainEl.classList.add("sized"); }
    mx.resize();
  }
  try { const v = +localStorage.getItem("t10_fleet_h"); if (v) setFleetH(v); } catch (e) { /* no storage */ }
  $("split").addEventListener("pointerdown", e => {
    e.preventDefault();
    const top = fleetEl.getBoundingClientRect().top, mapB = $("map").getBoundingClientRect().bottom;
    document.body.classList.add("dragging");
    const move = ev => setFleetH(Math.round(Math.max(90, Math.min(ev.clientY - top, mapB - top - 160))));
    const up = () => {
      document.body.classList.remove("dragging");
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      try { localStorage.setItem("t10_fleet_h", parseInt(mainEl.style.getPropertyValue("--fleet-h")) || ""); } catch (e) { /* ignore */ }
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  });
  $("split").addEventListener("dblclick", () => { setFleetH(null); try { localStorage.removeItem("t10_fleet_h"); } catch (e) { /* ignore */ } });

  window.addEventListener("resize", () => { mx.resize(); sx.resize(); drawMap(); if (st.d) tiles(st.d, true); });
})();
