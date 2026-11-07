# Gateway ingest boundary

This file is the adapter between the USB gateway and fusion. It is not a change to `docs/ARCHITECTURE.md`. William owns that contract. Do not treat this file as a second message format.

## What the reader accepts

Inbound only: one JSON object per line, as published in `docs/ARCHITECTURE.md` under "Gateway → host".

Accepted `type` values: `beacon`, `feat`, `event`, `range`, `device_seen`.

The reader adds `t_host`, which the architecture says the host adds. The contract does not specify the type. This reader uses integer Unix epoch milliseconds. That choice is local until the team writes it down.

Extra fields are passed through. They are not a new schema. `uptime_s` is in the over-the-air beacon and not in the JSON example, so it is not required.

## What the reader does not accept

- A raw MAC address. `device_seen` hashes in the published example are 8 hex characters. A colon-separated MAC is rejected.
- `cmd` or `chirp` JSON. Those types are over-the-air only. No gateway JSON example exists for them.
- Outbound commands. HAIL, BLINK, RANGE, QUIET MODE, and BASELINE are not sent. Their HTTP bodies are not agreed.

## Sink

Fusion now has a host on this branch: `fusion/state.py` plus `fusion/server.py`. The boundary is still one method. The server passes `FusionState` into `read_lines` / `run_port`. It does not scrape stdout and it does not parse serial a second time.

```python
class ObservationSink:
    def accept(self, observation: dict) -> None:
        """One validated gateway object plus t_host. Not the /ws payload."""
```

`python -m fusion.serial_ingest` still prints that object to stdout for debugging. `python -m fusion.server` is the dashboard path.

`/ws` version 1 is proposed in `docs/WS_CONTRACT.md`. It is not in `docs/ARCHITECTURE.md`. `POST /cmd`, `POST /anchor`, and `POST /baseline` are still not implemented.
