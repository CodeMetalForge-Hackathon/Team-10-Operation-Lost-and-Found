# Team 10 UI handoff

Operator page on `feat/evidence-review-screen`. The socket payload is still proposed `/ws` version 1. This note does not change the five gateway JSON types.

## What the page shows

Compact header: Operation Lost and Found, Operations overview, source, browser connection, sensor reporting, TAK.

Summary strip: sensors with cues, reporting, newest line, retained events, localization. Sensors with cues is `banner.possible_acoustic`. It is not an event count.

Evidence queue uses readable names. Raw kinds stay in the detail panel. Each acoustic row shows the sensor, evidence age, and whether that sensor is stale. Node freshness is `status` / `last_t_host`. Evidence age is `t_host` on the evidence row.

The timeline is host-receipt time by sensor. It is not a map. Circles are acoustic. Triangles are radio. Squares are other stored events. Repeated snapshots replace the points. They do not append.

## Fields the page uses

From each `/ws` message: `v`, `simulated`, `t_host`, `localization_mode`, `stale_after_ms`, `nodes`, `links`, `devices`, `ranges`, `banner.possible_acoustic`, `banner.text`, `counts.nodes_active`, `counts.nodes_seen`, `counts.acoustic_events`, `counts.packets`, `counts.packets_per_s`, `counts.bytes_per_s`.

From a node: `id`, `status`, `last_t_host`, `seq`, `hops`, `rssi_last`, `batt_mv`, `floor_db`, `nbrs`, `latest_feat`, `evidence`, `search_priority`, `position`.

From evidence: `kind`, `t_ms`, `t_host`, `peak_db`, `voice_db`, `count`, `conf`.

From a device: `hash`, `kind`, `rssi_max`, `count`, `heard_by`, `t_host`.

From a range: `src`, `chirper`, `delay_us`, `snr_db`, `t_host`.

`t_ms` is shown as an unsynchronized node clock. The chart does not use it as the axis.

`position` null is Not reported. It is not drawn as zero. `conf` is an unsigned integer with an unknown scale. It is not a probability and there is no gauge. `count` is a reported count, not a tap count. A neighbor RSSI is not a distance. `delay_us` is not metres.

## Event flow

`sim/demo.py` or the serial reader → `fusion.serial_ingest.accept_line` → `FusionState.accept` → `GET /ws` about twice a second → `ui/index.html` and `ui/review.js`.

The page does not inject observations. The first snapshot with evidence selects the newest acoustic cue, or another observation if there is no acoustic cue, only while the user has not chosen. Later snapshots do not replace that choice. Viewing is not an acknowledgment. A socket close keeps the last snapshot and marks ages cached. Reconnect renders the next server snapshot. It does not add a copy.

## Replay

`GET /demo` → `{available, simulated, mode, sends_hardware_commands}`.

`POST /demo/replay` resets retained demo observations and replays through `accept_line`. Only a `--demo` process wires this. Live and `--simulate` return 409. The page does not invent a session id. Until `counts.packets` drops, or the previous evidence keys are gone without the packet count growing, the note says the rows are still the previous demo run.

`POST /cmd`, `POST /anchor`, and `POST /baseline` are still 404.

## Controls

Available: filters, queue rows, sensor cards, timeline marks, chart window, technical details, diagnostics, and Replay demo when `/demo` says so.

Not on the page: HAIL, BLINK IDs, RANGE, QUIET MODE, BASELINE. No fake success.

## Assets

Local only. Versions are in `ui/vendor/PROVENANCE.md`. ECharts 6.1.0. `@tabler/core` 1.7.3, used for badge, button, and list-group. `@tabler/icons` 3.50.0 outline SVGs. No CDN and no remote font.

## Known limitations

- No measured positions. The roster is not a map.
- A range line creates an observed node for its `src`. Node 2 can appear that way. `nodes_seen` is observed ids, not a deployed count.
- Evidence retained per node is the last 8 events. The chart is that snapshot, not a full packet log.
- `conf` scale is not a percentage.
- Replay refuses a live gateway session.
- The socket URL is derived from `location.host`. Do not hardcode the laptop into a Pi build.
- TAK and localization are not implemented.

## Next integration dependency

One real gateway line, if a board is on the cable, through `--gateway /dev/serial/by-id/...`, and confirm `simulated` is false and Replay demo is absent. Firmware and the Pi image are outside this page.
