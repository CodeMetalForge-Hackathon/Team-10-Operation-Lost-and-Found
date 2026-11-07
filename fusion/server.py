"""Serve fusion state to the static dashboard.

The /ws payload is the proposed v1 contract in docs/WS_CONTRACT.md.
It is not a change to the gateway JSON lines in docs/ARCHITECTURE.md.
POST /cmd, POST /anchor, and POST /baseline are not implemented.
"""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from fusion.serial_ingest import accept_line, read_simulated
from fusion.state import FusionState

UI_DIR = Path(__file__).resolve().parents[1] / "ui"
PUSH_INTERVAL_S = 0.5


def create_app(state=None, now_ms=None, ui_dir=None, demo=None):
    fusion = state if state is not None else FusionState()
    page_dir = Path(ui_dir) if ui_dir is not None else UI_DIR
    app = FastAPI(title="Team 10 fusion host", docs_url=None, redoc_url=None)
    app.state.fusion = fusion

    @app.get("/")
    def index():
        return FileResponse(page_dir / "index.html")

    @app.get("/state")
    def state_now():
        return fusion.snapshot(_now(now_ms))

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        try:
            while True:
                await socket.send_json(fusion.snapshot(_now(now_ms)))
                await asyncio.sleep(PUSH_INTERVAL_S)
        except WebSocketDisconnect:
            return

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
        description="Serve the dashboard from gateway lines. One of --demo, --simulate, or --gateway is required.",
    )
    parser.add_argument("--demo", action="store_true", help="Play the built-in simulated gateway script.")
    parser.add_argument("--simulate", default=None, help="Read this gateway JSON file, or - for stdin.")
    parser.add_argument("--gateway", default=None, help="Serial device. Prefer /dev/serial/by-id/...")
    parser.add_argument("--baud", type=int, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--listen", type=int, default=8000)
    parser.add_argument("--stale-ms", type=int, default=6000)
    args = parser.parse_args(argv)

    selected = [name for name in ("demo", "simulate", "gateway") if getattr(args, name)]
    if len(selected) > 1:
        sys.stderr.write("choose only one of --demo, --simulate, --gateway\n")
        return 2
    if not selected and not os.environ.get("GATEWAY_PORT"):
        sys.stderr.write("choose --demo, --simulate FILE, or --gateway PORT\n")
        return 2

    state = FusionState(stale_after_ms=args.stale_ms)
    stop = threading.Event()

    def log(message):
        sys.stderr.write(str(message) + "\n")

    def clock():
        return int(time.time() * 1000)

    player = None
    if args.demo:
        from fusion.demo_player import DemoPlayer
        from sim.demo import SCRIPT, keepalive_line

        state.simulated = True
        player = DemoPlayer(state, log, clock, SCRIPT, keepalive_line)
        player.start()
    elif args.simulate:
        state.simulated = True
        if args.simulate == "-":
            threading.Thread(target=_read_stdin, args=(state, stop, log, clock), daemon=True).start()
        else:
            load_simulated(args.simulate, state, log, clock)
    else:
        try:
            port, baud = resolve_endpoint(args.gateway, args.baud, os.environ)
        except ValueError as exc:
            log(exc)
            return 2
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
            daemon=True,
        ).start()

    app = create_app(state, demo=player)
    sys.stderr.write(
        f"dashboard http://{args.host}:{args.listen}/  ws://{args.host}:{args.listen}/ws\n"
    )
    if state.simulated:
        sys.stderr.write("input is simulated. It is not a hardware recording.\n")
    uvicorn.run(app, host=args.host, port=args.listen, log_level="warning")
    if player is not None:
        player.stop()
    stop.set()
    return 0


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
