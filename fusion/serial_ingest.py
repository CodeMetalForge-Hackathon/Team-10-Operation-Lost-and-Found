"""USB serial and simulated gateway-line reader.

This is the ingest boundary. It is not fusion state and not the /ws payload.
"""

import json
import os


class ListSink:
    def __init__(self):
        self.items = []

    def accept(self, observation):
        self.items.append(observation)


def run_port(open_port, sink, log, now_ms, sleep, stop):
    delay = 1.0
    while not stop():
        try:
            port = open_port()
        except OSError as exc:
            log(f"open failed: {exc}")
            sleep(delay)
            delay = min(delay * 2, 5.0)
            continue
        delay = 1.0
        pending = b""
        try:
            while not stop():
                raw = port.readline()
                if not raw:
                    continue
                pending += raw
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    read_lines([line], sink, log, now_ms)
        except OSError as exc:
            log(f"disconnected: {exc}")
            _close(port)
            if stop():
                return
            sleep(delay)
            delay = min(delay * 2, 5.0)
        else:
            _close(port)


def _close(port):
    close = getattr(port, "close", None)
    if close is None:
        return
    try:
        close()
    except OSError as exc:
        return exc


def read_simulated(path, sink, log, now_ms):
    with open(path, encoding="utf-8") as handle:
        return read_lines(handle, sink, log, now_ms)


def read_lines(lines, sink, log, now_ms):
    clock = now_ms if callable(now_ms) else lambda: now_ms
    accepted = 0
    for line in lines:
        text = line.decode("utf-8", errors="replace") if isinstance(line, bytes) else line
        text = text.strip()
        if not text:
            continue
        try:
            accepted += accept_line(text, sink, log, clock())
        except (json.JSONDecodeError, ValueError) as exc:
            log(f"{exc}: {text}")
    return accepted


EVENT_KINDS = {"LOUD", "TAP_PATTERN", "VOICE_LIKE", "RADAR_PRESENCE", "GAS"}
DEVICE_KINDS = {"BLE_OTHER", "BLE_APPLE", "BLE_FINDMY", "BLE_GOOGLE", "WIFI_PROBE"}
CONTRACT_BAUD = 921600


def accept_line(line, sink, log, now_ms):
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError("gateway line must be a JSON object")
    kind = message.get("type")
    if kind == "beacon":
        _radio(message)
        _require_int(message, "batt_mv", 0, 65535)
        _require_int(message, "floor_db", -128, 127)
        _pairs(message, "nbrs", 0, 255, -128, 127)
    elif kind == "feat":
        _radio(message)
        _require_int(message, "t_ms", 0, 2**32 - 1)
        for key in ("rms_db", "low_db", "voice_db", "high_db", "peak_db"):
            _require_int(message, key, -128, 127)
    elif kind == "event":
        _radio(message)
        _require_int(message, "t_ms", 0, 2**32 - 1)
        _require_int(message, "peak_db", -128, 127)
        _require_int(message, "voice_db", -128, 127)
        _require_int(message, "count", 0, 255)
        _require_int(message, "conf", 0, 255)
        if message.get("kind") not in EVENT_KINDS:
            raise ValueError("unknown event kind")
    elif kind == "range":
        _require_int(message, "src", 0, 255)
        _require_int(message, "chirper", 0, 255)
        _require_int(message, "delay_us", 0, 2**32 - 1)
        _require_int(message, "snr_db", -128, 127)
    elif kind == "device_seen":
        _radio(message)
        _require_int(message, "t_ms", 0, 2**32 - 1)
        _devices(message)
    else:
        raise ValueError(f"unknown gateway type: {kind}")
    observation = dict(message)
    observation["t_host"] = now_ms
    sink.accept(observation)
    return 1


def _radio(message):
    _require_int(message, "src", 0, 255)
    _require_int(message, "seq", 0, 65535)
    _require_int(message, "hops", 0, 255)
    _require_int(message, "rssi_last", -128, 127)


def _pairs(message, key, id_low, id_high, rssi_low, rssi_high):
    pairs = message.get(key)
    if not isinstance(pairs, list):
        raise ValueError(f"{key} must be a list")
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError(f"{key} entries must be [id, rssi]")
        _bounded(pair[0], id_low, id_high, f"{key} id")
        _bounded(pair[1], rssi_low, rssi_high, f"{key} rssi")


def _devices(message):
    devs = message.get("devs")
    if not isinstance(devs, list) or len(devs) > 20:
        raise ValueError("devs must be a list of at most 20")
    for dev in devs:
        if not isinstance(dev, list) or len(dev) != 4:
            raise ValueError("device entry must be [hash, kind, rssi, count]")
        digest, kind, rssi, count = dev
        if not isinstance(digest, str) or len(digest) != 8 or any(c not in "0123456789abcdefABCDEF" for c in digest):
            raise ValueError("device hash must be 8 hex characters")
        if kind not in DEVICE_KINDS:
            raise ValueError("unknown device kind")
        _bounded(rssi, -128, 127, "device rssi")
        _bounded(count, 0, 255, "device count")


def _require_int(message, key, low, high):
    if key not in message:
        raise ValueError(f"missing {key}")
    _bounded(message[key], low, high, key)


def _bounded(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} out of range")


class JsonLineSink:
    """Default sink until fusion owns state. One JSON object per line on stdout."""

    def __init__(self, stream):
        self._stream = stream

    def accept(self, observation):
        self._stream.write(json.dumps(observation, separators=(",", ":")) + "\n")
        flush = getattr(self._stream, "flush", None)
        if flush is not None:
            flush()


def resolve_endpoint(port, baud, env):
    chosen = port or env.get("GATEWAY_PORT")
    if not chosen:
        raise ValueError("set --port or GATEWAY_PORT; no device path is assumed")
    if baud is not None:
        chosen_baud = int(baud)
    elif env.get("GATEWAY_BAUD"):
        chosen_baud = int(env["GATEWAY_BAUD"])
    else:
        chosen_baud = CONTRACT_BAUD
    return chosen, chosen_baud


def open_serial(port, baud, serial_module=None):
    module = serial_module
    if module is None:
        import serial as module
    return module.Serial(port, baudrate=baud, timeout=1)


def main(argv=None, stdout=None, stderr=None, now_ms=None, run=None, serial_module=None):
    import argparse
    import sys
    import time

    parser = argparse.ArgumentParser(
        prog="fusion.serial_ingest",
        description="Read gateway JSON lines from the USB serial port or a file.",
    )
    parser.add_argument("--port", default=None, help="Serial device. Prefer /dev/serial/by-id/...")
    parser.add_argument("--baud", type=int, default=None, help=f"Default {CONTRACT_BAUD} from the contract")
    parser.add_argument("--simulate", default=None, help="Read this file instead of serial. Use - for stdin.")
    args = parser.parse_args(argv)
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    clock = (lambda: int(time.time() * 1000)) if now_ms is None else now_ms
    sink = JsonLineSink(out)

    def log(message):
        err.write(str(message) + "\n")

    if args.simulate:
        if args.simulate == "-":
            read_lines(sys.stdin, sink, log, clock)
        else:
            read_simulated(args.simulate, sink, log, clock)
        return 0
    try:
        port, baud = resolve_endpoint(args.port, args.baud, os.environ)
    except ValueError as exc:
        log(exc)
        return 2
    runner = run_port if run is None else run
    runner(
        lambda: open_serial(port, baud, serial_module),
        sink,
        log,
        clock,
        time.sleep,
        lambda: False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
