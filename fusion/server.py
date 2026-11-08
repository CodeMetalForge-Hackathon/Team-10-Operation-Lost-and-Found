"""Serve fusion state to the static dashboard. This is the one fusion host process.

The /ws payload is the proposed v1 contract in docs/WS_CONTRACT.md.
It is not a change to the gateway JSON lines in docs/ARCHITECTURE.md.

Also served by this process (team decision 2026-11-08, one host instead of two):
  GET  /                the ops dashboard (ui/ops.html: heatmap, node fleet, distance matrix, sensor graphs)
  GET  /ops             its data, one JSON (build_ops)
  GET  /review          the evidence review page (ui/index.html)
  GET  /heatmap         the experimental heatmap page (fusion/heatmap.py's model and page)
  GET  /heatmap/state   that model's snapshot
  POST /heatmap/reset   clear the heatmap
  POST /cmd?name=HAIL   send HAIL / PING / BLINK to the gateway (serial input only)
  GET  /tak             node markers + evidence remarks + the heatmap peak ("T10 LOOK HERE") for fusion/tak.py
  GET  /mosaic.png|json a saved camera mosaic (--mosaic data/camera/walk3_mosaic); a live camera is loaded directly
Node positions: --pos (hand-measured), else the drone camera's drops (--mosaic :8080 or http://PI-IP:8080),
else the 3-node test layout for --demo/--simulate/--recording. Live gateway input is recorded to data/live_*.jsonl.
POST /anchor and POST /baseline are not implemented.
"""

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from fusion.history import History
from fusion.people import WINDOW_S as PEOPLE_WINDOW_S, estimate as people_estimate
from fusion.serial_ingest import accept_line, read_simulated
from fusion.state import FusionState

UI_DIR = Path(__file__).resolve().parents[1] / "ui"
PUSH_INTERVAL_S = 0.5
DEFAULT_POSITIONS = {1: (0.0, 0.0), 2: (3.0, 0.0), 5: (0.0, 3.0)}  # same 3-node layout as heatmap.py
GATEWAY_COMMANDS = ("HAIL", "PING", "BLINK")  # names firmware/node/node.ino accepts after "CMD "
TAK_POLL_FRESH_MS = 10_000


def heatmap_page(mosaic_url=""):
    """fusion/heatmap.py's page, pointed at this server's routes and at the camera (mosaic_url: http://... or :8080)."""
    from fusion.heatmap import PAGE

    return (
        PAGE.replace("fetch('/state')", "fetch('/heatmap/state')")
        .replace("__T10_MOSAIC_URL__", mosaic_url)
        .replace("fetch('/reset'", "fetch('/heatmap/reset'")
        .replace(
            "function cmd(n){fetch('/cmd?name='+n,{method:'POST'})}",
            "function cmd(n){fetch('/cmd?name='+n,{method:'POST'}).then(r=>r.json())"
            ".then(j=>{if(!j.ok)alert(j.error)}).catch(()=>alert('host not reachable'))}",
        )
        .replace(
            '<div id="side"><h2>Team 10: where to look</h2>',
            '<div id="side"><p><a href="/" style="color:#7fd">&larr; Operations overview</a></p>'
            "<h2>Team 10: where to look</h2>"
            '<p class="muted">Where sound and vibration evidence is strongest. Not a confirmed survivor location.</p>',
        )
    )


