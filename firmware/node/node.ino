// node.ino: Team 10 mesh firmware (XIAO ESP32-C5 field nodes, XIAO ESP32-S3 Plus gateway / drone bridge)
//
// STEP 1 (no mic needed): ESP-NOW flooding mesh + BEACON with neighbor RSSI + gateway JSON lines + CMD downlink.
// STEP 2 (no mic needed): set ENABLE_BLE_SCAN 1 -> passive BLE scan -> DEVICE_SEEN.
// STEP 3 (field nodes): Grove Sound Sensor (D0, DMA ADC 16 kHz) + SW-420 (D1) + Grove Buzzer (D4)
//         -> FEAT 1 Hz, EVENT LOUD / VIBRATION / VOICE_LIKE (sustained sound) / TAP_PATTERN, HAIL beeps.
//         Policy: report every sound and movement with its strength; fusion decides the weight.
//
// Before flashing EACH board, edit ROLE and NODE_ID below.
//   Field nodes:  ROLE_NODE,         NODE_ID 1..5
//   Gateway:      ROLE_GATEWAY,      NODE_ID 0
//   Drone bridge: ROLE_DRONE_BRIDGE, NODE_ID 200
// Arduino IDE: board "XIAO_ESP32C5" / "XIAO_ESP32S3", esp32 core >= 3.3, Tools > USB CDC On Boot: Enabled.
//
// Gateway serial commands (type in Serial Monitor, newline-terminated):
//   CMD PING 0 255 | CMD BLINK 0 255 | CMD HAIL 0 255 | CMD TXPOWER 8 255 | CMD SCAN 2 255 | CMD SALT 1234 255

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include "protocol.h"

// Role constants (do not edit)
#define ROLE_NODE 1
#define ROLE_GATEWAY 2
#define ROLE_DRONE_BRIDGE 3

// ======================= EDIT PER BOARD (only these two lines) =======================
// (or leave as-is and flash with tools/flash.py, which passes -DROLE=.. -DNODE_ID=..)
#ifndef ROLE
#define ROLE ROLE_NODE   // ROLE_NODE | ROLE_GATEWAY | ROLE_DRONE_BRIDGE
#endif
#ifndef NODE_ID
#define NODE_ID 2        // nodes 1..5, gateway 0, drone 200
#endif
// =====================================================================================

static_assert(ROLE_NODE != ROLE_GATEWAY && ROLE_GATEWAY != ROLE_DRONE_BRIDGE, "role constants were edited");

#ifndef ENABLE_BLE_SCAN
#define ENABLE_BLE_SCAN 0     // STEP 2: set to 1 on field nodes
#endif
#define ESPNOW_CHANNEL 1
#define START_TTL 4
#define BEACON_PERIOD_MS 2000
#define NEIGHBOR_TIMEOUT_MS 10000
#define DEVICE_WINDOW_MS 10000

#ifdef LED_BUILTIN
#define LED_PIN LED_BUILTIN   // later: external bright LED on D5
#else
#define LED_PIN -1
#endif

#if ENABLE_BLE_SCAN
#include <BLEDevice.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#endif

static const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
static const bool IS_PRINTER = (ROLE == ROLE_GATEWAY || ROLE == ROLE_DRONE_BRIDGE);
static const bool FORWARDS_UPLINK = (ROLE == ROLE_NODE || ROLE == ROLE_DRONE_BRIDGE);

// ---------- receive queue (callback runs in WiFi task; keep it tiny) ----------
struct RxItem {
  uint8_t mac[6];
  int8_t rssi;
  uint8_t len;
  uint8_t data[PKT_MAX_LEN];
};
static QueueHandle_t rxQueue;
static volatile uint32_t rxDropped = 0;

void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
  if (len < (int)sizeof(PktHeader) || len > PKT_MAX_LEN || data[0] != PKT_MAGIC) return;
  RxItem it;
  memcpy(it.mac, info->src_addr, 6);
  it.rssi = info->rx_ctrl ? info->rx_ctrl->rssi : 0;
  it.len = (uint8_t)len;
  memcpy(it.data, data, len);
  if (xQueueSend(rxQueue, &it, 0) != pdTRUE) rxDropped++;
}

// ---------- de-duplication ----------
static uint32_t seenRing[64];
static uint8_t seenIdx = 0;
bool alreadySeen(uint8_t src, uint16_t seq) {
  uint32_t key = 0x01000000u | ((uint32_t)src << 16) | seq;
  for (uint32_t k : seenRing) if (k == key) return true;
  seenRing[seenIdx] = key;
  seenIdx = (seenIdx + 1) % 64;
  return false;
}

// ---------- neighbor table (RSSI of direct transmissions) ----------
struct Neighbor {
  bool used;
  uint8_t mac[6];
  int id;  // -1 until learned from a hops==0 packet
  float rssi;
  uint32_t lastMs;
};
static Neighbor nbrs[MAX_NEIGHBORS];

void updateNeighbor(const RxItem &it, const PktHeader &h) {
  Neighbor *slot = nullptr, *freeSlot = nullptr, *oldest = &nbrs[0];
  for (auto &n : nbrs) {
    if (n.used && memcmp(n.mac, it.mac, 6) == 0) { slot = &n; break; }
    if (!n.used && !freeSlot) freeSlot = &n;
    if (n.lastMs < oldest->lastMs) oldest = &n;
  }
  if (!slot) {
    slot = freeSlot ? freeSlot : oldest;
    memset(slot, 0, sizeof(*slot));
    slot->used = true;
    memcpy(slot->mac, it.mac, 6);
    slot->id = -1;
    slot->rssi = it.rssi;
  }
  if (h.hops == 0) slot->id = h.src;  // transmitter == origin
  slot->rssi = 0.7f * slot->rssi + 0.3f * it.rssi;
  slot->lastMs = millis();
}

