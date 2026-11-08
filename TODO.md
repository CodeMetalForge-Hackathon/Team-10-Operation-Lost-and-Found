# TODO (team decisions pending)

Open items from `docs/SENSORS.md`. Decide, then update `docs/ARCHITECTURE.md` §2 + `firmware/node/protocol.h` and log in `docs/DECISIONS.md`.

- [x] **Grove Sound Sensor output type** (DONE: clipped waveform; band fields = -128; see ARCHITECTURE.md §2): scope D0 at 16 kHz while clapping. Waveform → band energies + chirp ranging work. Envelope only → keep `rms_db`/`peak_db`; adopt **`-128` = "not available"** for `low_db`/`voice_db`/`high_db`? (proposed)
- [ ] **mmWave `RADAR_PRESENCE` encoding** (only if a radar gets fitted): `count` = distance in decimetres, `conf` = presence confidence? (proposed)
- [x] **"Felt, not heard" taps** (DONE: built as proposed, plus every SW-420 burst is sent as `VIBRATION`): when the SW-420 sees a tap rhythm but the mic doesn't, send `TAP_PATTERN` with `peak_db` ≈ node floor and `conf` ≤ 50? (proposed)

## Open-source release

- [ ] **Make the project properly open source (Apache-2.0).** `LICENSE` (Apache-2.0 text) has been in the repo since the initial commit, but nothing else is done yet:
  - say "Licensed under Apache-2.0, see `LICENSE`" in `README.md`;
  - add a `NOTICE` file (Apache §4d) with the project copyright (team names, 2026) and credit for the bundled third-party code: ECharts (Apache-2.0) and Tabler core/icons (MIT). Their licence texts are already in `ui/vendor/licenses/`;
  - check that every other dependency (`requirements.txt`, the arduino-esp32 core, Arduino libraries) is compatible with Apache-2.0 and listed in the README's "what existed before" section;
  - optional: add `SPDX-License-Identifier: Apache-2.0` headers to our own `.py`, `.ino`, `.h` and `.js` files;
  - confirm Code Metal Forge's IP rules let the team release under Apache-2.0, and log the decision in `docs/DECISIONS.md`.
