# TODO (team decisions pending)

Open items from `docs/SENSORS.md`. Decide, then update `docs/ARCHITECTURE.md` §2 + `firmware/node/protocol.h` and log in `docs/DECISIONS.md`.

- [x] **Grove Sound Sensor output type** (DONE: clipped waveform; band fields = -128; see ARCHITECTURE.md §2): scope D0 at 16 kHz while clapping. Waveform → band energies + chirp ranging work. Envelope only → keep `rms_db`/`peak_db`; adopt **`-128` = "not available"** for `low_db`/`voice_db`/`high_db`? (proposed)
- [ ] **mmWave `RADAR_PRESENCE` encoding** (only if a radar gets fitted): `count` = distance in decimetres, `conf` = presence confidence? (proposed)
- [x] **"Felt, not heard" taps** (DONE: built as proposed, plus every SW-420 burst is sent as `VIBRATION`): when the SW-420 sees a tap rhythm but the mic doesn't, send `TAP_PATTERN` with `peak_db` ≈ node floor and `conf` ≤ 50? (proposed)
