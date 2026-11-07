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

Fusion does not exist in this repo yet. The boundary is one method:

```python
class ObservationSink:
    def accept(self, observation: dict) -> None:
        """One validated gateway object plus t_host. Not /ws state."""
```

`python -m fusion.serial_ingest` uses a stdout sink so a person can see the line. That stdout stream is a debug view, not the fusion API. When `fusion/server.py` exists, it should pass its own sink into `run_port` or `read_lines`. It should not scrape stdout, and it should not grow a second serial parser.

`/ws` is still unspecified. This reader does not open a socket and does not decide how a gateway line becomes dashboard state.
