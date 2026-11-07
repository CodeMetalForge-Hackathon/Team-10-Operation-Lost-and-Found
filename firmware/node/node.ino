// node.ino: Team 10 mesh firmware (XIAO ESP32-C5 field nodes, XIAO ESP32-S3 Plus gateway / drone bridge)
//
// STEP 1 (no mic needed): ESP-NOW flooding mesh + BEACON with neighbor RSSI + gateway JSON lines + CMD downlink.
// STEP 2 (no mic needed): set ENABLE_BLE_SCAN 1 -> passive BLE scan -> DEVICE_SEEN.
// STEP 3 (after the ICS-43434 arrives): audio FEAT / EVENT (not in this file yet).
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
// repeats > 1: resend the identical packet (same seq) so receivers de-dup it. Used for CMDs,
// because ESP-NOW broadcast has no ACK/retry and a lost command is worse than a duplicate.
void sendPacket(uint8_t type, const void *payload, size_t plen, int repeats = 1) {
  uint8_t buf[PKT_MAX_LEN];
  PktHeader h{PKT_MAGIC, type, (uint8_t)NODE_ID, START_TTL, 0, txSeq++, 0};
  if (sizeof(h) + plen > PKT_MAX_LEN) return;
  memcpy(buf, &h, sizeof(h));
  memcpy(buf + sizeof(h), payload, plen);
  alreadySeen(h.src, h.seq);  // never re-forward our own packet
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
      Serial.println("# HAIL received (buzzer not wired yet)");
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
  b.floor_db = 0; // TODO: audio noise floor
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
  nextBeaconMs = millis() + random(0, BEACON_PERIOD_MS);
}

void loop() {
  RxItem it;
  while (xQueueReceive(rxQueue, &it, 0) == pdTRUE) {
    const PktHeader &h = *(const PktHeader *)it.data;
    updateNeighbor(it, h);
    if (alreadySeen(h.src, h.seq)) continue;

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