// ---------- sending ----------
static uint16_t txSeq = 0;
static SemaphoreHandle_t txMutex;  // the audio task also sends (events must not wait for a BLE scan)
// repeats > 1: resend the identical packet (same seq) so receivers de-dup it. Used for CMDs,
// because ESP-NOW broadcast has no ACK/retry and a lost command is worse than a duplicate.
void sendPacket(uint8_t type, const void *payload, size_t plen, int repeats = 1) {
  uint8_t buf[PKT_MAX_LEN];
  if (sizeof(PktHeader) + plen > PKT_MAX_LEN) return;
  xSemaphoreTake(txMutex, portMAX_DELAY);
  PktHeader h{PKT_MAGIC, type, (uint8_t)NODE_ID, START_TTL, 0, txSeq++, 0};
  memcpy(buf, &h, sizeof(h));
  memcpy(buf + sizeof(h), payload, plen);
  alreadySeen(h.src, h.seq);  // never re-forward our own packet
  xSemaphoreGive(txMutex);
  for (int i = 0; i < repeats; i++) {
    if (i) delay(15 + random(0, 15));
    esp_now_send(BCAST, buf, sizeof(h) + plen);
  }
}

// Rebroadcasts are delayed by random jitter so neighbors don't collide.
struct Pending {
  bool used;
  uint32_t dueMs;
  uint8_t len;
  uint8_t data[PKT_MAX_LEN];
};
static Pending pending[16];

void scheduleForward(const RxItem &it) {
  for (auto &p : pending) {
    if (p.used) continue;
    p.used = true;
    p.dueMs = millis() + random(0, 21);
    p.len = it.len;
    memcpy(p.data, it.data, it.len);
    PktHeader *h = (PktHeader *)p.data;
    h->ttl--;
    h->hops++;
    return;
  }
}

void serviceForwards() {
  uint32_t now = millis();
  for (auto &p : pending) {
    if (p.used && (int32_t)(now - p.dueMs) >= 0) {
      esp_now_send(BCAST, p.data, p.len);
      p.used = false;
    }
  }
}

// ---------- JSON output (gateway / drone bridge) ----------
const char *kindName(uint8_t k) {
  switch (k) {
    case EV_LOUD: return "LOUD";
    case EV_TAP_PATTERN: return "TAP_PATTERN";
    case EV_VOICE_LIKE: return "VOICE_LIKE";
    case EV_RADAR_PRESENCE: return "RADAR_PRESENCE";
    case EV_GAS: return "GAS";
    case EV_VIBRATION: return "VIBRATION";
    case EV_MOVED: return "MOVED";
    default: return "UNKNOWN";
  }
}
const char *devKindName(uint8_t k) {
  switch (k) {
    case DEV_BLE_OTHER: return "BLE_OTHER";
    case DEV_BLE_APPLE: return "BLE_APPLE";
    case DEV_BLE_FINDMY: return "BLE_FINDMY";
    case DEV_BLE_GOOGLE: return "BLE_GOOGLE";
    case DEV_WIFI_PROBE: return "WIFI_PROBE";
    default: return "UNKNOWN";
  }
}

void printJson(const RxItem &it) {
  const PktHeader &h = *(const PktHeader *)it.data;
  const uint8_t *p = it.data + sizeof(PktHeader);
  size_t plen = it.len - sizeof(PktHeader);
  char common[96];
  snprintf(common, sizeof(common), "\"src\":%u,\"seq\":%u,\"hops\":%u,\"rssi_last\":%d",
           h.src, h.seq, h.hops, it.rssi);

  switch (h.type) {
    case PKT_BEACON: {
      if (plen < 6) return;
      const BeaconPayload *b = (const BeaconPayload *)p;
      uint8_t n = min<uint8_t>(b->n, (plen - 6) / sizeof(NeighborEntry));
      Serial.printf("{\"type\":\"beacon\",%s,\"batt_mv\":%u,\"uptime_s\":%u,\"floor_db\":%d,\"nbrs\":[",
                    common, b->batt_mv, b->uptime_s, b->floor_db);
      for (uint8_t i = 0; i < n; i++)
        Serial.printf("%s[%u,%d]", i ? "," : "", b->nbrs[i].id, b->nbrs[i].rssi);
      Serial.print("]}\n");
      break;
    }
    case PKT_FEAT: {
      if (plen < sizeof(FeatPayload)) return;
      const FeatPayload *f = (const FeatPayload *)p;
      Serial.printf("{\"type\":\"feat\",%s,\"t_ms\":%lu,\"rms_db\":%d,\"low_db\":%d,\"voice_db\":%d,\"high_db\":%d,\"peak_db\":%d}\n",
                    common, (unsigned long)f->t_ms, f->rms_db, f->low_db, f->voice_db, f->high_db, f->peak_db);
      break;
    }
    case PKT_EVENT: {
      if (plen < sizeof(EventPayload)) return;
      const EventPayload *e = (const EventPayload *)p;
      Serial.printf("{\"type\":\"event\",%s,\"t_ms\":%lu,\"kind\":\"%s\",\"peak_db\":%d,\"voice_db\":%d,\"count\":%u,\"conf\":%u}\n",
                    common, (unsigned long)e->t_ms, kindName(e->kind), e->peak_db, e->voice_db, e->count, e->conf);
      break;
    }
    case PKT_RANGE: {
      if (plen < sizeof(RangePayload)) return;
      const RangePayload *r = (const RangePayload *)p;
      Serial.printf("{\"type\":\"range\",%s,\"chirper\":%u,\"delay_us\":%lu,\"snr_db\":%d}\n",
                    common, r->chirper, (unsigned long)r->delay_us, r->snr_db);
      break;
    }
    case PKT_DEVICE_SEEN: {
      if (plen < 5) return;
      const DeviceSeenPayload *d = (const DeviceSeenPayload *)p;
      uint8_t n = min<uint8_t>(d->n, (plen - 5) / sizeof(DeviceEntry));
      Serial.printf("{\"type\":\"device_seen\",%s,\"t_ms\":%lu,\"devs\":[", common, (unsigned long)d->t_ms);
      for (uint8_t i = 0; i < n; i++)
        Serial.printf("%s[\"%08lx\",\"%s\",%d,%u]", i ? "," : "", (unsigned long)d->devs[i].hash,
                      devKindName(d->devs[i].kind), d->devs[i].rssi_max, d->devs[i].count);
      Serial.print("]}\n");
      break;
    }
    default:
      break;  // CHIRP / CMD echoes are not printed
  }
}

