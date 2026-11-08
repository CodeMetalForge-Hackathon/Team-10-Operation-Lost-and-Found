# Storage and processing

Checked after merging William's `153bab1` and `c69393f`.

## What the process does

```text
USB serial or TCP newline JSON or a recording file
        │
        ▼
fusion/serial_ingest.py     one parser, stamps t_host in milliseconds
        │
        ▼
fusion/state.py              in-memory live roster, stale after 6000 ms
        │
        ├── GET /state and /ws     current roster only
        └── fusion/store.py        append-only SQLite, if enabled
                │
                └── GET /history   old rows, marked historical
```

Before this change, nothing was written to disk except the committed `data/*.jsonl` files and whatever `tools/record_gateway.py` writes during a capture. Restarting the server dropped every node. Freshness was only the in-memory `t_host`. Gateway `gw` lines were kept in memory and replaced by the next one. The mesh de-duplicates `(src, seq)` before a forward. The host did not.

That was enough to show a live roster. It was not enough to look at a felt tap after a restart without calling it a new live event.

## What SQLite stores

Default file: `data/host.sqlite`. Git ignores `*.sqlite`. Pass `--no-store` to skip it.

Each accepted line is an insert. There is no unique key on `src` + `seq`, so a repeated delivery is kept and a later distinct event is not collapsed into it. The row stores:

- provenance: `live`, `recording`, or `simulation`
- message type, `src`, `seq`, `hops`, gateway id for `gw`
- host `t_host` in milliseconds and recorder `t_recorded_s` when the line had one
- the normalized JSON, including raw zeros and `-128` sentinels

Schema version is `1` in the `meta` table.

## What it does not do

- It does not reload rows into the live roster. A restart shows an empty roster until a new line arrives. `GET /history` still has the old rows, with `historical: true`.
- It does not estimate a position.
- It does not deduplicate mesh retries.
- `POST /demo/replay` clears the in-memory roster. It does not delete the database.
- The diagnostics list shows a few stored rows and says they are not new live detections. The main roster is still the websocket snapshot.

## Query

```bash
curl 'http://127.0.0.1:8000/history?limit=20&source=live&src=2'
```

`source` is optional. `src` is optional. `msg_type` is optional.
