import unittest

from fusion.serial_ingest import (
    ListSink,
    accept_line,
    main,
    read_lines,
    read_simulated,
    resolve_endpoint,
    run_port,
)


BEACON = (
    '{"type":"beacon","src":3,"seq":120,"hops":1,"rssi_last":-58,'
    '"batt_mv":3950,"floor_db":-62,"nbrs":[[1,-55],[2,-71]]}'
)


class AcceptBeaconTest(unittest.TestCase):
    def test_valid_beacon_reaches_the_sink_with_host_time(self):
        sink = ListSink()
        errors = []

        accepted = accept_line(BEACON, sink, errors.append, now_ms=1_700_000_000_000)

        self.assertEqual(accepted, 1)
        self.assertEqual(errors, [])
        self.assertEqual(
            sink.items,
            [
                {
                    "type": "beacon",
                    "src": 3,
                    "seq": 120,
                    "hops": 1,
                    "rssi_last": -58,
                    "batt_mv": 3950,
                    "floor_db": -62,
                    "nbrs": [[1, -55], [2, -71]],
                    "t_host": 1_700_000_000_000,
                    "t_ingest_ms": 1_700_000_000_000,
                }
            ],
        )


class MalformedLineTest(unittest.TestCase):
    def test_bad_line_is_logged_and_the_next_beacon_is_kept(self):
        sink = ListSink()
        errors = []

        accepted = read_lines(
            ["{not json", BEACON],
            sink,
            errors.append,
            now_ms=10,
        )

        self.assertEqual(accepted, 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("not json", errors[0])
        self.assertEqual(sink.items[0]["type"], "beacon")
        self.assertEqual(sink.items[0]["t_host"], 10)


FEAT = (
    '{"type":"feat","src":3,"seq":121,"hops":1,"rssi_last":-58,"t_ms":51234,'
    '"rms_db":-40,"low_db":-50,"voice_db":-42,"high_db":-55,"peak_db":-30}'
)
EVENT = (
    '{"type":"event","src":3,"seq":122,"hops":2,"rssi_last":-70,"t_ms":51800,'
    '"kind":"TAP_PATTERN","peak_db":-20,"voice_db":-35,"count":3,"conf":80}'
)
RANGE = '{"type":"range","src":2,"chirper":3,"delay_us":10450,"snr_db":18}'
DEVICE = (
    '{"type":"device_seen","src":4,"seq":88,"hops":1,"rssi_last":-61,"t_ms":60000,'
    '"devs":[["9f3a01c2","BLE_APPLE",-52,14],["07bb4e10","WIFI_PROBE",-70,2]]}'
)


class ContractExamplesTest(unittest.TestCase):
    def test_each_documented_gateway_line_reaches_the_sink(self):
        sink = ListSink()
        errors = []

        accepted = read_lines(
            [BEACON, FEAT, EVENT, RANGE, DEVICE],
            sink,
            errors.append,
            now_ms=20,
        )

        self.assertEqual(errors, [])
        self.assertEqual(accepted, 5)
        self.assertEqual(
            [item["type"] for item in sink.items],
            ["beacon", "feat", "event", "range", "device_seen"],
        )
        self.assertEqual(sink.items[3]["chirper"], 3)
        self.assertEqual(sink.items[4]["devs"][0][1], "BLE_APPLE")
        self.assertTrue(all(item["t_host"] == 20 for item in sink.items))


class SimulatedFileTest(unittest.TestCase):
    def test_file_stands_in_for_the_serial_port(self):
        import tempfile
        from pathlib import Path

        sink = ListSink()
        errors = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gateway.txt"
            path.write_text(BEACON + "\n{not json\n", encoding="utf-8")
            accepted = read_simulated(path, sink, errors.append, now_ms=40)

        self.assertEqual(accepted, 1)
        self.assertEqual(sink.items[0]["src"], 3)
        self.assertEqual(len(errors), 1)


class ReconnectTest(unittest.TestCase):
    def test_unplug_is_logged_and_the_next_open_delivers_the_line(self):
        sink = ListSink()
        errors = []
        state = {"opens": 0}

        class Port:
            def __init__(self, generation):
                self.generation = generation
                self.reads = 0
                self.closed = False

            def readline(self):
                self.reads += 1
                if self.generation == 1:
                    raise OSError("unplugged")
                if self.reads == 1:
                    return (BEACON + "\n").encode()
                return b""

            def close(self):
                self.closed = True

        def open_port():
            state["opens"] += 1
            if state["opens"] > 3:
                raise AssertionError("reconnect did not stop")
            return Port(state["opens"])

        def stop():
            return len(sink.items) == 1

        run_port(open_port, sink, errors.append, now_ms=50, sleep=lambda _delay: None, stop=stop)

        self.assertEqual(sink.items[0]["type"], "beacon")
        self.assertEqual(state["opens"], 2)
        self.assertTrue(any("unplugged" in error for error in errors))


class HostClockTest(unittest.TestCase):
    def test_each_line_gets_its_own_arrival_time(self):
        sink = ListSink()
        times = iter([100, 250])

        accepted = read_lines([BEACON, FEAT], sink, lambda _error: None, now_ms=lambda: next(times))

        self.assertEqual(accepted, 2)
        self.assertEqual(sink.items[0]["t_host"], 100)
        self.assertEqual(sink.items[1]["t_host"], 250)


class EndpointTest(unittest.TestCase):
    def test_missing_port_is_an_error_rather_than_a_default_device(self):
        with self.assertRaises(ValueError) as caught:
            resolve_endpoint(port=None, baud=None, env={})
        self.assertNotIn("/dev/", str(caught.exception))

    def test_env_port_uses_the_contract_baud_unless_overridden(self):
        port, baud = resolve_endpoint(
            port=None,
            baud=None,
            env={"GATEWAY_PORT": "/dev/serial/by-id/usb-c5"},
        )
        self.assertEqual(port, "/dev/serial/by-id/usb-c5")
        self.assertEqual(baud, 921600)

        port, baud = resolve_endpoint(
            port=None,
            baud=None,
            env={"GATEWAY_PORT": "/dev/serial/by-id/usb-c5", "GATEWAY_BAUD": "115200"},
        )
        self.assertEqual(port, "/dev/serial/by-id/usb-c5")
        self.assertEqual(baud, 115200)


class CliTest(unittest.TestCase):
    def test_simulate_prints_the_observation_and_does_not_send_commands(self):
        import io
        import json
        import tempfile
        from pathlib import Path

        stdout = io.StringIO()
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lines.txt"
            path.write_text(BEACON + "\n", encoding="utf-8")
            code = main(["--simulate", str(path)], stdout=stdout, stderr=stderr, now_ms=lambda: 7)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["type"], "beacon")
        self.assertEqual(payload["t_host"], 7)
        self.assertNotIn("HAIL", stdout.getvalue() + stderr.getvalue())

    def test_serial_mode_opens_the_given_port_at_the_given_baud(self):
        import io

        seen = {}

        class Opened:
            def __init__(self, port, baudrate, timeout):
                self.port = port
                self.baudrate = baudrate
                self.timeout = timeout

        class FakeSerialModule:
            def Serial(self, port, baudrate, timeout):
                return Opened(port, baudrate, timeout)

        def fake_run(open_port, sink, log, now_ms, sleep, stop):
            seen["opened"] = open_port()
            seen["sink"] = sink

        code = main(
            ["--port", "/dev/serial/by-id/usb-c5", "--baud", "921600"],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            now_ms=lambda: 1,
            run=fake_run,
            serial_module=FakeSerialModule(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(seen["opened"].port, "/dev/serial/by-id/usb-c5")
        self.assertEqual(seen["opened"].baudrate, 921600)
        self.assertEqual(seen["opened"].timeout, 1)
        seen["sink"].accept({"type": "beacon"})


class FixtureTest(unittest.TestCase):
    def test_checked_in_sample_matches_the_contract_examples(self):
        from pathlib import Path

        sink = ListSink()
        errors = []
        path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sample_gateway.txt"
        accepted = read_simulated(path, sink, errors.append, now_ms=1)

        self.assertEqual(errors, [])
        self.assertEqual(accepted, 5)
        self.assertEqual(sink.items[4]["type"], "device_seen")

    def test_raw_mac_is_rejected(self):
        sink = ListSink()
        errors = []
        line = (
            '{"type":"device_seen","src":4,"seq":88,"hops":1,"rssi_last":-61,"t_ms":60000,'
            '"devs":[["aa:bb:cc:dd:ee:ff","BLE_APPLE",-52,1]]}'
        )
        accepted = read_lines([line, BEACON], sink, errors.append, now_ms=1)

        self.assertEqual(accepted, 1)
        self.assertEqual(sink.items[0]["type"], "beacon")
        self.assertTrue(any("hash" in error for error in errors))


class ModuleEntryTest(unittest.TestCase):
    def test_module_invocation_prints_a_simulated_line(self):
        import subprocess
        import sys

        completed = subprocess.run(
            [sys.executable, "-m", "fusion.serial_ingest", "--simulate", "tests/fixtures/sample_gateway.txt"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('"type":"beacon"', completed.stdout)
        self.assertIn('"type":"device_seen"', completed.stdout)
        self.assertNotIn("HAIL", completed.stdout)


class SplitChunkTest(unittest.TestCase):
    def test_a_line_split_across_reads_is_one_observation(self):
        sink = ListSink()
        errors = []
        payload = (BEACON + "\n").encode()
        chunks = [payload[:12], payload[12:], b""]

        class Port:
            def __init__(self):
                self.chunks = list(chunks)

            def readline(self):
                if not self.chunks:
                    return b""
                return self.chunks.pop(0)

            def close(self):
                return None

        run_port(
            lambda: Port(),
            sink,
            errors.append,
            now_ms=9,
            sleep=lambda _delay: None,
            stop=lambda: len(sink.items) == 1,
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(sink.items), 1)
        self.assertEqual(sink.items[0]["type"], "beacon")


if __name__ == "__main__":
    unittest.main()