def create_app(state=None, now_ms=None, ui_dir=None, demo=None, heatmap=None, commands=None, positions=None,
               mosaic=None):
    """positions: {id: (x, y)} metres. app.state.positions["now"] is replaced (not edited) when the camera's
    drops change, so readers always see one consistent dict. mosaic: camera address or saved-mosaic file prefix."""
    fusion = state if state is not None else FusionState()
    page_dir = Path(ui_dir) if ui_dir is not None else UI_DIR
    pos = {"now": dict(DEFAULT_POSITIONS if positions is None else positions)}
    mosaic_url = mosaic.rstrip("/") if mosaic and mosaic.startswith(("http", ":")) else ""
    mosaic_file = mosaic if mosaic and not mosaic_url else None
    app = FastAPI(title="Team 10 fusion host", docs_url=None, redoc_url=None)
    app.state.fusion = fusion
    app.state.positions = pos
    tak_seen = {"last_poll_ms": None}
    sensor_history = History()  # rolling per-node sensor series for the ops dashboard's graphs
    fusion.observers.append(sensor_history.ingest)
    fusion.reset_hooks.append(sensor_history.reset)

    def snapshot():
        now = _now(now_ms)
        snap = fusion.snapshot(now)
        last = tak_seen["last_poll_ms"]
        snap["tak_bridge"] = {
            "last_poll_ms": last,
            "polling": last is not None and now - last <= TAK_POLL_FRESH_MS,
        }
        return snap

    @app.get("/")
    def ops_page():
        return FileResponse(page_dir / "ops.html")

    @app.get("/review")
    def review_page():
        return FileResponse(page_dir / "index.html")

    @app.get("/ops")
    def ops_state():
        now = _now(now_ms)
        snap = snapshot()
        heat = heatmap.snapshot(now / 1000.0) if heatmap is not None else None
        return build_ops(snap, heat, pos["now"], sensor_history.series(now / 1000.0), mosaic_url, now,
                         devices=sensor_history.devices(now / 1000.0, PEOPLE_WINDOW_S))

    @app.get("/heatmap")
    def heatmap_index():
        if heatmap is None:
            return HTMLResponse(
                "<p>The heatmap is off in this process (started with --no-heatmap, or numpy is missing). "
                '<a href="/">Back</a></p>',
                status_code=404,
            )
        return HTMLResponse(heatmap_page(mosaic_url))

    @app.get("/heatmap/state")
    def heatmap_state():
        if heatmap is None:
            return JSONResponse(status_code=404, content={"error": "heatmap is off"})
        return heatmap.snapshot(_now(now_ms) / 1000.0)

    @app.post("/heatmap/reset")
    def heatmap_reset():
        if heatmap is None:
            return JSONResponse(status_code=404, content={"ok": False, "error": "heatmap is off"})
        heatmap.reset()
        return {"ok": True}

    @app.post("/cmd")
    def send_command(name: str = ""):
        name = name.upper()
        if name not in GATEWAY_COMMANDS:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": f"unknown command {name!r}; use one of {list(GATEWAY_COMMANDS)}"},
            )
        if commands is None:
            return JSONResponse(
                status_code=409,
                content={"ok": False, "error": "No gateway serial port in this mode. Commands only go out with --gateway."},
            )
        if fusion.snapshot(_now(now_ms))["link"].get("connected") is not True:
            # Never queue: a HAIL sent minutes later beeps at the wrong time and spoils the heatmap's reply window.
            return JSONResponse(status_code=409, content={"ok": False, "error": "gateway not connected; plug it in and retry"})
        commands.put(f"CMD {name} 0 255")
        return {"ok": True, "sent": f"CMD {name} 0 255"}

    @app.get("/tak")
    def tak_picture():
        from fusion.tak import picture_from_heatmap_state
        from fusion.tak_picture import build_picture

        now = _now(now_ms)
        tak_seen["last_poll_ms"] = now
        picture = build_picture(fusion.snapshot(now), pos["now"], now)
        if heatmap is not None:  # the peak, only while confident: tak.py sends it as "T10 LOOK HERE"
            picture["sources"] = picture_from_heatmap_state(heatmap.snapshot(now / 1000.0))["sources"]
        return picture

    @app.get("/mosaic.png")
    @app.get("/mosaic.json")
    def saved_mosaic(request: Request):
        ext = Path(request.url.path).suffix
        path = Path(mosaic_file + ext) if mosaic_file else None
        if path is None or not path.is_file():  # read on each request: the file may be rewritten
            return Response("no mosaic", status_code=404)
        return FileResponse(path, media_type="image/png" if ext == ".png" else "application/json")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        icon = page_dir / "vendor" / "icons" / "ear.svg"
        if icon.is_file():
            return FileResponse(icon, media_type="image/svg+xml")
        return Response(status_code=204)

    @app.get("/state")
    def state_now():
        return snapshot()

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        try:
            while True:
                await socket.send_json(snapshot())
                await asyncio.sleep(PUSH_INTERVAL_S)
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            return

    @app.get("/history")
    def history(limit: int = 50, source: str = None, src: int = None, msg_type: str = None):
        store = getattr(fusion, "store", None)
        if store is None:
            return {"v": 1, "persistent": False, "observations": []}
        return {
            "v": 1,
            "persistent": True,
            "historical": True,
            "count": store.count(),
            "observations": store.recent(limit=limit, source=source, src=src, msg_type=msg_type),
        }

    @app.get("/history/{row_id}")
    def history_one(row_id: int):
        store = getattr(fusion, "store", None)
        if store is None:
            return JSONResponse(status_code=404, content={"persistent": False, "historical": True})
        row = store.get(row_id)
        if row is None:
            return JSONResponse(
                status_code=404,
                content={"persistent": True, "historical": True, "error": "not found"},
            )
        return row

    @app.get("/demo")
    def demo_status():
        simulated = bool(fusion.simulated)
        available = simulated and demo is not None and hasattr(demo, "replay")
        return {
            "available": available,
            "simulated": simulated,
            "mode": "simulation" if simulated else "live",
            "sends_hardware_commands": False,
        }

    @app.post("/demo/replay")
    def replay_demo():
        if not fusion.simulated or demo is None or not hasattr(demo, "replay"):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "mode": "simulation" if fusion.simulated else "live",
                    "sends_hardware_commands": False,
                    "error": (
                        "Replay is only available in simulation mode. "
                        "It does not reset a live gateway session and it does not send hardware commands."
                    ),
                },
            )
        result = demo.replay()
        result.setdefault("sends_hardware_commands", False)
        return JSONResponse(status_code=200 if result.get("ok") else 409, content=result)

    if page_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=page_dir), name="ui-assets")

    return app