// ---------- commands ----------
static int blinkToggles = 0;
static uint32_t nextBlinkMs = 0;
static bool ledOn = false;
static uint32_t nextBeaconMs = 0;
static int scanSeconds = 2;
static uint32_t salt = 0x5EED;
static int8_t txPowerQdbm = -1;  // last applied tx power (0.25 dBm units), -1 = default
static volatile bool hailRequest = false;  // set by CMD_HAIL, served by the audio task (beeps)
static volatile float audioFloorDb = 0;    // mic noise floor, dBFS (0 until the audio task has run)

// Gateway-held mesh settings, re-broadcast periodically so rebooted / late nodes converge.
// -1 = never set (nodes keep their defaults).
#define CONFIG_REBROADCAST_MS 15000
static int16_t cfgTxPower = -1, cfgScan = -1, cfgSalt = -1;

void setLed(bool on) {
  if (LED_PIN < 0) return;
  ledOn = on;
  digitalWrite(LED_PIN, on ? HIGH : LOW);
}

void handleCmd(const CmdPayload &c) {
  if (c.target != 255 && c.target != NODE_ID) return;
  switch (c.cmd) {
    case CMD_PING: nextBeaconMs = millis(); break;
    case CMD_BLINK_ID: blinkToggles = 2 * (NODE_ID ? NODE_ID : 1); break;
    case CMD_HAIL:
      Serial.println("# HAIL received: beeping");
      hailRequest = true;
      blinkToggles = 10;
      break;
    case CMD_SET_TX_POWER: {  // idempotent: also arrives every 15 s via config re-broadcast
      int8_t p = constrain(c.arg, 8, 84);
      if (p != txPowerQdbm) {
        esp_wifi_set_max_tx_power(p);
        txPowerQdbm = p;
        Serial.printf("# tx power set to %.2f dBm\n", p * 0.25f);
      }
      break;
    }
    case CMD_SET_SCAN: {
      int s = constrain(c.arg, 0, 9);
      if (s != scanSeconds) Serial.printf("# BLE scan seconds per window: %d\n", s);
      scanSeconds = s;
      break;
    }
    case CMD_SET_SALT: salt = (uint32_t)(uint16_t)c.arg; break;
    default: break;
  }
}

// Gateway: parse "CMD <NAME> <arg> <target>" from USB serial and flood it.
void readSerialCommands() {
  static String line;
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch != '\n' && ch != '\r') { line += ch; continue; }
    line.trim();
    if (line.startsWith("CMD ")) {
      char name[16] = {0};
      int arg = 0, target = 255;
      sscanf(line.c_str() + 4, "%15s %d %d", name, &arg, &target);
      CmdPayload c{0, (int16_t)arg, (uint8_t)target};
      String n(name);
      n.toUpperCase();
      if (n == "HAIL") c.cmd = CMD_HAIL;
      else if (n == "BLINK") c.cmd = CMD_BLINK_ID;
      else if (n == "RANGE") c.cmd = CMD_START_RANGING;
      else if (n == "TXPOWER") c.cmd = CMD_SET_TX_POWER;
      else if (n == "RATE") c.cmd = CMD_SET_RATE;
      else if (n == "PING") c.cmd = CMD_PING;
      else if (n == "SCAN") c.cmd = CMD_SET_SCAN;
      else if (n == "SALT") c.cmd = CMD_SET_SALT;
      if (c.cmd) {
        sendPacket(PKT_CMD, &c, sizeof(c), 3);
        Serial.printf("# sent CMD %s arg=%d target=%d\n", name, arg, target);
        if (target == 255) {  // remember mesh-wide settings for periodic re-broadcast
          if (c.cmd == CMD_SET_TX_POWER) cfgTxPower = arg;
          else if (c.cmd == CMD_SET_SCAN) cfgScan = arg;
          else if (c.cmd == CMD_SET_SALT) cfgSalt = arg;
        }
      } else {
        Serial.printf("# unknown command %s\n", name);
      }
    }
    line = "";
  }
}

