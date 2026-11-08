/* Evidence review for the fusion snapshot.
   WebSocket messages are full snapshots, not an event log.
   The chart uses host-receipt time. Node t_ms is not synchronized. */
(function (factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.Review = api;
})(function () {
  var ACOUSTIC = { LOUD: true, TAP_PATTERN: true, VOICE_LIKE: true, VIBRATION: true };
  var LABELS = {
    TAP_PATTERN: "Tap pattern",
    LOUD: "Loud sound",
    VOICE_LIKE: "Sustained sound",
    VIBRATION: "Felt vibration",
    RADAR_PRESENCE: "Radar presence",
    GAS: "Gas",
    BLE_APPLE: "Apple BLE advertisement",
    BLE_OTHER: "Other BLE advertisement",
    BLE_FINDMY: "Find My advertisement",
    BLE_GOOGLE: "Google BLE advertisement",
    WIFI_PROBE: "Wi-Fi probe"
  };
  var RECENT_WINDOW_MS = 3 * 60 * 1000;

  function readableKind(kind) {
    if (!kind) return "Unnamed event";
    return LABELS[kind] || String(kind);
  }

  function shown(value, suffix) {
    if (value === null || value === undefined || value === "") return "Not reported";
    return suffix ? String(value) + suffix : String(value);
  }

  function formatAge(ms) {
    if (!Number.isFinite(ms) || ms < 0) return "Unknown";
    if (ms < 1000) return "under 1 s";
    var seconds = Math.floor(ms / 1000);
    if (seconds < 60) return seconds + " s";
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + " min " + (seconds % 60) + " s";
    var hours = Math.floor(minutes / 60);
    return hours + " h " + (minutes % 60) + " min";
  }

  function formatClock(ms) {
    if (!Number.isFinite(ms)) return "Unknown";
    var date = new Date(ms);
    if (Number.isNaN(date.getTime())) return "Unknown";
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function cueKey(nodeId, evidence) {
    return "cue:" + nodeId + ":" + (evidence.kind || "unknown") + ":" + evidence.t_ms + ":" + evidence.t_host;
  }

  function deviceKey(device) {
    return "device:" + (device.hash || "unknown") + ":" + device.heard_by;
  }

  function nodeKey(id) {
    return "node:" + id;
  }

  function familyOf(kind) {
    return ACOUSTIC[kind] ? "acoustic" : "other";
  }

  function shapeOf(family) {
    if (family === "acoustic") return "circle";
    if (family === "radio") return "triangle";
    return "square";
  }

  function countText(value) {
    if (value === null || value === undefined || value === "") return "Not reported";
    return "Reported count " + value;
  }

  function confText(value) {
    if (value === null || value === undefined || value === "") return "Not reported";
    return String(value) + " (unsigned integer, scale unknown, not a calibrated probability)";
  }

  function countMeaning(kind, value) {
    if (value === null || value === undefined || value === "") return "Not reported";
    if (kind === "TAP_PATTERN") return "Reported count " + value + " (pattern edges, not a person count)";
    if (kind === "VIBRATION") return "Reported count " + value + " (SW-420 edges, not an accelerometer)";
    if (kind === "VOICE_LIKE") return "Reported count " + value + " (duration in 100 ms steps, not a person count)";
    if (kind === "LOUD") return "Reported count " + value + " (detector count, not a person count)";
    return "Reported count " + value + " (kind unclassified or unknown scale, not a person count)";
  }

  function measurementText(value, status, suffix, unimplemented) {
    if (status === "unimplemented") return unimplemented || "Not measured";
    if (status === "unavailable") return "Unavailable";
    if (status === "absent" || value === null || value === undefined || value === "") return "Not reported";
    return suffix ? String(value) + suffix : String(value);
  }

  function peakText(row) {
    if (!row) return "Not reported";
    if (row.peakDbStatus === "unavailable" || row.peakDb === -128) return "Unavailable";
    if (row.kind === "VIBRATION" || row.kindStatus === "unclassified") {
      return shown(row.peakDb, " dB") + " (reported integer, not a confirmed heard peak)";
    }
    return shown(row.peakDb, " dBFS");
  }

  function voiceText(row) {
    if (!row) return "Not reported";
    if (row.voiceDbStatus === "unavailable" || row.voiceDb === -128) return "Unavailable";
    if (row.kind === "VOICE_LIKE") {
      return shown(row.voiceDb, " dBFS") + " (average level, not a voice-band energy, not confirmed speech)";
    }
    return shown(row.voiceDb, " dBFS");
  }

  function kindNote(kind) {
    if (kind === "LOUD") return "Loud sound. Not a person.";
    if (kind === "VOICE_LIKE") return "Sustained sound. Not confirmed speech.";
    if (kind === "VIBRATION") return "SW-420 vibration. Not an accelerometer.";
    if (kind === "TAP_PATTERN") return "Tap pattern. Not a person count.";
    return "Unclassified event. Original kind kept. Not a confirmed detection.";
  }

  function reusePlan(previousKeys, nextKeys) {
    var prev = {};
    (previousKeys || []).forEach(function (key) { prev[key] = true; });
    var kept = [];
    var inserted = [];
    (nextKeys || []).forEach(function (key) {
      if (prev[key]) kept.push(key);
      else inserted.push(key);
    });
    return { kept: kept, inserted: inserted, replaced: 0 };
  }

  function collectObservations(msg) {
    var rows = [];
    (msg && msg.nodes || []).forEach(function (node) {
      (node.evidence || []).forEach(function (evidence) {
        var family = familyOf(evidence.kind);
        rows.push({
          key: cueKey(node.id, evidence),
          family: family,
          shape: shapeOf(family),
          kind: evidence.kind || "",
          label: readableKind(evidence.kind),
          sensorId: node.id,
          sensorStatus: node.status || "",
          sensorLast: node.last_t_host,
          tHost: evidence.t_host,
          tMs: evidence.t_ms,
          count: evidence.count,
          conf: evidence.conf,
          peakDb: evidence.peak_db,
          peakDbStatus: evidence.peak_db_status,
          voiceDb: evidence.voice_db,
          voiceDbStatus: evidence.voice_db_status,
          kindStatus: evidence.kind_status || "known",
          tRecordedS: evidence.t_recorded_s,
          tIngestMs: evidence.t_ingest_ms,
          seq: evidence.seq,
          hops: evidence.hops,
          rssi: evidence.rssi_last,
          storeId: evidence.store_id,
          historical: false
        });
      });
    });
    (msg && msg.devices || []).forEach(function (device) {
      var heard = (msg.nodes || []).find(function (node) { return node.id === device.heard_by; });
      rows.push({
        key: deviceKey(device),
        family: "radio",
        shape: "triangle",
        kind: device.kind || "",
        label: readableKind(device.kind),
        sensorId: device.heard_by,
        sensorStatus: heard ? heard.status || "" : "",
        sensorLast: heard ? heard.last_t_host : null,
        tHost: device.t_host,
        tMs: device.t_ms,
        count: device.count,
        conf: null,
        hash: device.hash,
        rssi: device.rssi_max
      });
    });
    return rows;
  }

  function replaceHistory(snapshot) {
    return collectObservations(snapshot);
  }

  function mostRecent(rows) {
    var best = null;
    rows.forEach(function (row) {
      if (!Number.isFinite(row.tHost)) return;
      if (!best || row.tHost > best.tHost || (row.tHost === best.tHost && String(row.key) < String(best.key))) {
        best = row;
      }
    });
    return best;
  }

  function chooseSelection(state, observations) {
    var keys = {};
    observations.forEach(function (row) { keys[row.key] = true; });
    if (state.userChose) {
      return { selectedKey: state.selectedKey, userChose: true, reason: "keep-user" };
    }
    if (state.selectedKey && keys[state.selectedKey]) {
      return { selectedKey: state.selectedKey, userChose: false, reason: "keep-auto" };
    }
    var acoustic = observations.filter(function (row) { return row.family === "acoustic"; });
    var pick = mostRecent(acoustic) || mostRecent(observations);
    if (!pick) return { selectedKey: null, userChose: false, reason: "empty" };
    return { selectedKey: pick.key, userChose: false, reason: "auto" };
  }

  function passesFilter(row, filter) {
    if (filter === "cues") return row.family === "acoustic";
    if (filter === "devices") return row.family === "radio";
    if (filter === "stale") return row.sensorStatus === "inactive";
    return true;
  }

  function chartWindow(observations, mode, now, selectedKey, allowFallback) {
    var timed = observations.filter(function (row) { return Number.isFinite(row.tHost); });
    var end = Number.isFinite(now) ? now : null;
    var start = null;
    var effective = mode === "retained" ? "retained" : "recent";
    var note = "";
    if (!timed.length || end === null) {
      return {
        points: [],
        start: null,
        end: end,
        effective: effective,
        outside: false,
        label: "No retained observations in this snapshot.",
        padded: false
      };
    }
    if (effective === "recent") {
      start = end - RECENT_WINDOW_MS;
      var recent = timed.filter(function (row) { return row.tHost >= start && row.tHost <= end; });
      if (!recent.length && allowFallback !== false) {
        effective = "retained";
        note = "Last 3 min has no retained observations. Showing the retained span.";
      }
    }
    if (effective === "retained") {
      start = timed.reduce(function (min, row) { return Math.min(min, row.tHost); }, timed[0].tHost);
    }
    var padded = false;
    var axisStart = start;
    var axisEnd = end;
    if (axisEnd - axisStart < 1000) {
      axisStart -= 30000;
      axisEnd += 30000;
      padded = true;
    }
    var points = timed.filter(function (row) { return row.tHost >= start && row.tHost <= end; });
    var selected = null;
    timed.forEach(function (row) { if (row.key === selectedKey) selected = row; });
    var outside = Boolean(selected && (selected.tHost < start || selected.tHost > end));
    var label = "Window " + formatClock(start) + "–" + formatClock(end) + " host-receipt time";
    label += effective === "recent" ? " (last 3 min)." : " (retained span, not a complete packet log).";
    if (note) label = note + " " + label;
    if (padded) label += " Axis padded so one point stays visible.";
    return {
      points: points,
      start: axisStart,
      end: axisEnd,
      dataStart: start,
      dataEnd: end,
      effective: effective,
      outside: outside,
      label: label,
      padded: padded
    };
  }

  function resetLanded(watch, snapshot, observations) {
    if (!watch) return false;
    var packets = snapshot && snapshot.counts ? snapshot.counts.packets : null;
    if (Number.isFinite(packets) && packets < watch.packets) return true;
    if (Number.isFinite(packets) && watch.packets > 0 && packets === 0) return true;
    var keys = {};
    (observations || []).forEach(function (row) { keys[row.key] = true; });
    var previous = watch.keys || [];
    if (previous.length && previous.every(function (key) { return !keys[key]; }) && Number.isFinite(packets) && packets <= watch.packets) {
      return true;
    }
    return false;
  }

  function evidenceAgeMs(row, now) {
    if (!row || !Number.isFinite(row.tHost) || !Number.isFinite(now)) return null;
    return now - row.tHost;
  }

  function sensorAgeMs(row, now) {
    if (!row || !Number.isFinite(row.sensorLast) || !Number.isFinite(now)) return null;
    return now - row.sensorLast;
  }

  function ageLabel(ms, socketState) {
    var label = formatAge(ms);
    if (label === "Unknown") return label;
    return socketState === "connected" ? label : label + " · cached";
  }

  function sensorWords(status, socketState) {
    if (socketState !== "connected") return { label: "Not live", tone: "fail" };
    if (status === "active") return { label: "Reporting", tone: "ok" };
    if (status === "inactive") return { label: "Stale", tone: "stale" };
    if (!status) return { label: "Unknown", tone: "stale" };
    return { label: String(status), tone: "stale" };
  }

  function provenanceMode(msg) {
    if (!msg || (msg.simulated !== true && msg.simulated !== false)) return null;
    if (msg.source === "recording" || msg.source === "simulation" || msg.source === "live") return msg.source;
    return msg.simulated ? "simulation" : "live";
  }

  function sourceLabel(msg, socketState) {
    var mode = provenanceMode(msg);
    if (!mode) return { text: "Unknown", mode: "unknown" };
    var text = mode === "recording" ? "RECORDING" : mode === "simulation" ? "SIMULATION" : "LIVE";
    var link = msg && msg.link;
    if (mode === "live" && link) {
      if (link.transport === "serial") text = link.connected === false ? "LIVE · serial closed" : "LIVE · USB serial";
      else if (link.transport === "tcp") text = link.connected === false ? "LIVE · TCP closed" : "LIVE · TCP";
      else if (link.transport) text = "LIVE · " + link.transport;
    }
    if (link && link.connected === false && link.last_error) text += " · link down";
    if (socketState !== "connected") text += " · last snapshot";
    return { text: text, mode: mode };
  }

  function sensorSummary(msg, socketState) {
    if (socketState !== "connected") return { text: "Not live", tone: "fail" };
    var counts = (msg && msg.counts) || {};
    if (!Number.isFinite(counts.nodes_active) || !Number.isFinite(counts.nodes_seen)) {
      return { text: "Unknown", tone: "unknown" };
    }
    var stale = counts.nodes_seen - counts.nodes_active;
    var tone = counts.nodes_active > 0 ? "ok" : "stale";
    return {
      text: counts.nodes_active + " reporting · " + stale + " stale",
      tone: tone
    };
  }

  function runNote(state, msg, observations) {
    if (state.replayError) return state.replayError;
    if (state.replayWatch) return "Restart requested. These rows are still the previous demo run.";
    if (state.cleared) return "Current demo run. The host cleared the previous retained observations. Waiting for the scripted baseline.";
    if (!msg) return "No snapshot yet.";
    if (msg.source === "recording") {
      var ended = msg.playback && msg.playback.status === "ended";
      return ended
        ? "Recording ended. These rows are captured gateway lines, not a live board."
        : "Recording playback. These rows are captured gateway lines, not a live board and not the simulated script.";
    }
    if (msg.simulated === false) {
      return "Live gateway session. Replay will not clear this history.";
    }
    if (msg.simulated !== true) return "Source unknown. Replay status is not confirmed.";
    var acoustic = observations.filter(function (row) { return row.family === "acoustic" && Number.isFinite(row.tHost); });
    var oldest = acoustic.reduce(function (min, row) { return Math.min(min, row.tHost); }, acoustic.length ? acoustic[0].tHost : null);
    var age = Number.isFinite(oldest) ? formatAge(msg.t_host - oldest) : "none";
    return "Current demo run. Oldest acoustic evidence " + age + " (host-receipt). Replay clears demo retention through ingest and does not send a hardware command.";
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function socketUrl() {
    if (typeof location === "undefined" || location.protocol === "file:" || !location.host) return null;
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + "/ws";
  }

  function start(doc) {
    var state = {
      latest: null,
      observations: [],
      socketState: "connecting",
      selectedKey: null,
      userChose: false,
      pinned: {},
      holdRender: false,
      pendingSnapshot: null,
      lastMessageAt: 0,
      filter: "all",
      windowMode: "recent",
      windowPinned: false,
      replayWatch: null,
      cleared: false,
      replayError: "",
      ignoredVersion: 0,
      socket: null,
      retryTimer: null,
      chart: null,
      reduced: false
    };
    if (typeof window !== "undefined" && window.matchMedia) {
      state.reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    }
    bind(doc, state);
    var socketNode = doc.getElementById("diag-socket");
    if (socketNode) socketNode.textContent = socketUrl() || "Unknown";
    refreshReplay(doc, state);
    refreshHistory(doc);
    if (typeof location !== "undefined" && location.protocol === "file:") {
      setSocket(doc, state, "disconnected");
      setRun(doc, "Open this page from the fusion host. A file URL has no server.");
    } else {
      connect(doc, state);
    }
    if (typeof window !== "undefined") {
      window.addEventListener("resize", function () {
        if (state.chart) state.chart.resize();
      });
      state.staleTimer = window.setInterval(function () {
        if (state.socketState === "connected" && state.lastMessageAt && Date.now() - state.lastMessageAt > 2500) {
          setSocket(doc, state, "stale");
          if (state.latest) render(doc, state);
        }
      }, 500);
    }
    return state;
  }

  function bind(doc, state) {
    doc.querySelectorAll("[data-filter]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.filter = button.dataset.filter;
        doc.querySelectorAll("[data-filter]").forEach(function (item) {
          item.setAttribute("aria-pressed", String(item === button));
        });
        render(doc, state);
      });
    });
    doc.querySelectorAll("[data-window]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.windowMode = button.dataset.window;
        state.windowPinned = true;
        doc.querySelectorAll("[data-window]").forEach(function (item) {
          item.setAttribute("aria-pressed", String(item === button));
        });
        render(doc, state);
      });
    });
    var replay = doc.getElementById("replay");
    if (replay) replay.addEventListener("click", function () { replayDemo(doc, state); });
    function hold(event) {
      var target = event.target && event.target.closest ? event.target.closest("#queue, #roster, #marks, #detail, #diagnostics") : null;
      if (!target) return;
      state.holdRender = true;
    }
    function release() {
      if (!state.holdRender) return;
      state.holdRender = false;
      if (state.pendingSnapshot) {
        var msg = state.pendingSnapshot;
        state.pendingSnapshot = null;
        onSnapshot(doc, state, msg);
      }
    }
    doc.addEventListener("pointerdown", hold, true);
    doc.addEventListener("mousedown", hold, true);
    doc.addEventListener("pointerup", release, true);
    doc.addEventListener("pointercancel", release, true);
    doc.addEventListener("mouseup", release, true);
  }

  function setSocket(doc, state, next) {
    state.socketState = next;
    var labels = { connecting: "Connecting", connected: "Connected", reconnecting: "Reconnecting", disconnected: "Disconnected", stale: "Stale" };
    var node = doc.getElementById("conn");
    if (!node) return;
    node.textContent = labels[next] || "Unknown";
    node.dataset.state = next;
  }

  function setRun(doc, text) {
    var note = doc.getElementById("run-note");
    if (note && note.textContent !== text) note.textContent = text;
  }

  function el(doc, tag, className, text) {
    var node = doc.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function icon(doc, name) {
    var node = el(doc, "span", "icon icon-" + name);
    node.setAttribute("aria-hidden", "true");
    return node;
  }

  function select(doc, state, key, fromUser) {
    if (fromUser) state.userChose = true;
    state.selectedKey = key;
    render(doc, state);
    if (fromUser) {
      var selected = doc.querySelector("[data-key=\"" + CSS.escape(key) + "\"]");
      if (selected) selected.focus();
    }
  }

  function onSnapshot(doc, state, msg) {
    if (state.holdRender) {
      state.pendingSnapshot = msg;
      return;
    }
    var observations = collectObservations(msg);
    state.pinned = state.pinned || {};
    observations.forEach(function (row) { state.pinned[row.key] = row; });
    if (state.replayWatch && resetLanded(state.replayWatch, msg, observations)) {
      state.replayWatch = null;
      state.cleared = observations.length === 0;
      state.replayError = "";
    } else if (state.cleared && observations.length) {
      state.cleared = false;
    }
    var choice = chooseSelection(state, observations);
    state.selectedKey = choice.selectedKey;
    state.userChose = choice.userChose;
    state.latest = msg;
    state.observations = observations;
    render(doc, state);
  }

  function render(doc, state) {
    var msg = state.latest;
    if (!msg) return;
    paintStatus(doc, state, msg);
    paintQueue(doc, state, msg);
    paintRoster(doc, state, msg);
    paintDetail(doc, state, msg);
    paintTimeline(doc, state, msg);
    paintDiagnostics(doc, state, msg);
    setRun(doc, runNote(state, msg, state.observations));
  }

  function paintStatus(doc, state, msg) {
    var source = sourceLabel(msg, state.socketState);
    var sourceNode = doc.getElementById("source");
    sourceNode.textContent = source.text;
    sourceNode.dataset.mode = source.mode;
    var sensors = sensorSummary(msg, state.socketState);
    var sensorNode = doc.getElementById("sensors");
    sensorNode.textContent = sensors.text;
    sensorNode.dataset.tone = sensors.tone;
    var loc = doc.getElementById("loc");
    if (!msg.localization_mode) loc.textContent = "Unknown";
    else if (msg.localization_mode === "UNLOCALIZED") loc.textContent = "Unavailable";
    else loc.textContent = String(msg.localization_mode);
    var tak = doc.getElementById("tak");
    if (tak) tak.textContent = "Not implemented";
    var counts = msg.counts || {};
    doc.getElementById("cue-count").textContent = msg.banner && Number.isFinite(msg.banner.possible_acoustic) ? String(msg.banner.possible_acoustic) : "Unknown";
    doc.getElementById("reporting").textContent = Number.isFinite(counts.nodes_active) && Number.isFinite(counts.nodes_seen)
      ? counts.nodes_active + " of " + counts.nodes_seen
      : "Unknown";
    doc.getElementById("event-count").textContent = Number.isFinite(counts.acoustic_events) ? String(counts.acoustic_events) : "Unknown";
    var stored = doc.getElementById("stored-count");
    if (stored) stored.textContent = Number.isFinite(counts.stored_observations) ? String(counts.stored_observations) + " historical" : "Not writing";
    var times = (msg.nodes || []).map(function (node) { return node.last_t_host; }).filter(function (value) { return Number.isFinite(value); });
    doc.getElementById("latest-age").textContent = times.length ? ageLabel(msg.t_host - Math.max.apply(null, times), state.socketState) : "Unknown";
  }

  function filtered(state) {
    return state.observations.filter(function (row) { return passesFilter(row, state.filter); });
  }

  function syncList(container, rows, paint, emptyText) {
    var doc = container.ownerDocument;
    var existing = {};
    Array.prototype.forEach.call(container.children, function (child) {
      if (child.dataset && child.dataset.key) existing[child.dataset.key] = child;
    });
    var wanted = {};
    rows.forEach(function (row) { wanted[row.key] = true; });
    Object.keys(existing).forEach(function (key) {
      if (!wanted[key]) existing[key].remove();
    });
    var empty = null;
    Array.prototype.forEach.call(container.children, function (child) {
      if (child.classList && child.classList.contains("empty")) empty = child;
    });
    if (!rows.length) {
      if (!empty) container.append(el(doc, "p", "empty", emptyText));
      else empty.textContent = emptyText;
      return;
    }
    if (empty) empty.remove();
    rows.forEach(function (row, index) {
      var node = existing[row.key];
      if (!node) {
        node = paint(row, null);
        node.dataset.key = row.key;
      } else {
        paint(row, node);
      }
      var current = container.children[index];
      if (current !== node) container.insertBefore(node, current || null);
    });
  }

  function rowButton(doc, state, row, button) {
    if (!button) {
      button = doc.createElement("button");
      button.type = "button";
      button.dataset.key = row.key;
      button.addEventListener("click", function () { select(doc, state, button.dataset.key, true); });
    }
    button.className = "list-group-item list-group-item-action evidence-row" + (state.selectedKey === row.key ? " is-selected" : "");
    button.setAttribute("aria-pressed", String(state.selectedKey === row.key));
    var sensor = sensorWords(row.sensorStatus, state.socketState);
    var evidenceAge = ageLabel(evidenceAgeMs(row, state.latest.t_host), state.socketState);
    var historical = row.historical ? "stored history, not a new live detection" : row.sensorStatus === "inactive" ? "historical, sensor stale" : "sensor " + sensor.label.toLowerCase();
    var note = kindNote(row.kind);
    button.replaceChildren(
      icon(doc, row.family === "radio" ? "antenna" : row.family === "acoustic" ? "ear" : "point"),
      (function () {
        var copy = el(doc, "span", "row-copy");
        copy.append(el(doc, "span", "row-title", row.label));
        copy.append(el(doc, "span", "row-meta", "Node " + shown(row.sensorId) + " · evidence " + evidenceAge + " · " + historical + " · " + note));
        if (state.selectedKey === row.key) copy.append(el(doc, "span", "flag selected", "Selected"));
        return copy;
      })()
    );
    return button;
  }

  function paintQueue(doc, state, msg) {
    var rows = filtered(state).slice().sort(function (a, b) {
      var rank = { acoustic: 0, other: 1, radio: 2 };
      var left = Object.prototype.hasOwnProperty.call(rank, a.family) ? rank[a.family] : 9;
      var right = Object.prototype.hasOwnProperty.call(rank, b.family) ? rank[b.family] : 9;
      var byFamily = left - right;
      if (byFamily) return byFamily;
      return (b.tHost || 0) - (a.tHost || 0);
    });
    var waiting = !(msg.nodes || []).length && !(msg.devices || []).length;
    syncList(
      doc.getElementById("queue"),
      rows,
      function (row, existing) { return rowButton(doc, state, row, existing); },
      waiting ? "Waiting for a gateway line. No sensors have reported to this host." : "Nothing matches this filter."
    );
  }

  function paintRoster(doc, state, msg) {
    var cards = (msg.nodes || []).filter(function (node) {
      if (state.filter === "cues" && node.search_priority !== "elevated") return false;
      if (state.filter === "stale" && node.status !== "inactive") return false;
      if (state.filter === "devices" && !state.observations.some(function (row) { return row.family === "radio" && row.sensorId === node.id; })) return false;
      return true;
    }).map(function (node) {
      return { key: nodeKey(node.id), node: node };
    });
    syncList(doc.getElementById("roster"), cards, function (item, existing) {
      var node = item.node;
      var key = item.key;
      var button = existing;
      if (!button) {
        button = doc.createElement("button");
        button.type = "button";
        button.dataset.key = key;
        button.addEventListener("click", function () { select(doc, state, button.dataset.key, true); });
      }
      var related = state.observations.some(function (row) { return row.key === state.selectedKey && row.sensorId === node.id; });
      button.className = "btn sensor-card" + (state.selectedKey === key ? " is-selected" : "");
      button.setAttribute("aria-pressed", String(state.selectedKey === key));
      var report = sensorWords(node.status, state.socketState);
      var cue = node.search_priority === "elevated" ? "Fresh cue" : node.search_priority === "stale" ? "Cue is stale" : "No acoustic cue";
      var copy = el(doc, "span", "card-copy");
      copy.append(el(doc, "span", "card-title", "Node " + node.id));
      copy.append(el(doc, "span", "flag " + report.tone, report.label));
      copy.append(el(doc, "span", "card-meta", cue + " · last line " + ageLabel(Number.isFinite(node.last_t_host) ? msg.t_host - node.last_t_host : null, state.socketState)));
      if (state.selectedKey === key) copy.append(el(doc, "span", "flag selected", "Selected"));
      else if (related) copy.append(el(doc, "span", "flag selected", "Selected cue's sensor"));
      button.replaceChildren(icon(doc, "radio"), copy);
      return button;
    }, (msg.nodes || []).length ? "No sensors match this filter." : "No sensors observed yet.");
  }

  function fact(doc, list, name, value) {
    list.append(el(doc, "dt", "", name), el(doc, "dd", "", value));
  }

  function clean(value) {
    if (Array.isArray(value)) return value.map(clean);
    if (!value || typeof value !== "object") return value === null ? "Not reported" : value;
    var copy = {};
    Object.keys(value).forEach(function (key) {
      copy[key] = value[key] === null || value[key] === undefined ? "Not reported" : clean(value[key]);
    });
    return copy;
  }

  function findNode(msg, id) {
    return (msg.nodes || []).find(function (node) { return node.id === id; }) || null;
  }

  function paintDetail(doc, state, msg) {
    var empty = doc.getElementById("detail-empty");
    var body = doc.getElementById("detail-body");
    var key = state.selectedKey;
    if (!key) {
      empty.hidden = false;
      empty.textContent = "Waiting for a retained observation.";
      body.hidden = true;
      return;
    }
    if (key.indexOf("node:") === 0) {
      var node = findNode(msg, Number(key.slice(5)));
      if (!node) {
        empty.hidden = false;
        empty.textContent = state.userChose
          ? "That sensor is no longer in the retained snapshot. Viewing it was not an acknowledgment."
          : "Waiting for a retained observation.";
        body.hidden = true;
        return;
      }
      paintNodeDetail(doc, state, msg, node);
      return;
    }
    var row = null;
    var fromLive = false;
    state.observations.forEach(function (item) { if (item.key === key) row = item; });
    if (row) fromLive = true;
    if (!row && state.pinned && state.pinned[key]) {
      row = state.pinned[key];
    }
    if (!row) {
      empty.hidden = false;
      empty.textContent = state.userChose
        ? "That evidence is not in the live list. Stored history can still be opened from Diagnostics. Viewing it was not an acknowledgment."
        : "Waiting for a retained observation.";
      body.hidden = true;
      return;
    }
    empty.hidden = true;
    body.hidden = false;
    var facts = doc.getElementById("detail-facts");
    facts.replaceChildren();
    var sensor = sensorWords(row.sensorStatus, state.socketState);
    doc.getElementById("detail-kicker").textContent = row.family === "radio" ? "Radio evidence" : row.family === "acoustic" ? "Acoustic evidence" : "Stored event";
    doc.getElementById("detail-name").textContent = row.label;
    fact(doc, facts, "Raw event", (row.kind || "Not reported") + (row.kindStatus === "unclassified" ? " (unclassified)" : ""));
    fact(doc, facts, "Sensor", "Node " + shown(row.sensorId));
    fact(doc, facts, "Sensor reporting", sensor.label + " (reporting is not a detection)");
    fact(doc, facts, "Sensor last line", ageLabel(sensorAgeMs(row, msg.t_host), state.socketState));
    fact(doc, facts, "Evidence age", ageLabel(evidenceAgeMs(row, msg.t_host), state.socketState));
    fact(doc, facts, "Time basis", timeBasis(row, msg));
    fact(doc, facts, "Reported count", countMeaning(row.kind, row.count));
    if (row.family !== "radio") fact(doc, facts, "Detector score", confText(row.conf));
    if (row.seq != null) fact(doc, facts, "Sequence", shown(row.seq));
    if (row.hops != null) fact(doc, facts, "Hops", row.hops === 0 ? "0 (received directly, not a relay test)" : shown(row.hops));
    if (row.family === "radio") {
      fact(doc, facts, "Hash", shown(row.hash));
      fact(doc, facts, "RSSI", shown(row.rssi, " dBm"));
    } else {
      fact(doc, facts, "Peak", peakText(row));
      fact(doc, facts, "Voice level", voiceText(row));
    }
    fact(doc, facts, "Position", "Not reported");
    doc.getElementById("detail-observed").textContent = row.family === "radio"
      ? "Radio evidence of a hashed advertisement heard by Node " + shown(row.sensorId) + ". Not a person, a name, or a location."
      : kindNote(row.kind) + " Node " + shown(row.sensorId) + " reported this detector event. It is not a person and not a dig location.";
    doc.getElementById("detail-limit").textContent = !fromLive
      ? "This row is no longer in the live list. It stays inspectable. It is not a new live detection. A score is not a calibrated probability."
      : row.sensorStatus === "inactive"
      ? "The sensor is stale and the evidence is still on screen. Inactive does not mean cleared or safe. A score is not a calibrated probability."
      : "A score is an unsigned integer with an unknown scale. It is not a calibrated probability. This page does not acknowledge or resolve evidence.";
    doc.getElementById("detail-raw").textContent = JSON.stringify(clean(row), null, 2);
  }

  function paintNodeDetail(doc, state, msg, node) {
    doc.getElementById("detail-empty").hidden = true;
    doc.getElementById("detail-body").hidden = false;
    var facts = doc.getElementById("detail-facts");
    facts.replaceChildren();
    var report = sensorWords(node.status, state.socketState);
    doc.getElementById("detail-kicker").textContent = "Sensor";
    doc.getElementById("detail-name").textContent = "Node " + node.id;
    fact(doc, facts, "Reporting", report.label);
    fact(doc, facts, "Last line", ageLabel(Number.isFinite(node.last_t_host) ? msg.t_host - node.last_t_host : null, state.socketState));
    fact(doc, facts, "Acoustic cue", node.search_priority === "elevated" ? "Fresh cue" : node.search_priority === "stale" ? "Stale cue" : "No acoustic cue");
    fact(doc, facts, "Position", node.position == null ? "Not reported" : "Reported " + JSON.stringify(node.position) + ". Not a measured dig point.");
    fact(doc, facts, "Battery", measurementText(node.batt_mv, node.batt_mv_status, " mV", "Not measured"));
    fact(doc, facts, "Floor", measurementText(node.floor_db, node.floor_db_status, " dBFS", "Not measured (pre-warmup or not implemented)"));
    var evidence = state.observations.filter(function (row) { return row.sensorId === node.id; });
    doc.getElementById("detail-observed").textContent = evidence.length
      ? "Retained for this sensor: " + evidence.map(function (row) { return row.label; }).join(", ") + ". Open a queue row for one event. This card is not a location."
      : "No acoustic or radio evidence retained for this sensor.";
    doc.getElementById("detail-limit").textContent = node.status === "inactive"
      ? "Stale means this sensor stopped reporting. It does not mean the evidence was cleared or that the area is safe."
      : "Reporting means a line arrived inside the stale window. It does not refresh another sensor's evidence.";
    doc.getElementById("detail-raw").textContent = JSON.stringify(clean(node), null, 2);
  }

  function timeBasis(row, msg) {
    var device = "Node clock t_ms " + shown(row.tMs) + " is not synchronized across sensors.";
    var ingest = "Host ingestion " + formatClock(row.tIngestMs || row.tHost) + ".";
    if (Number.isFinite(row.tRecordedS)) {
      return "Original recording " + formatClock(row.tRecordedS * 1000) + ". " + ingest + " Ingestion time is not the capture time. " + device;
    }
    if (msg && msg.source === "recording") {
      return ingest + " Playback time is not the original capture time. " + device;
    }
    return ingest + " " + device;
  }

  function paintTimeline(doc, state, msg) {
    var rows = filtered(state);
    var windowMode = state.windowPinned ? state.windowMode : "recent";
    var model = chartWindow(rows, windowMode, msg.t_host, state.selectedKey, !state.windowPinned);
    if (!state.windowPinned) {
      doc.querySelectorAll("[data-window]").forEach(function (button) {
        button.setAttribute("aria-pressed", String(button.dataset.window === (model.effective === "recent" ? "recent" : "retained")));
      });
    }
    doc.getElementById("window-label").textContent = model.label;
    var outside = doc.getElementById("outside-note");
    if (model.outside) {
      outside.hidden = false;
      outside.textContent = "Selected evidence is outside this chart window. It stays in the selected-evidence panel.";
    } else {
      outside.hidden = true;
      outside.textContent = "";
    }
    var chartEl = doc.getElementById("chart");
    var empty = doc.getElementById("chart-empty");
    var marks = doc.getElementById("marks");
    marks.replaceChildren();
    if (!model.points.length || typeof echarts === "undefined") {
      chartEl.hidden = true;
      empty.hidden = false;
      empty.textContent = typeof echarts === "undefined"
        ? "Timeline chart did not load from this host."
        : "No retained observations in this window.";
      if (state.chart) {
        state.chart.dispose();
        state.chart = null;
      }
      return;
    }
    empty.hidden = true;
    chartEl.hidden = false;
    var sensorIds = {};
    (msg.nodes || []).forEach(function (node) { sensorIds[node.id] = true; });
    model.points.forEach(function (row) { sensorIds[row.sensorId] = true; });
    var categories = Object.keys(sensorIds).map(Number).sort(function (a, b) { return a - b; }).map(function (id) {
      return "Node " + id;
    });
    function series(family, symbol) {
      return {
        name: family,
        type: "scatter",
        symbol: symbol,
        symbolSize: function (value, params) {
          return params.data && params.data.key === state.selectedKey ? 16 : 10;
        },
        data: model.points.filter(function (row) { return row.family === family; }).map(function (row) {
          var color = family === "acoustic" ? "#FBBF24" : family === "radio" ? "#7DD3FC" : "#94A3B8";
          return {
            value: [row.tHost, "Node " + row.sensorId],
            key: row.key,
            label: row.label,
            shape: row.shape,
            age: ageLabel(evidenceAgeMs(row, msg.t_host), state.socketState),
            itemStyle: {
              color: color,
              borderColor: row.key === state.selectedKey ? "#F1F5F9" : "transparent",
              borderWidth: row.key === state.selectedKey ? 2 : 0
            }
          };
        })
      };
    }
    if (!state.chart) {
      state.chart = echarts.init(chartEl, null, { renderer: "canvas" });
      state.chart.on("click", function (params) {
        if (params && params.data && params.data.key) select(doc, state, params.data.key, true);
      });
    }
    state.chart.setOption({
      animation: false,
      backgroundColor: "transparent",
      grid: { left: 72, right: 16, top: 16, bottom: 48 },
      tooltip: {
        trigger: "item",
        formatter: function (params) {
          var data = params.data || {};
          return escapeHtml(data.label || "") + "<br/>" + escapeHtml(params.value ? params.value[1] : "") + "<br/>" + escapeHtml(data.shape || "") + " · " + escapeHtml(data.age || "");
        }
      },
      xAxis: {
        type: "time",
        min: model.start,
        max: model.end,
        name: "Host-receipt time",
        nameLocation: "middle",
        nameGap: 28,
        nameTextStyle: { color: "#9AA8BC", fontSize: 11 },
        axisLabel: { color: "#9AA8BC", hideOverlap: true },
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.16)" } },
        splitLine: { show: false }
      },
      yAxis: {
        type: "category",
        data: categories,
        inverse: true,
        name: "Sensor",
        nameTextStyle: { color: "#9AA8BC", fontSize: 11 },
        axisLabel: { color: "#F1F5F9" },
        axisLine: { lineStyle: { color: "rgba(255,255,255,0.16)" } },
        splitLine: { show: true, lineStyle: { color: "rgba(255,255,255,0.06)" } }
      },
      series: [
        series("acoustic", "circle"),
        series("radio", "triangle"),
        series("other", "rect")
      ]
    }, false);
    model.points.slice().sort(function (a, b) { return b.tHost - a.tHost; }).forEach(function (row) {
      var button = doc.createElement("button");
      button.type = "button";
      button.className = "btn btn-sm mark-btn" + (state.selectedKey === row.key ? " is-selected" : "");
      button.dataset.key = row.key;
      button.setAttribute("aria-pressed", String(state.selectedKey === row.key));
      button.textContent = row.shape + " · " + row.label + " · Node " + row.sensorId + (state.selectedKey === row.key ? " · Selected" : "");
      button.addEventListener("click", function () { select(doc, state, row.key, true); });
      marks.append(button);
    });
  }

  function paintDiagnostics(doc, state, msg) {
    var counts = msg.counts || {};
    doc.getElementById("diag-socket").textContent = socketUrl() || "Unknown";
    doc.getElementById("diag-pps").textContent = Number.isFinite(counts.packets_per_s) ? String(counts.packets_per_s) : "Unknown";
    doc.getElementById("diag-bps").textContent = Number.isFinite(counts.bytes_per_s) ? String(counts.bytes_per_s) : "Unknown";
    doc.getElementById("diag-packets").textContent = Number.isFinite(counts.packets) ? String(counts.packets) : "Unknown";
    doc.getElementById("diag-stale").textContent = Number.isFinite(msg.stale_after_ms) ? msg.stale_after_ms + " ms" : "Unknown";
    doc.getElementById("diag-mode").textContent = msg.localization_mode || "Unknown";
    doc.getElementById("diag-banner").textContent = msg.banner && msg.banner.text ? msg.banner.text : "Unknown";
    doc.getElementById("diag-ignored").textContent = state.ignoredVersion ? String(state.ignoredVersion) : "None";
    var linkNode = doc.getElementById("diag-link");
    if (linkNode) {
      var link = msg.link || {};
      var parts = [];
      if (link.transport) parts.push(String(link.transport));
      if (link.connected === false) parts.push("down");
      else if (link.connected === true) parts.push("up");
      if (link.last_error) parts.push(String(link.last_error));
      if (msg.gateway && Number.isFinite(msg.gateway.rx_dropped)) parts.push(msg.gateway.rx_dropped + " dropped, gateway " + shown(msg.gateway.id));
      linkNode.textContent = parts.length ? parts.join(" · ") : "Not reported";
    }
    var storeNode = doc.getElementById("diag-store");
    if (storeNode) {
      var diag = msg.diagnostics || {};
      storeNode.textContent = diag.store_errors ? String(diag.store_errors) + " (" + (diag.last_store_error || "write failed") + ")" : "None";
    }
    var drawer = doc.getElementById("diagnostics");
    var raw = doc.getElementById("diag-raw");
    if (raw && drawer && drawer.open) {
      var packed = JSON.stringify(msg);
      if (state.diagPacked !== packed) {
        state.diagPacked = packed;
        raw.textContent = JSON.stringify(msg, null, 2);
      }
    } else if (raw && raw.textContent === "No message yet") {
      raw.textContent = "Open this drawer to load the latest socket message.";
    }
    if (!(drawer && drawer.open)) return;
    var links = doc.getElementById("diag-links");
    links.replaceChildren();
    if (!(msg.links || []).length) links.append(el(doc, "p", "empty", "Not reported"));
    else (msg.links || []).forEach(function (link) {
      links.append(el(doc, "p", "", "Node " + shown(link.a) + " reported neighbor " + shown(link.b) + " at " + shown(link.rssi, " dBm. Not a distance.")));
    });
    var ranges = doc.getElementById("diag-ranges");
    ranges.replaceChildren();
    if (!(msg.ranges || []).length) ranges.append(el(doc, "p", "empty", "Not reported"));
    else (msg.ranges || []).forEach(function (range) {
      ranges.append(el(doc, "p", "", "Node " + shown(range.src) + " heard chirper " + shown(range.chirper) + ", delay " + shown(range.delay_us, " µs. Not a calibrated distance.")));
    });
  }

  function refreshHistory(doc) {
    var box = doc.getElementById("diag-history");
    if (!box || typeof fetch !== "function") return;
    fetch("/history?limit=8").then(function (response) {
      if (!response.ok) throw new Error("history unavailable");
      return response.json();
    }).then(function (body) {
      var rows = (body && body.observations) || [];
      box.replaceChildren();
      if (!body || body.persistent === false) {
        box.append(el(doc, "p", "empty", "This process is not writing a database."));
        return;
      }
      if (!rows.length) {
        box.append(el(doc, "p", "empty", "No stored rows yet."));
        return;
      }
      rows.forEach(function (row) {
        box.append(el(
          doc,
          "p",
          "",
          String(row.source || "unknown").toUpperCase()
            + " · " + shown(row.msg_type)
            + " · node " + shown(row.src)
            + " · stored evidence, not a new live detection"
        ));
      });
    }).catch(function () {
      if (box.textContent === "Not loaded") {
        box.replaceChildren(el(doc, "p", "empty", "History was not loaded."));
      }
    });
  }

  function refreshReplay(doc, state) {
    var button = doc.getElementById("replay");
    fetch("/demo").then(function (response) {
      if (!response.ok) throw new Error("unavailable");
      return response.json();
    }).then(function (body) {
      button.hidden = !body.available;
      if (!state.latest && body.available) {
        setRun(doc, "Replay clears retained demo observations and plays the script again through ingest. It does not send a hardware command.");
      }
      if (!body.available && !state.latest) {
        setRun(doc, "Replay is not available on this process. This page will not reset a live session.");
      }
    }).catch(function () {
      button.hidden = true;
    });
  }

  function replayDemo(doc, state) {
    var button = doc.getElementById("replay");
    button.disabled = true;
    state.replayError = "";
    setRun(doc, "Restart requested. Waiting for the host to clear retained demo observations.");
    fetch("/demo/replay", { method: "POST" }).then(function (response) {
      return response.json().then(function (body) { return { ok: response.ok, body: body }; });
    }).then(function (result) {
      if (!result.ok || !result.body.ok) {
        state.replayError = (result.body && result.body.error) || "Replay failed. State was not reset.";
        setRun(doc, state.replayError);
        return;
      }
      var keys = state.observations.map(function (row) { return row.key; });
      var packets = state.latest && state.latest.counts ? state.latest.counts.packets : 0;
      state.replayWatch = { packets: packets, keys: keys };
      setRun(doc, "Restart requested. These rows are still the previous demo run until the host snapshot clears.");
    }).catch(function () {
      state.replayError = "Replay failed. The browser could not reach the server. No hardware command was sent.";
      setRun(doc, state.replayError);
    }).then(function () {
      button.disabled = false;
    });
  }

  function connect(doc, state) {
    var url = socketUrl();
    if (!url) {
      setSocket(doc, state, "disconnected");
      setRun(doc, "Open this page from the fusion host. A file URL has no server.");
      return;
    }
    if (state.socket && (state.socket.readyState === WebSocket.CONNECTING || state.socket.readyState === WebSocket.OPEN)) return;
    try {
      state.socket = new WebSocket(url);
    } catch (err) {
      setSocket(doc, state, "disconnected");
      return;
    }
    state.socket.addEventListener("open", function () {
      setSocket(doc, state, "connected");
      if (state.latest) render(doc, state);
      refreshReplay(doc, state);
    });
    state.socket.addEventListener("message", function (event) {
      var msg;
      try { msg = JSON.parse(event.data); } catch (err) { return; }
      if (!msg || msg.v !== 1) {
        state.ignoredVersion += 1;
        var ignored = doc.getElementById("diag-ignored");
        if (ignored) ignored.textContent = String(state.ignoredVersion);
        return;
      }
      state.lastMessageAt = Date.now();
      if (state.socketState === "stale") setSocket(doc, state, "connected");
      onSnapshot(doc, state, msg);
    });
    state.socket.addEventListener("close", function () {
      setSocket(doc, state, "disconnected");
      if (state.latest) render(doc, state);
      if (state.retryTimer) window.clearTimeout(state.retryTimer);
      state.retryTimer = window.setTimeout(function () {
        setSocket(doc, state, "reconnecting");
        connect(doc, state);
      }, 1500);
    });
    state.socket.addEventListener("error", function () { setSocket(doc, state, "disconnected"); });
  }

  return {
    RECENT_WINDOW_MS: RECENT_WINDOW_MS,
    readableKind: readableKind,
    countText: countText,
    countMeaning: countMeaning,
    confText: confText,
    measurementText: measurementText,
    reusePlan: reusePlan,
    peakText: peakText,
    voiceText: voiceText,
    collectObservations: collectObservations,
    replaceHistory: replaceHistory,
    chooseSelection: chooseSelection,
    chartWindow: chartWindow,
    resetLanded: resetLanded,
    evidenceAgeMs: evidenceAgeMs,
    sensorAgeMs: sensorAgeMs,
    cueKey: cueKey,
    deviceKey: deviceKey,
    sourceLabel: sourceLabel,
    start: start
  };
});
