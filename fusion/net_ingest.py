"""Newline-delimited JSON over TCP. Same parser as the USB gateway."""

import socket

from fusion.serial_ingest import read_lines


RESERVED_PORTS = {8765, 8775}


def run_tcp(bind, port, sink, log, now_ms, stop, ready=None):
    """Listen until stop() is true. ready(port) fires once the socket is bound."""
    if port in RESERVED_PORTS:
        raise ValueError(f"port {port} is reserved for an existing demo service")
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((bind, port))
        server.listen(4)
        server.settimeout(0.2)
        bound = server.getsockname()[1]
        if ready is not None:
            ready(bound)
        while not stop():
            try:
                conn, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                if stop():
                    return bound
                log(f"tcp accept failed: {exc}")
                _note_link(sink, transport="tcp", connected=False, last_error=str(exc))
                continue
            _note_link(sink, transport="tcp", connected=True, last_error=None)
            _read_connection(conn, sink, log, now_ms, stop)
            _note_link(sink, transport="tcp", connected=False, last_error="tcp client closed")
        return bound
    finally:
        server.close()


def _read_connection(conn, sink, log, now_ms, stop):
    conn.settimeout(0.2)
    pending = b""
    try:
        while not stop():
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                read_lines([line], sink, log, now_ms)
    except OSError as exc:
        log(f"tcp client closed: {exc}")
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _note_link(sink, **fields):
    method = getattr(sink, "note_link", None)
    if method is not None:
        method(**fields)
