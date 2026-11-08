"""Serve fusion state to the static dashboard. This is the one fusion host process.

The /ws payload is the proposed v1 contract in docs/WS_CONTRACT.md.
It is not a change to the gateway JSON lines in docs/ARCHITECTURE.md.

Also served by this process (team decision 2026-11-08, one host instead of two):
  GET  /heatmap         the experimental heatmap page (fusion/heatmap.py's model and page)
  GET  /heatmap/state   that model's snapshot
  POST /heatmap/reset   clear the heatmap
  POST /cmd?name=HAIL   send HAIL / PING / BLINK to the gateway (serial input only)
  GET  /tak             node markers + evidence text for fusion/tak.py (no survivor point)
POST /anchor and POST /baseline are not implemented.
"""

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from fusion.serial_ingest import accept_line, read_simulated
from fusion.state import FusionState

UI_DIR = Path(__file__).resolve().parents[1] / "ui"
PUSH_INTERVAL_S = 0.5
DEFAULT_POSITIONS = {1: (0.0, 0.0), 2: (3.0, 0.0), 5: (0.0, 3.0)}  # same 3-node layout as heatmap.py
GATEWAY_COMMANDS = ("HAIL", "PING", "BLINK")  # names firmware/node/node.ino accepts after "CMD "
TAK_POLL_FRESH_MS = 10_000


def heatmap_page():
    """fusion/heatmap.py's page, pointed at this server's routes.

    Relabelled to match the team decision that the system shows evidence, not a dig point.
    """
    from fusion.heatmap import PAGE

    return (
        PAGE.replace("fetch('/state')", "fetch('/heatmap/state')")
        .replace("fetch('/reset'", "fetch('/heatmap/reset'")
        .replace(
            "function cmd(n){fetch('/cmd?name='+n,{method:'POST'})}",
            "function cmd(n){fetch('/cmd?name='+n,{method:'POST'}).then(r=>r.json())"
            ".then(j=>{if(!j.ok)alert(j.error)}).catch(()=>alert('host not reachable'))}",
        )
        .replace("<title>Team 10 heatmap (test)</title>", "<title>Team 10 evidence heatmap</title>")
        .replace(
            '<div id="side"><h2>Team 10: where to dig (test heatmap)</h2>',
            '<div id="side"><p><a href="/" style="color:#7fd">&larr; Operations overview</a></p>'
            "<h2>Team 10: evidence heatmap (experimental)</h2>"
            '<p class="muted">Where sound and vibration evidence is strongest, from hand-entered node '
            "positions. Not a confirmed survivor location.</p>",
        )
        .replace("<b>Dig here:</b>", "<b>Strongest evidence:</b>")
    )


def create_app(state=None, now_ms=None, ui_dir=None, demo=None, heatmap=None, commands=None, positions=None):
    fusion = state if state is not None else FusionState()
    page_dir = Path(ui_dir) if ui_dir is not None else UI_DIR
    node_positions = dict(DEFAULT_POSITIONS if positions is None else positions)
    app = FastAPI(title="Team 10 fusion host", docs_url=None, redoc_url=None)
    app.state.fusion = fusion
    tak_seen = {"last_poll_ms": None}

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
    def index():
        return FileResponse(page_dir / "index.html")

    @app.get("/heatmap")
    def heatmap_index():
        if heatmap is None:
            return HTMLResponse(
                "<p>The heatmap is off in this process (started with --no-heatmap, or numpy is missing). "
                '<a href="/">Back</a></p>',
                status_code=404,
            )
        return HTMLResponse(heatmap_page())

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
        commands.put(f"CMD {name} 0 255")
        return {"ok": True, "sent": f"CMD {name} 0 255"}

    @app.get("/tak")
    def tak_picture():
        from fusion.tak_picture import build_picture

        now = _now(now_ms)
        tak_seen["last_poll_ms"] = now
        return build_picture(fusion.snapshot(now), node_positions, now)

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
                        help="ID=x,y metres, hand-measured (default: 1=0,0 2=3,0 5=0,3). Used by /heatmap and /tak.")
    parser.add_argument("--no-heatmap", action="store_true", help="Do not run the heatmap estimator (/heatmap).")
    args = parser.parse_args(argv)
    try:
        positions = parse_positions(args.pos)
    except ValueError as exc:
        sys.stderr.write(f"--pos: {exc}\n")
        return 2

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

    heatmap = None if args.no_heatmap else start_heatmap(state, positions, stop, log)
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

    app = create_app(state, demo=player, heatmap=heatmap, commands=commands, positions=positions)
    sys.stderr.write(
        f"dashboard http://{args.host}:{args.listen}/  ws://{args.host}:{args.listen}/ws\n"
    )
    sys.stderr.write(
        f"heatmap   http://{args.host}:{args.listen}/heatmap   TAK picture http://{args.host}:{args.listen}/tak\n"
        if heatmap is not None
        else f"heatmap off. TAK picture http://{args.host}:{args.listen}/tak\n"
    )
    sys.stderr.write(f"node positions (hand-entered, metres): {positions}\n")
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