// ---------- beacon ----------
void sendBeacon() {
  BeaconPayload b{};
  b.batt_mv = 0;  // TODO: read XIAO C5 battery-sense pin (check schematic)
  b.uptime_s = (uint16_t)min<uint32_t>(millis() / 1000, 65535);
  b.floor_db = (int8_t)lroundf(audioFloorDb);  // mic noise floor, dBFS (0 on gateway / before warm-up)
  uint32_t now = millis();
  for (auto &n : nbrs) {
    if (!n.used || n.id < 0 || now - n.lastMs > NEIGHBOR_TIMEOUT_MS) continue;
    b.nbrs[b.n++] = {(uint8_t)n.id, (int8_t)lroundf(n.rssi)};
    if (b.n >= MAX_NEIGHBORS) break;
  }
  sendPacket(PKT_BEACON, &b, 6 + b.n * sizeof(NeighborEntry));
}

// ---------- BLE device scan (STEP 2) ----------
#if ENABLE_BLE_SCAN
struct DevAgg { uint32_t hash; uint8_t kind; int8_t rssiMax; uint8_t count; };
#define DEV_TABLE 96
static DevAgg devTable[DEV_TABLE];
static int devCount = 0;
static uint32_t devWindowStart = 0, nextScanMs = 0;

uint32_t fnv1a(const char *s, uint32_t seed) {
  uint32_t h = 2166136261u ^ seed;
  while (*s) { h ^= (uint8_t)*s++; h *= 16777619u; }
  return h;
}

void addDevice(uint32_t hash, uint8_t kind, int rssi) {
  for (int i = 0; i < devCount; i++) {
    if (devTable[i].hash == hash) {
      devTable[i].rssiMax = max<int>(devTable[i].rssiMax, rssi);
      if (devTable[i].count < 255) devTable[i].count++;
      if (kind > devTable[i].kind) devTable[i].kind = kind;
      return;
    }
  }
  if (devCount < DEV_TABLE) {
    devTable[devCount++] = {hash, kind, (int8_t)rssi, 1};
    return;
  }
  // Table full (crowded venue): evict the weakest entry if this device is stronger,
  // so nearby devices (the ones that matter) are never dropped for distant ones.
  int weakest = 0;
  for (int i = 1; i < devCount; i++)
    if (devTable[i].rssiMax < devTable[weakest].rssiMax) weakest = i;
  if (rssi > devTable[weakest].rssiMax) devTable[weakest] = {hash, kind, (int8_t)rssi, 1};
}

void runBleScan() {
  if (scanSeconds <= 0) return;
  BLEScan *scan = BLEDevice::getScan();
  BLEScanResults *res = scan->start(scanSeconds, false);  // blocking; rxQueue buffers ESP-NOW meanwhile
  for (int i = 0; res && i < res->getCount(); i++) {
    BLEAdvertisedDevice d = res->getDevice(i);
    if (d.getRSSI() < -80) continue;  // too weak to be near this node; keeps the table for nearby devices
    uint8_t kind = DEV_BLE_OTHER;
    if (d.haveManufacturerData()) {
      auto md = d.getManufacturerData();
      if (md.length() >= 2 && (uint8_t)md[0] == 0x4C && (uint8_t)md[1] == 0x00) {
        kind = (md.length() >= 3 && (uint8_t)md[2] == 0x12) ? DEV_BLE_FINDMY : DEV_BLE_APPLE;
      }
    }
    if (kind == DEV_BLE_OTHER && d.haveServiceData() && d.getServiceDataUUID().equals(BLEUUID((uint16_t)0xFE2C)))
      kind = DEV_BLE_GOOGLE;
    addDevice(fnv1a(d.getAddress().toString().c_str(), salt), kind, d.getRSSI());
  }
  scan->clearResults();
}

void flushDevices() {
  DeviceSeenPayload p{};
  p.t_ms = millis();
  // pick the strongest MAX_DEVICES
  static bool taken[DEV_TABLE];
  memset(taken, 0, sizeof(taken));
  while (p.n < MAX_DEVICES) {
    int best = -1;
    for (int i = 0; i < devCount; i++)
      if (!taken[i] && (best < 0 || devTable[i].rssiMax > devTable[best].rssiMax)) best = i;
    if (best < 0) break;
    taken[best] = true;
    p.devs[p.n++] = {devTable[best].hash, devTable[best].kind, devTable[best].rssiMax, devTable[best].count};
  }
  if (p.n) sendPacket(PKT_DEVICE_SEEN, &p, 5 + p.n * sizeof(DeviceEntry));
  Serial.printf("# DEVICE_SEEN window: %d unique, sent %u\n", devCount, p.n);
  devCount = 0;
}
#endif

// ---------- sensors: sound, SW-420, buzzer (field nodes only, STEP 3) ----------
// Measured on N2 (docs/HARDWARE.md): the sound sensor output is clipped at both ends at 3V3, the
// SW-420 has no false triggers at rest but rings for up to ~1.5 s after a hard hit.
// Levels are dBFS relative to 2048 counts, from the mean absolute deviation around a slow average
// (robust to the missing bottom half of the waveform).
#if ROLE == ROLE_NODE
#include "esp_adc/adc_continuous.h"

