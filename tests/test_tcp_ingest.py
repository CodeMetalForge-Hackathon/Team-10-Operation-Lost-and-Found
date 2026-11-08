"""TCP newline JSON uses the same normalizer as USB serial."""

import socket
import threading
import time
import unittest

from fusion.net_ingest import RESERVED_PORTS, run_tcp
from fusion.serial_ingest import accept_line
from fusion.state import FusionState


LINE = (
    '{"type":"beacon","src":2,"seq":91,"hops":0,"rssi_last":-36,'
    '"batt_mv":0,"uptime_s":186,"floor_db":0,"nbrs":[[1,-43]]}\n'
)
GW = '{"type":"gw","id":0,"t_ms":306574,"rx_dropped":0}\n'


class TcpMatchesSerialTest(unittest.TestCase):
    def test_a_tcp_line_normalizes_like_a_serial_line(self):
        serial = FusionState()
        accept_line(LINE, serial, lambda _error: None, now_ms=4_000)
        tcp_state = FusionState()
        errors = []
        stop = threading.Event()
        ready = threading.Event()
        bound = {}

        def serve():
            run_tcp(
                "127.0.0.1",
                0,
                tcp_state,
                errors.append,
                now_ms=lambda: 4_000,
                stop=stop.is_set,
                ready=lambda port: bound.__setitem__("port", port) or ready.set(),
            )

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(2), "tcp ingest did not bind")
        self.assertNotIn(bound["port"], RESERVED_PORTS)
        try:
            with socket.create_connection(("127.0.0.1", bound["port"]), timeout=2) as conn:
                payload = (GW + "not json\n" + LINE).encode()
                conn.sendall(payload[:8])
                conn.sendall(payload[8:])
            deadline = time.time() + 2
            while time.time() < deadline and not tcp_state.snapshot(4_000)["nodes"]:
                time.sleep(0.01)
        finally:
            stop.set()
            thread.join(2)

        self.assertFalse(thread.is_alive())
        self.assertTrue(any("not json" in error for error in errors))
        serial_node = serial.snapshot(4_000)["nodes"][0]
        tcp_node = tcp_state.snapshot(4_000)["nodes"][0]
        self.assertEqual(tcp_node["id"], serial_node["id"])
        self.assertEqual(tcp_node["uptime_s"], 186)
        self.assertEqual(tcp_node["hops"], serial_node["hops"])
        self.assertEqual(tcp_node["batt_mv"], 0)
        self.assertEqual(tcp_node["batt_mv_status"], "unimplemented")
        self.assertEqual(tcp_node["last_t_host"], 4_000)
        self.assertEqual(tcp_state.snapshot(4_000)["gateway"]["rx_dropped"], 0)
        self.assertEqual(tcp_state.snapshot(4_000)["source"], "live")
        self.assertFalse(tcp_state.snapshot(4_000)["simulated"])

    def test_tcp_can_bind_a_lan_address(self):
        state = FusionState()
        stop = threading.Event()
        ready = threading.Event()
        bound = {}

        def serve():
            run_tcp(
                "0.0.0.0",
                0,
                state,
                lambda _error: None,
                now_ms=lambda: 1,
                stop=stop.is_set,
                ready=lambda port: bound.__setitem__("port", port) or ready.set(),
            )

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.assertTrue(ready.wait(2))
        try:
            with socket.create_connection(("127.0.0.1", bound["port"]), timeout=2) as conn:
                conn.sendall(LINE.encode())
            deadline = time.time() + 2
            while time.time() < deadline and not state.snapshot(1)["nodes"]:
                time.sleep(0.01)
        finally:
            stop.set()
            thread.join(2)
        self.assertEqual(state.snapshot(1)["nodes"][0]["id"], 2)
        self.assertEqual(state.snapshot(1)["source"], "live")

    def test_reserved_demo_ports_are_refused(self):
        for port in (8765, 8775):
            with self.assertRaises(ValueError):
                run_tcp(
                    "127.0.0.1",
                    port,
                    FusionState(),
                    lambda _error: None,
                    now_ms=1,
                    stop=lambda: True,
                )
