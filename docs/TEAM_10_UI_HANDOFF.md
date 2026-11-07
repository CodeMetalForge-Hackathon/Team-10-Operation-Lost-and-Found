# Team 10 UI handoff

Operator page on `feat/operator-ui-polish`. The socket payload is still proposed `/ws` version 1. This note does not change the five gateway JSON types.

## Fields the page uses

From each `/ws` message: `v`, `simulated`, `t_host`, `localization_mode`, `stale_after_ms`, `nodes`, `links`, `devices`, `ranges`, `banner.possible_acoustic`, `banner.text`, `counts.nodes_active`, `counts.nodes_seen`, `counts.packets`, `counts.packets_per_s`, `counts.bytes_per_s`.

From a node: `id`, `status`, `last_t_host`, `seq`, `hops`, `rssi_last`, `batt_mv`, `floor_db`, `nbrs`, `latest_feat`, `evidence`, `search_priority`, `position`.

From evidence: `kind`, `t_ms`, `t_host`, `peak_db`, `voice_db`, `count`, `conf`.

From a device: `hash`, `kind`, `rssi_max`, `count`, `heard_by`, `t_host`.

From a range: `src`, `chirper`, `delay_us`, `snr_db`, `t_host`.

`position` null is shown as Not reported. It is not drawn as zero. `conf` is shown as an unsigned integer with an unknown scale. It is not a probability. `device_seen` stays a hash plus a kind. A neighbor RSSI is not a distance. `delay_us` is not metres.

## Event flow

`sim/demo.py` or the serial reader → `fusion.serial_ingest.accept_line` → `FusionState.accept` → `GET /ws` about twice a second → `ui/index.html`.

The page does not inject observations. Selection is kept across updates until that item leaves the snapshot. A socket close keeps the last snapshot and marks it cached. Reconnect renders the next server snapshot. It does not add a copy.

## New endpoints

`GET /demo` → `{available, simulated, mode, sends_hardware_commands}`.

`POST /demo/replay` resets retained observations and replays the built-in script through `accept_line`. Only a `--demo` process wires this. Live and `--simulate` return 409. `sends_hardware_commands` is false.

`POST /cmd`, `POST /anchor`, and `POST /baseline` are still 404.

## Controls

Available: filters, selection, technical details, diagnostics, and Replay demo when `/demo` says so.

Not on the page: HAIL, BLINK IDs, RANGE, QUIET MODE, BASELINE. No fake success.

## Known limitations

- No measured positions. The roster is not a map.
- A range line creates an observed node for its `src`. Node 2 can appear that way. `nodes_seen` is observed ids, not a deployed count.
- Evidence retained per node is the last 8 events. The timeline is that snapshot, not a full packet log.
- `conf` scale is not documented as a percentage.
- Replay is not safe to call against a live gateway, and the server refuses it.
- The socket URL is derived from `location.host`. Do not hardcode the laptop into a Pi build.

## Hardware and TAK

Serial reader: implemented, not verified on a board in this pass. TAK: not implemented. Localization: not implemented (`UNLOCALIZED` / Unavailable). Firmware and the Pi image are outside this page.

## Next integration test

Run `--demo`, confirm one tap on node 3, two device hashes heard by node 4, node 3 going stale while the tap remains, and Replay demo returning the cue count to 1 without a second copy. Then one real gateway line, if a board is on the cable, through `--gateway /dev/serial/by-id/...`, and confirm `simulated` is false and Replay demo is absent.