#define PIN_SOUND D0
#define PIN_SW420 D1
#define PIN_BUZZER D4
#define AUDIO_FS 16000
#define FRAME_SAMPLES 160            // 10 ms frames
#define FULL_SCALE 2048.0f
#define CLIP_LO 8
#define CLIP_HI 1850
#define ONSET_DB 10.0f               // onset: frame >= floor + 10 dB ...
#define RISE_DB 6.0f                 // ... and >= 6 dB above the previous frame
#define ONSET_REFRACTORY_MS 100
#define LOUD_HOLD_MS 250             // onsets within 250 ms merge into one LOUD (keeps the strongest)
#define SUSTAIN_DB 6.0f              // sustained sound: >= floor + 6 dB ...
#define SUSTAIN_GAP_MS 150           // ... allowing gaps up to 150 ms (syllables) ...
#define SUSTAIN_MIN_MS 400           // ... for >= 400 ms -> VOICE_LIKE, repeated every 2 s
#define SUSTAIN_REPEAT_MS 2000
#define SW_QUIET_MS 300              // SW-420: a burst ends after 300 ms without edges
#define TAP_MIN_GAP_MS 150
#define TAP_MAX_GAP_MS 1500
#define TAP_MERGE_MS 120             // a mic onset and an SW-420 burst this close = one tap
#define BUZZ_HZ 2300
#define HAIL_BEEPS 3
#define HAIL_ON_MS 150
#define HAIL_PERIOD_MS 300
#define HAIL_BLANK_MS 2500           // after our HAIL ends, ignore everything for 2.5 s (other nodes beep late)

static adc_continuous_handle_t adcHandle = nullptr;
static volatile uint32_t blankUntilMs = 0;
static volatile uint32_t swEdges = 0, swLastEdgeMs = 0, swBurstStartMs = 0;
static uint32_t stLoud = 0, stFelt = 0, stSus = 0, stPat = 0, stOverruns = 0;
static float lastLevelDb = -99;

void IRAM_ATTR onSw420() {
  uint32_t now = millis();
  if (now - swLastEdgeMs > SW_QUIET_MS) swBurstStartMs = now;
  swLastEdgeMs = now;
  swEdges++;
}

static inline bool blanked(uint32_t now) { return (int32_t)(now - blankUntilMs) < 0; }
static inline int8_t dbToI8(float db) { return (int8_t)constrain(lroundf(db), -127, 0); }

void emitEvent(uint8_t kind, uint32_t tms, float peakDb, int8_t v2, uint32_t count, int conf) {
  EventPayload e{tms, kind, dbToI8(peakDb), v2, (uint8_t)min<uint32_t>(count, 255), (uint8_t)constrain(conf, 0, 100)};
  sendPacket(PKT_EVENT, &e, sizeof(e));
  Serial.printf("# EVENT %s t=%lu peak=%d v2=%d count=%u conf=%u floor=%.1f\n", kindName(kind),
                (unsigned long)tms, e.peak_db, e.voice_db, e.count, e.conf, audioFloorDb);
}

// level history (2 s of 10 ms frames) so SW-420 bursts can look up how loud the mic heard them
static float lvlRing[200];
static uint32_t lvlRingMs[200];
static int lvlIdx = 0;
float micPeakAround(uint32_t t, uint32_t before, uint32_t after) {
  float pk = -99;
  for (int i = 0; i < 200; i++)
    if (lvlRingMs[i] && lvlRingMs[i] + before >= t && lvlRingMs[i] <= t + after) pk = max(pk, lvlRing[i]);
  return pk;
}

// tap candidates for rhythm detection: mic onsets and SW-420 bursts, merged when close in time
struct TapCand { uint32_t ms; float lvl; bool felt, heard; };
static TapCand taps[16];
static int nTaps = 0;
static uint32_t firstTapMs = 0;

void addTap(uint32_t ms, float lvl, bool felt, bool heard) {
  for (int i = 0; i < nTaps; i++) {
    if ((int32_t)(ms - taps[i].ms) <= TAP_MERGE_MS && (int32_t)(taps[i].ms - ms) <= TAP_MERGE_MS) {
      taps[i].felt |= felt; taps[i].heard |= heard; taps[i].lvl = max(taps[i].lvl, lvl);
      return;
    }
  }
  if (nTaps == 16) return;
  int pos = nTaps;  // keep sorted by time (SW-420 bursts arrive late with an earlier timestamp)
  while (pos > 0 && (int32_t)(taps[pos - 1].ms - ms) > 0) { taps[pos] = taps[pos - 1]; pos--; }
  taps[pos] = {ms, lvl, felt, heard};
  if (nTaps++ == 0) firstTapMs = ms;
}

// Emit TAP_PATTERN for every run of >= 2 taps with gaps of 150..1500 ms, then clear.
void flushTaps() {
  int i = 0;
  while (i < nTaps) {
    int j = i;
    while (j + 1 < nTaps) {
      uint32_t g = taps[j + 1].ms - taps[j].ms;
      if (g < TAP_MIN_GAP_MS || g > TAP_MAX_GAP_MS) break;
      j++;
    }
    int n = j - i + 1;
    if (n >= 2) {
      int felt = 0, heard = 0; float pk = -99, gs = 0, gs2 = 0;
      for (int k = i; k <= j; k++) {
        felt += taps[k].felt; heard += taps[k].heard; pk = max(pk, taps[k].lvl);
        if (k > i) { float g = taps[k].ms - taps[k - 1].ms; gs += g; gs2 += g * g; }
      }
      float mean = gs / (n - 1), cv = n > 2 ? sqrtf(max(0.0f, gs2 / (n - 1) - mean * mean)) / mean : 1;
      int conf = 30 + 10 * min(n, 5) + (felt * 2 >= n ? 20 : 0) + (cv < 0.3f ? 15 : 0);
      float peak = pk;
      if (!heard) { conf = min(conf, 50); peak = audioFloorDb; }  // "felt through the structure, not heard"
      emitEvent(EV_TAP_PATTERN, taps[i].ms, peak, -128, n, conf);
      stPat++;
    }
    i = j + 1;
  }
  nTaps = 0;
}