def load_simulated(path, state, log, now_ms):
    state.simulated = True
    return read_simulated(path, state, log, now_ms)


def _now(clock):
    if clock is None:
        import time

        return int(time.time() * 1000)
    return clock() if callable(clock) else clock


def main(argv=None):
    import argparse
    import os
    import sys
    import threading
    import time

    import uvicorn

    from fusion.serial_ingest import open_serial, resolve_endpoint, run_port

    parser = argparse.ArgumentParser(
        prog="fusion.server",
        description="Serve the dashboard from gateway lines. Choose one input, or --gateway with --tcp.",
    )
    parser.add_argument("--demo", action="store_true", help="Play the built-in simulated gateway script.")
    parser.add_argument("--simulate", default=None, help="Read this gateway JSON file immediately. This is not a hardware recording.")
    parser.add_argument("--recording", default=None, help="Play a recorded gateway JSONL, keeping its intervals.")
    parser.add_argument("--speed", type=float, default=1.0, help="Recording speed. 1 keeps the recorded intervals.")
    parser.add_argument("--gateway", default=None, help="Serial device. Prefer /dev/serial/by-id/...")
    parser.add_argument("--baud", type=int, default=None)
    parser.add_argument("--tcp", type=int, default=None, help="Listen for newline JSON. Do not use 8765 or 8775.")
    parser.add_argument("--tcp-bind", default="127.0.0.1", help="Bind address for --tcp.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--listen", type=int, default=8000)
    parser.add_argument("--stale-ms", type=int, default=6000)
    parser.add_argument("--store", default="data/host.sqlite", help="SQLite history. Not the live node table.")
    parser.add_argument("--no-store", action="store_true", help="Keep observations in memory only.")
    parser.add_argument("--pos", action="append", default=[],
                        help="ID=x,y metres, hand-measured. Default: the camera's drops with --mosaic <camera>; "
                             "1=0,0 2=3,0 5=0,3 for --demo/--simulate/--recording. Used by /heatmap and /tak.")
    parser.add_argument("--mosaic", default=None,
                        help="drone camera: :8080 (on the Pi) or http://PI-IP:8080 places nodes where they were dropped "
                             "and shows the floor photo; or a saved mosaic file prefix (photo only)")
    parser.add_argument("--name", default=None, help="live recording name (default live_<time>)")
    parser.add_argument("--no-record", action="store_true", help="do not record live gateway lines to data/*.jsonl")
    parser.add_argument("--no-heatmap", action="store_true", help="Do not run the heatmap estimator (/heatmap).")
    args = parser.parse_args(argv)
    try:
        positions = parse_positions(args.pos)
    except ValueError as exc:
        sys.stderr.write(f"--pos: {exc}\n")
        return 2
    camera = args.mosaic if args.mosaic and args.mosaic.startswith(("http", ":")) else None

    selected = [name for name in ("demo", "simulate", "gateway", "recording") if getattr(args, name)]
    if len(selected) > 1:
        sys.stderr.write("choose only one of --demo, --simulate, --recording, --gateway\n")
        return 2
    if args.tcp is not None and selected and selected != ["gateway"]:
        sys.stderr.write("--tcp is a live input; combine it only with --gateway\n")
        return 2
    if args.listen in (8765, 8775) or args.tcp in (8765, 8775):
        sys.stderr.write("8765 and 8775 are already used by demo services; pick another port\n")
        return 2
    if not selected and args.tcp is None and not os.environ.get("GATEWAY_PORT"):
        sys.stderr.write("choose --demo, --simulate FILE, --recording FILE, --gateway PORT, or --tcp PORT\n")
        return 2
    if args.recording and args.speed <= 0:
        sys.stderr.write("speed must be positive\n")
        return 2

    store = None
    if not args.no_store:
        from fusion.store import ObservationStore

        store = ObservationStore(args.store)
    state = FusionState(stale_after_ms=args.stale_ms, store=store)
    stop = threading.Event()

    def log(message):
        sys.stderr.write(str(message) + "\n")

    def clock():
        return int(time.time() * 1000)

    live = not (args.demo or args.simulate or args.recording)
    if not args.pos and (camera or live):
        positions = {}  # placed by the camera's drops (or not placed: give --pos)
    heatmap = None if args.no_heatmap else start_heatmap(state, positions, stop, log)
    meta = {"positions_m": {str(k): list(v) for k, v in positions.items()}, "tool": "fusion/server.py",
            "positions_from": "--pos" if args.pos else camera}
    rec = None
    if live and not args.no_record:
        rec = start_recording(state, args.name, meta)
    commands = None
    player = None
    if args.demo:
        from fusion.demo_player import DemoPlayer
        from sim.demo import SCRIPT, keepalive_line

        state.source = "simulation"
        state.simulated = True
        state.note_link(transport="simulation", connected=True, last_error=None)
        player = DemoPlayer(state, log, clock, SCRIPT, keepalive_line)
        player.start()
    elif args.simulate:
        state.source = "simulation"
        state.simulated = True
        state.note_link(transport="file", connected=True, last_error=None)
        if args.simulate == "-":
            threading.Thread(target=_read_stdin, args=(state, stop, log, clock), daemon=True).start()
        else:
            load_simulated(args.simulate, state, log, clock)
    elif args.recording:
        from pathlib import Path

        from fusion.recording import RecordingPlayer

        path = Path(args.recording)
        lines = path.read_text(encoding="utf-8").splitlines()
        state.source = "recording"
        state.simulated = False
        state.note_link(transport="recording", connected=True, last_error=None)
        player = RecordingPlayer(state, log, clock, lines, speed=args.speed, path=path)
        threading.Thread(target=player.play, daemon=True, name="recording-player").start()
    else:
        serial_requested = bool(args.gateway or os.environ.get("GATEWAY_PORT"))
        if serial_requested:
            try:
                port, baud = resolve_endpoint(args.gateway, args.baud, os.environ)
            except ValueError as exc:
                log(exc)
                return 2
            import queue

            commands = queue.Queue()
            threading.Thread(
                target=run_port,
                args=(
                    lambda: open_serial(port, baud),
                    state,
                    log,
                    clock,
                    time.sleep,
                    stop.is_set,
                ),
                kwargs={"commands": commands},
                daemon=True,
            ).start()
        if args.tcp is not None:
            from fusion.net_ingest import run_tcp

            threading.Thread(
                target=run_tcp,
                args=("127.0.0.1" if args.tcp_bind is None else args.tcp_bind, args.tcp, state, log, clock, stop.is_set),
                daemon=True,
                name="tcp-ingest",
            ).start()
        state.source = "live"
        state.simulated = False

    app = create_app(state, demo=player, heatmap=heatmap, commands=commands, positions=positions, mosaic=args.mosaic)
    if camera and not args.pos:
        from fusion.heatmap import drops_poller

        def on_drops(nodes):  # one new dict for /tak; drops_poller already updated the heatmap grid
            app.state.positions["now"] = dict(nodes)
            meta["positions_m"] = {str(k): list(v) for k, v in nodes.items()}
            if rec:
                write_meta(rec, meta)

        base = ("http://127.0.0.1" + camera) if camera.startswith(":") else camera.rstrip("/")
        target = heatmap if heatmap is not None else _NoHeatmap()
        threading.Thread(target=drops_poller, args=(target, base, on_drops), daemon=True, name="drops").start()
        sys.stderr.write(f"node positions from the drone camera's drops: {base}/drops\n")
    sys.stderr.write(
        f"dashboard http://{args.host}:{args.listen}/  ws://{args.host}:{args.listen}/ws\n"
    )
    sys.stderr.write(
        f"heatmap   http://{args.host}:{args.listen}/heatmap   TAK picture http://{args.host}:{args.listen}/tak\n"
        if heatmap is not None
        else f"heatmap off. TAK picture http://{args.host}:{args.listen}/tak\n"
    )
    if positions or not camera:
        sys.stderr.write(f"node positions (metres): {positions or 'none: give --pos ID=x,y or --mosaic <camera>'}\n")
    if rec:
        sys.stderr.write(f"recording to {rec}\n")
    if state.source == "recording":
        sys.stderr.write("input is a recording. It is not a live board and not the simulated script.\n")
    elif state.simulated or state.source == "simulation":
        sys.stderr.write("input is simulated. It is not a hardware recording.\n")
    else:
        sys.stderr.write("input is live. USB and TCP use the same parser. This process has not verified a Pi.\n")
    uvicorn.run(app, host=args.host, port=args.listen, log_level="warning")
    if player is not None:
        player.stop()
    stop.set()
    return 0


