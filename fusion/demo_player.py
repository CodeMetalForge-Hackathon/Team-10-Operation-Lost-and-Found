"""Restart a simulated gateway script through the ingest path.

This player calls the same line parser as a serial session. It does not open a
port and it does not send HAIL, BLINK, RANGE, QUIET MODE, or any other command.
"""

import threading

from fusion.serial_ingest import accept_line


class DemoPlayer:
    def __init__(self, state, log, clock, script, keepalive=None):
        self.state = state
        self.log = log
        self.clock = clock
        self.script = list(script)
        self.keepalive = keepalive
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._generation = 0

    def start(self):
        return self._launch(reset=False)

    def stop(self):
        self._stop.set()

    def join(self, timeout=None):
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def replay(self):
        if not self.state.simulated:
            return _refused("live")
        launched = self._launch(reset=True)
        if not launched.get("ok"):
            return launched
        return {
            "ok": True,
            "mode": "simulation",
            "sends_hardware_commands": False,
        }

    def _launch(self, reset):
        with self._lock:
            old = self._thread
            self._stop.set()
        if old is not None and old.is_alive() and old is not threading.current_thread():
            old.join(timeout=2.0)
            if old.is_alive():
                return {
                    "ok": False,
                    "mode": "simulation",
                    "sends_hardware_commands": False,
                    "error": "The previous simulation player is still emitting. Replay was not applied.",
                }
        if reset:
            self.state.reset()
        with self._lock:
            self._generation += 1
            generation = self._generation
            self._stop = threading.Event()
            stop = self._stop
            self._thread = threading.Thread(
                target=self._run,
                args=(generation, stop),
                daemon=True,
                name="demo-player",
            )
            self._thread.start()
        return {"ok": True, "sends_hardware_commands": False}

    def _run(self, generation, stop):
        import time

        start = time.monotonic()
        for at, line in self.script:
            if not self._current(generation, stop):
                return
            remaining = at - (time.monotonic() - start)
            if remaining > 0 and stop.wait(remaining):
                return
            if not self._current(generation, stop):
                return
            accept_line(line, self.state, self.log, self.clock())
        if self.keepalive is None:
            return
        seq = 10
        while self._current(generation, stop):
            if stop.wait(2.0) or not self._current(generation, stop):
                return
            accept_line(self.keepalive(seq), self.state, self.log, self.clock())
            seq = (seq + 1) % 65536

    def _current(self, generation, stop):
        return not stop.is_set() and generation == self._generation


def _refused(mode):
    return {
        "ok": False,
        "mode": mode,
        "sends_hardware_commands": False,
        "error": (
            "Replay is only available in simulation mode. "
            "It does not reset a live gateway session and it does not send hardware commands."
        ),
    }
