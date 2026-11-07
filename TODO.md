# TODO (team decisions pending)

Open items from `docs/SENSORS.md`. Decide, then update `docs/ARCHITECTURE.md` §2 + `firmware/node/protocol.h` and log in `docs/DECISIONS.md`.

- [ ] **Grove Sound Sensor output type**: scope D0 at 16 kHz while clapping. Waveform → band energies + chirp ranging work. Envelope only → keep `rms_db`/`peak_db`; adopt **`-128` = "not available"** for `low_db`/`voice_db`/`high_db`? (proposed)
- [ ] **mmWave `RADAR_PRESENCE` encoding** (only if a radar gets fitted): `count` = distance in decimetres, `conf` = presence confidence? (proposed)
- [ ] **"Felt, not heard" taps**: when the SW-420 sees a tap rhythm but the mic doesn't, send `TAP_PATTERN` with `peak_db` ≈ node floor and `conf` ≤ 50? (proposed)