HEAT_KEYS = ("bounds", "res", "nx", "ny", "heat", "peak", "sources", "people_est", "hail_age", "warmup")


def build_ops(snap, heat, positions, series, mosaic_url, now_ms, devices=()):
    """Everything the ops dashboard draws, in one JSON (polled at 1 Hz).

    dropped = nodes with a position (camera drops or --pos); operational = dropped and reporting.
    matrix: metres between positions (upper triangle on the page) and mesh link dBm, the mean of what
    each node reports hearing from the other in its beacon (lower triangle); None = unknown / no link.
    """
    by_id = {n["id"]: n for n in snap["nodes"]}
    ids = sorted(set(positions) | set(by_id))
    nodes = []
    for i in ids:
        n = by_id.get(i, {})
        x, y = positions.get(i, (None, None))
        nodes.append({
            "id": i, "x": x, "y": y, "dropped": i in positions,
            "alive": n.get("status") == "active",
            "age_s": round((now_ms - n["last_t_host"]) / 1000.0, 1) if n.get("last_t_host") else None,
            "hops": n.get("hops"), "rssi": n.get("rssi_last"), "floor_db": n.get("floor_db"),
            "uptime_s": n.get("uptime_s"),
        })
    heard = {}  # (a, b) -> [dBm a reports for b, ...]
    for n in snap["nodes"]:
        for other, dbm in n.get("nbrs") or []:
            heard.setdefault(tuple(sorted((n["id"], other))), []).append(dbm)
    metres, dbm = [], []
    for a in ids:
        metres.append([_dist(positions.get(a), positions.get(b)) for b in ids])
        dbm.append([None if a == b else _mean(heard.get(tuple(sorted((a, b))))) for b in ids])
    dropped = [i for i in ids if i in positions]
    return {
        "t": now_ms / 1000.0,
        "source": snap.get("source"),
        "link": snap.get("link"),
        "tak": bool(snap.get("tak_bridge", {}).get("polling")),
        "packets_per_s": snap["counts"]["packets_per_s"],
        "bytes_per_s": snap["counts"]["bytes_per_s"],
        "nodes": nodes,
        "dropped": dropped,
        "operational": [i for i in dropped if by_id.get(i, {}).get("status") == "active"],
        "heard_not_dropped": [i for i in ids if i not in positions and by_id.get(i, {}).get("status") == "active"],
        "matrix": {"ids": ids, "metres": metres, "dbm": dbm},
        "heat": {k: heat.get(k) for k in HEAT_KEYS} if heat else None,
        "history": {str(k): v for k, v in series.items()},
        "people": people_estimate(heat.get("people_est") if heat else None, series, devices, positions, now_ms / 1000.0),
        "mosaic_url": mosaic_url,
    }


