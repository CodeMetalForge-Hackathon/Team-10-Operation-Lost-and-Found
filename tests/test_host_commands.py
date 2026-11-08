"""The host commands in the handoff refuse reserved ports and serve a recording."""

import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.request


class ReservedPortTest(unittest.TestCase):
    def test_dashboard_will_not_take_8765(self):
        import io
        import sys
        from fusion.server import main

        old = sys.stderr
        sys.stderr = io.StringIO()
        try:
            code = main(["--demo", "--listen", "8765"])
        finally:
            sys.stderr = old
        self.assertEqual(code, 2)


class RecordingCommandTest(unittest.TestCase):
    def test_recording_command_marks_state_and_keeps_a_node(self):
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "fusion.server",
                "--recording",
                "data/ble_iphone_near_node1.jsonl",
                "--speed",
                "100",
                "--host",
                "127.0.0.1",
                "--listen",
                "18081",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        snap = None
        try:
            deadline = time.time() + 8
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:18081/state", timeout=1) as resp:
                        snap = json.load(resp)
                    if snap.get("source") == "recording" and snap.get("nodes"):
                        break
                except Exception:
                    time.sleep(0.05)
            self.assertIsNotNone(snap)
            self.assertEqual(snap["source"], "recording")
            self.assertFalse(snap["simulated"])
            self.assertTrue(any(node["id"] in (1, 2) for node in snap["nodes"]))
            self.assertTrue(all(node["position"] is None for node in snap["nodes"]))
            self.assertEqual(snap["gateway"]["rx_dropped"], 0)
        finally:
            proc.terminate()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()


class TcpCommandTest(unittest.TestCase):
    def test_tcp_command_accepts_a_beacon(self):
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "fusion.server",
                "--tcp",
                "19100",
                "--tcp-bind",
                "127.0.0.1",
                "--host",
                "127.0.0.1",
                "--listen",
                "18082",
                "--no-record",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        line = (
            '{"type":"beacon","src":2,"seq":91,"hops":0,"rssi_last":-36,'
            '"batt_mv":0,"uptime_s":186,"floor_db":0,"nbrs":[[1,-43]]}\n'
        )
        snap = None
        try:
            deadline = time.time() + 8
            connected = False
            while time.time() < deadline and not connected:
                try:
                    with socket.create_connection(("127.0.0.1", 19100), timeout=0.5) as conn:
                        conn.sendall(line.encode())
                    connected = True
                except OSError:
                    time.sleep(0.05)
            self.assertTrue(connected, "tcp ingest did not accept a connection")
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:18082/state", timeout=1) as resp:
                        snap = json.load(resp)
                    if snap.get("nodes"):
                        break
                except Exception:
                    time.sleep(0.05)
            self.assertIsNotNone(snap)
            self.assertEqual(snap["source"], "live")
            self.assertFalse(snap["simulated"])
            self.assertEqual(snap["nodes"][0]["id"], 2)
            self.assertEqual(snap["nodes"][0]["uptime_s"], 186)
            self.assertEqual(snap["nodes"][0]["batt_mv_status"], "unimplemented")
        finally:
            proc.terminate()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