bool audioInit() {
  adc_continuous_handle_cfg_t hcfg = {};
  hcfg.max_store_buf_size = FRAME_SAMPLES * SOC_ADC_DIGI_RESULT_BYTES * 16;
  hcfg.conv_frame_size = FRAME_SAMPLES * SOC_ADC_DIGI_RESULT_BYTES;
  if (adc_continuous_new_handle(&hcfg, &adcHandle) != ESP_OK) return false;
  adc_unit_t unit; adc_channel_t ch;
  if (adc_continuous_io_to_channel(PIN_SOUND, &unit, &ch) != ESP_OK) return false;
  adc_digi_pattern_config_t pat = {};
  pat.atten = ADC_ATTEN_DB_12;
  pat.channel = ch & 0x7;
  pat.unit = unit;
  pat.bit_width = SOC_ADC_DIGI_MAX_BITWIDTH;
  adc_continuous_config_t cfg = {};
  cfg.pattern_num = 1;
  cfg.adc_pattern = &pat;
  cfg.sample_freq_hz = AUDIO_FS;
  cfg.conv_mode = ADC_CONV_SINGLE_UNIT_1;
  cfg.format = ADC_DIGI_OUTPUT_FORMAT_TYPE2;
  if (adc_continuous_config(adcHandle, &cfg) != ESP_OK) return false;
  return adc_continuous_start(adcHandle) == ESP_OK;
}

