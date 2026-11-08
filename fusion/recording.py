"""Play a recorded gateway file through the same line parser as serial."""

import json
import threading

from fusion.serial_ingest import accept_line, recorded_seconds_of


class RecordingPlayer:
    def __init__(self, state, log, clock, lines, speed=1.0, sleep=None, path=None):
        if speed <= 0:
            raise ValueError("speed must be positive")
        self.state = state
        self.log = log
        self.clock = clock
        self.lines = list(lines)
        self.speed = float(speed)
        self.sleep = sleep if sleep is not None else _sleep
        self.path = None if path is None else str(path)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def play(self):
        self.state.source = "recording"
        self.state.simulated = False
        accepted = 0
        self._mark("playing", accepted)
        previous = None
        for raw in self.lines:
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            text = text.strip()
            if not text:
                continue
            seconds = recorded_seconds_of(text)
            if previous is not None and seconds is not None:
                delay = (seconds - previous) / self.speed
                if delay > 0:
                    if self.sleep is _sleep:
                        if self._stop.wait(delay):
                            self._mark("ended", accepted)
                            return accepted
                    else:
                        self.sleep(delay)
            if seconds is not None:
                previous = seconds
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                self.log(f"{exc}: {text}")
                continue
            try:
                accepted += accept_line(text, self.state, self.log, self.clock())
            except (json.JSONDecodeError, ValueError) as exc:
                self.log(f"{exc}: {text}")
            self._mark("playing", accepted)
        self._mark("ended", accepted)
        return accepted

    def _mark(self, status, accepted):
        self.state.playback = {
            "status": status,
            "speed": self.speed,
            "path": self.path,
            "lines": accepted,
        }


def _sleep(delay):
    import time

    time.sleep(delay)