def _dist(p, q):
    if p is None or q is None:
        return None
    return round(((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5, 2)


def _mean(values):
    return round(sum(values) / len(values)) if values else None


class _NoHeatmap:  # drops still reach /tak when started with --no-heatmap
    def set_positions(self, _positions):
        pass


# Fields serial_ingest adds when it stamps a line. A recording keeps the gateway line + t_host (Unix seconds),
# the format fusion/heatmap.py records, so either tool can replay it.
_STAMP_FIELDS = ("t_host", "t_recorded", "t_recorded_s", "t_ingest_ms", "t_device_ms")


def start_recording(state, name, meta):
    """Append every accepted gateway line to data/<name>.jsonl, with a .meta.json beside it (node positions)."""
    root = Path(__file__).resolve().parents[1] / "data"
    root.mkdir(exist_ok=True)
    name = name or time.strftime("live_%Y%m%d_%H%M%S")
    path = root / (name + ".jsonl")
    meta.update({"name": name, "start": time.strftime("%Y-%m-%dT%H:%M:%S")})
    write_meta(path, meta)

    def record(observation):
        if observation.get("type") == "log":
            return
        line = {k: v for k, v in observation.items() if k not in _STAMP_FIELDS}
        line["t_host"] = round(observation.get("t_ingest_ms", time.time() * 1000) / 1000.0, 3)
        with open(path, "a", encoding="utf-8") as out:  # nothing lost if the Pi loses power
            out.write(json.dumps(line) + "\n")

    state.observers.append(record)
    return path


def write_meta(path, meta):
    Path(str(path).replace(".jsonl", ".meta.json")).write_text(json.dumps(meta, indent=1), encoding="utf-8")


def parse_positions(items):
    """["1=0,0", "2=3,0"] -> {1: (0.0, 0.0), 2: (3.0, 0.0)}. Empty -> the default 3-node layout."""
    if not items:
        return dict(DEFAULT_POSITIONS)
    positions = {}
    for item in items:
        try:
            key, xy = item.split("=")
            x, y = (float(v) for v in xy.split(","))
            positions[int(key)] = (x, y)
        except ValueError:
            raise ValueError(f"expected ID=x,y, got {item!r}") from None
    return positions


def start_heatmap(state, positions, stop, log):
    """Run fusion/heatmap.py's estimator in this process, fed by every accepted line.

    Returns None (and the dashboard keeps working) if numpy is missing.
    """
    try:
        from fusion.heatmap import Fusion
    except ImportError as exc:
        log(f"heatmap off: {exc} (pip install -r requirements.txt)")
        return None
    import threading

    heatmap = Fusion(positions)
    state.observers.append(heatmap.ingest)
    state.reset_hooks.append(heatmap.reset)

    def tick():
        while not stop.wait(0.1):
            heatmap.tick(time.time())

    threading.Thread(target=tick, daemon=True, name="heatmap-tick").start()
    return heatmap


def _read_stdin(state, stop, log, clock):
    import sys

    while not stop.is_set():
        line = sys.stdin.readline()
        if not line:
            return
        try:
            accept_line(line, state, log, clock())
        except (json.JSONDecodeError, ValueError) as exc:
            log(f"{exc}: {line.strip()}")


if __name__ == "__main__":
    raise SystemExit(main())