void audioTask(void *) {
  static uint8_t buf[FRAME_SAMPLES * SOC_ADC_DIGI_RESULT_BYTES];
  static uint16_t s[FRAME_SAMPLES];
  int fill = 0;
  uint32_t frames = 0;
  float dc = 0, floorDb = -40, prevDb = -99;
  // LOUD aggregation
  bool loudOn = false; uint32_t loudStart = 0, loudN = 0; float loudPk = -99;
  uint32_t lastOnsetMs = 0;
  // sustained-sound episode
  bool susOn = false, susSent = false; uint32_t susStart = 0, susLast = 0, susSentMs = 0; float susPk = -99, susSum = 0; uint32_t susN = 0;
  // FEAT accumulation
  float featMad = 0, featPk = -99; uint32_t featN = 0, nextFeatMs = millis() + 1000;
  // SW-420 burst tracking
  bool swOn = false; uint32_t swStartEdges = 0, swStart = 0;
  // HAIL
  bool hailOn = false, buzzOn = false; uint32_t hailStart = 0;

  for (;;) {
    uint32_t got = 0;
    esp_err_t r = adc_continuous_read(adcHandle, buf, sizeof(buf), &got, 20);
    uint32_t now = millis();
    if (r == ESP_OK) {
      for (uint32_t i = 0; i + SOC_ADC_DIGI_RESULT_BYTES <= got; i += SOC_ADC_DIGI_RESULT_BYTES) {
        const adc_digi_output_data_t *d = (const adc_digi_output_data_t *)&buf[i];
        s[fill++] = d->type2.data;
        if (fill < FRAME_SAMPLES) continue;
        fill = 0;
        // ---- one 10 ms frame ----
        uint32_t sum = 0;
        for (int k = 0; k < FRAME_SAMPLES; k++) sum += s[k];
        float mean = (float)sum / FRAME_SAMPLES;
        dc = frames == 0 ? mean : dc + 0.01f * (mean - dc);  // ~1 s average
        float mad = 0;
        for (int k = 0; k < FRAME_SAMPLES; k++) mad += fabsf(s[k] - dc);
        mad /= FRAME_SAMPLES;
        float lvl = 20.0f * log10f(max(mad, 1.0f) / FULL_SCALE);
        frames++;
        lastLevelDb = lvl;
        if (frames <= 100) {  // 1 s warm-up: learn the floor, report nothing
          floorDb = frames == 1 ? lvl : floorDb + 0.05f * (lvl - floorDb);
          prevDb = lvl;
          continue;
        }
        if (blanked(now)) { prevDb = lvl; loudOn = false; susOn = false; continue; }
        // floor: follows quiet frames quickly, loud stretches slowly (~5 s)
        floorDb += (lvl < floorDb ? 0.05f : 0.002f) * (lvl - floorDb);
        audioFloorDb = floorDb;
        lvlRing[lvlIdx] = lvl; lvlRingMs[lvlIdx] = now; lvlIdx = (lvlIdx + 1) % 200;
        featMad += mad; featN++; featPk = max(featPk, lvl);

        // onsets -> LOUD (merged over 250 ms) + tap candidates
        bool onset = lvl >= floorDb + ONSET_DB && lvl - prevDb >= RISE_DB && now - lastOnsetMs >= ONSET_REFRACTORY_MS;
        prevDb = lvl;
        if (onset) {
          lastOnsetMs = now;
          if (!loudOn) { loudOn = true; loudStart = now; loudN = 0; loudPk = lvl; }
          loudN++;
          if (!susOn || now - susStart < SUSTAIN_MIN_MS) addTap(now, lvl, false, true);  // not inside ongoing sound
        }
        if (loudOn) {
          loudPk = max(loudPk, lvl);
          if (now - loudStart >= LOUD_HOLD_MS) {
            emitEvent(EV_LOUD, loudStart, loudPk, -128, loudN, (int)((loudPk - floorDb) * 4));
            loudOn = false; stLoud++;
          }
        }

        // sustained sound -> VOICE_LIKE (unclassified: voice, moaning, machinery)
        if (lvl >= floorDb + SUSTAIN_DB) {
          if (!susOn) { susOn = true; susSent = false; susStart = now; susPk = -99; susSum = 0; susN = 0; }
          susLast = now; susPk = max(susPk, lvl); susSum += lvl; susN++;
        }
        if (susOn) {
          if (now - susLast > SUSTAIN_GAP_MS) susOn = false;
          else if (now - susStart >= SUSTAIN_MIN_MS && (!susSent || now - susSentMs >= SUSTAIN_REPEAT_MS)) {
            float avg = susSum / susN;
            emitEvent(EV_VOICE_LIKE, susStart, susPk, dbToI8(avg), (now - susStart) / 100, (int)((avg - floorDb) * 5));
            susSent = true; susSentMs = now; susPk = -99; stSus++;
          }
        }
      }
    } else if (r != ESP_ERR_TIMEOUT) {
      stOverruns++;
    }

    // ---- SW-420 bursts -> VIBRATION + tap candidates ----
    uint32_t edges = swEdges, lastEdge = swLastEdgeMs, burstStart = swBurstStartMs;
    now = millis();  // re-read AFTER the ISR values: an edge after the old `now` would underflow now - lastEdge
    if (!swOn && edges != swStartEdges) { swOn = true; swStart = burstStart; }
    if (swOn && (int32_t)(now - lastEdge) >= SW_QUIET_MS) {
      uint32_t n = edges - swStartEdges;
      swStartEdges = edges;
      swOn = false;
      if (!blanked(swStart) && !blanked(now)) {
        float pk = micPeakAround(swStart, 50, 150);
        bool heard = pk >= audioFloorDb + ONSET_DB - 4;
        emitEvent(EV_VIBRATION, swStart, heard ? pk : audioFloorDb, -128, n, heard ? 90 : 60);
        addTap(swStart, heard ? pk : audioFloorDb, true, heard);
        stFelt++;
      }
    }

    // ---- tap rhythm: flush when quiet for longer than the max gap, or the window is full/old ----
    if (nTaps && !swOn) {
      uint32_t lastTap = taps[nTaps - 1].ms;
      if (now - lastTap > TAP_MAX_GAP_MS + 100 || nTaps >= 12 || now - firstTapMs > 8000) flushTaps();
    }

    // ---- FEAT once a second ----
    if ((int32_t)(now - nextFeatMs) >= 0) {
      nextFeatMs += 1000;
      if (featN) {
        FeatPayload f{now, dbToI8(20.0f * log10f(max(featMad / featN, 1.0f) / FULL_SCALE)), -128, -128, -128, dbToI8(featPk)};
        sendPacket(PKT_FEAT, &f, sizeof(f));
      }
      featMad = 0; featN = 0; featPk = -99;
    }

    // ---- HAIL: 3 beeps, then ignore everything while neighbours beep too ----
    if (hailRequest) { hailRequest = false; hailOn = true; hailStart = now; }
    if (hailOn) {
      uint32_t t = now - hailStart;
      bool on = t < HAIL_BEEPS * HAIL_PERIOD_MS && (t % HAIL_PERIOD_MS) < HAIL_ON_MS;
      if (on != buzzOn) { ledcWriteTone(PIN_BUZZER, on ? BUZZ_HZ : 0); buzzOn = on; }
      blankUntilMs = now + HAIL_BLANK_MS;
      if (t >= HAIL_BEEPS * HAIL_PERIOD_MS) hailOn = false;
    }
  }
}

void sensorsSetup() {
  pinMode(PIN_SW420, INPUT);
  blankUntilMs = millis() + 1500;  // ignore boot/reset glitches on the SW-420 and the mic warm-up
  attachInterrupt(digitalPinToInterrupt(PIN_SW420), onSw420, CHANGE);
  ledcAttach(PIN_BUZZER, BUZZ_HZ, 8);
  ledcWriteTone(PIN_BUZZER, 0);
  if (!audioInit()) {
    Serial.println("# AUDIO init FAILED (sound sensor disabled)");
    return;
  }
  xTaskCreate(audioTask, "audio", 6144, nullptr, 5, nullptr);
  Serial.println("# audio: 16 kHz DMA on D0, SW-420 on D1, buzzer on D4");
}

void sensorsStatus() {
  Serial.printf("# audio floor=%.1f dBFS level=%.1f | events loud=%lu felt=%lu sustained=%lu patterns=%lu adc_err=%lu | sw_edges=%lu sw_pin=%d\n",
                audioFloorDb, lastLevelDb, (unsigned long)stLoud, (unsigned long)stFelt, (unsigned long)stSus,
                (unsigned long)stPat, (unsigned long)stOverruns, (unsigned long)swEdges, digitalRead(PIN_SW420));
}
#endif

// ---------- setup / loop ----------
void setup() {
  Serial.begin(921600);
#if ARDUINO_USB_CDC_ON_BOOT && !ARDUINO_USB_MODE_TINYUSB
  // USB-Serial/JTAG: if a host is attached but nobody reads the port, prints would block and stall
  // the mesh (observed: relays ~15 s late). Never block on Serial.
  Serial.setTxTimeoutMs(0);
#endif
  delay(1500);
  if (LED_PIN >= 0) pinMode(LED_PIN, OUTPUT);
  randomSeed(esp_random());

  rxQueue = xQueueCreate(64, sizeof(RxItem));
  txMutex = xSemaphoreCreateMutex();

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
#if CONFIG_IDF_TARGET_ESP32C5
  esp_wifi_set_band_mode(WIFI_BAND_MODE_2G_ONLY);  // S3 can't hear 5 GHz
#endif
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    Serial.println("# ESP-NOW init FAILED");
    while (true) delay(1000);
  }
  esp_now_register_recv_cb(onRecv);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = ESPNOW_CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  esp_now_add_peer(&peer);

#if ENABLE_BLE_SCAN
  BLEDevice::init("");
  BLEScan *scan = BLEDevice::getScan();
  scan->setActiveScan(false);  // passive: receive only, never transmit scan requests
  scan->setInterval(100);
  scan->setWindow(99);
  devWindowStart = millis();
#endif

  Serial.printf("# Team10 node up: role=%d id=%d mac=%s ch=%d\n", ROLE, NODE_ID,
                WiFi.macAddress().c_str(), ESPNOW_CHANNEL);
#if ROLE == ROLE_NODE
  sensorsSetup();
#endif
  nextBeaconMs = millis() + random(0, BEACON_PERIOD_MS);
}

void loop() {
  RxItem it;
  while (xQueueReceive(rxQueue, &it, 0) == pdTRUE) {
    const PktHeader &h = *(const PktHeader *)it.data;
    updateNeighbor(it, h);
    xSemaphoreTake(txMutex, portMAX_DELAY);  // seen-ring is shared with sendPacket (audio task)
    bool dup = alreadySeen(h.src, h.seq);
    xSemaphoreGive(txMutex);
    if (dup) continue;

    if (h.type == PKT_CMD && it.len >= sizeof(PktHeader) + sizeof(CmdPayload)) {
      handleCmd(*(const CmdPayload *)(it.data + sizeof(PktHeader)));
      if (h.ttl > 0 && ROLE != ROLE_GATEWAY) scheduleForward(it);  // downlink floods outward
      continue;
    }
    if (IS_PRINTER) printJson(it);
    if (FORWARDS_UPLINK && h.ttl > 0) scheduleForward(it);
  }
  serviceForwards();

  uint32_t now = millis();
  if (ROLE != ROLE_GATEWAY && (int32_t)(now - nextBeaconMs) >= 0) {
    sendBeacon();
    nextBeaconMs = now + BEACON_PERIOD_MS + random(-200, 201);
  }

  if (IS_PRINTER) readSerialCommands();
#if ROLE == ROLE_NODE
  while (Serial.available()) if (Serial.read() == 'H') { Serial.println("# local HAIL (debug key)"); hailRequest = true; }
#endif

  // Gateway: re-broadcast mesh-wide settings so rebooted / newly dropped nodes pick them up.
  static uint32_t nextConfigMs = CONFIG_REBROADCAST_MS;
  if (ROLE == ROLE_GATEWAY && (int32_t)(now - nextConfigMs) >= 0) {
    nextConfigMs = now + CONFIG_REBROADCAST_MS;
    const int16_t vals[3] = {cfgTxPower, cfgScan, cfgSalt};
    const uint8_t ids[3] = {CMD_SET_TX_POWER, CMD_SET_SCAN, CMD_SET_SALT};
    for (int i = 0; i < 3; i++) {
      if (vals[i] < 0) continue;
      CmdPayload c{ids[i], vals[i], 255};
      sendPacket(PKT_CMD, &c, sizeof(c), 2);
    }
  }

  if (blinkToggles > 0 && (int32_t)(now - nextBlinkMs) >= 0) {
    setLed(!ledOn);
    blinkToggles--;
    nextBlinkMs = now + 250;
    if (blinkToggles == 0) setLed(false);
  }

  static uint32_t nextStatusMs = 0;
  if ((int32_t)(now - nextStatusMs) >= 0) {
    nextStatusMs = now + 5000;
    if (IS_PRINTER) Serial.printf("{\"type\":\"gw\",\"id\":%d,\"t_ms\":%lu,\"rx_dropped\":%lu}\n",
                                  NODE_ID, (unsigned long)now, (unsigned long)rxDropped);
    else Serial.printf("# alive id=%d neighbors:", NODE_ID);
    if (!IS_PRINTER) {
      for (auto &n : nbrs) if (n.used && now - n.lastMs < NEIGHBOR_TIMEOUT_MS) Serial.printf(" [%d %.0fdBm]", n.id, n.rssi);
      Serial.println();
#if ROLE == ROLE_NODE
      sensorsStatus();
#endif
    }
  }

#if ENABLE_BLE_SCAN
  if (ROLE == ROLE_NODE) {
    if ((int32_t)(now - nextScanMs) >= 0) {
      runBleScan();
      nextScanMs = millis() + (DEVICE_WINDOW_MS / 2) + random(-500, 501);  // ~2 scans per window
    }
    if (millis() - devWindowStart >= DEVICE_WINDOW_MS) {
      flushDevices();
      devWindowStart = millis();
    }
  }
#endif
}
