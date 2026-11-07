// protocol.h: over-the-air packet format. CONTRACT: must match docs/ARCHITECTURE.md section 2.
#pragma once
#include <stdint.h>

#define PKT_MAGIC 0xA7
#define PKT_MAX_LEN 250  // ESP-NOW v1 payload limit

enum PktType : uint8_t {
  PKT_BEACON = 1,
  PKT_FEAT = 2,
  PKT_EVENT = 3,
  PKT_CHIRP = 4,
  PKT_RANGE = 5,
  PKT_CMD = 6,
  PKT_DEVICE_SEEN = 7,
};

enum CmdId : uint8_t {
  CMD_HAIL = 1,
  CMD_BLINK_ID = 2,
  CMD_START_RANGING = 3,
  CMD_SET_TX_POWER = 4,  // arg in 0.25 dBm units, 8..84
  CMD_SET_RATE = 5,
  CMD_PING = 6,
  CMD_SET_SCAN = 7,      // arg = BLE scan seconds per 10 s window, 0 = off
  CMD_SET_SALT = 8,
};

enum EventKind : uint8_t {
  EV_LOUD = 1,
  EV_TAP_PATTERN = 2,
  EV_VOICE_LIKE = 3,
  EV_RADAR_PRESENCE = 4,
  EV_GAS = 5,
};

enum DevKind : uint8_t {
  DEV_BLE_OTHER = 1,
  DEV_BLE_APPLE = 2,
  DEV_BLE_FINDMY = 3,
  DEV_BLE_GOOGLE = 4,
  DEV_WIFI_PROBE = 5,
};

struct __attribute__((packed)) PktHeader {
  uint8_t magic;
  uint8_t type;
  uint8_t src;   // origin node id (0 = gateway, 200+ = drone)
  uint8_t ttl;   // hops remaining
  uint8_t hops;  // hops so far (0 = heard directly from origin)
  uint16_t seq;  // per-source counter
  uint8_t rsv;
};

struct __attribute__((packed)) NeighborEntry {
  uint8_t id;
  int8_t rssi;
};

#define MAX_NEIGHBORS 16
struct __attribute__((packed)) BeaconPayload {
  uint16_t batt_mv;
  uint16_t uptime_s;
  int8_t floor_db;
  uint8_t n;
  NeighborEntry nbrs[MAX_NEIGHBORS];  // only n are sent
};

struct __attribute__((packed)) FeatPayload {
  uint32_t t_ms;
  int8_t rms_db, low_db, voice_db, high_db, peak_db;
};

struct __attribute__((packed)) EventPayload {
  uint32_t t_ms;
  uint8_t kind;
  int8_t peak_db, voice_db;
  uint8_t count, conf;
};

struct __attribute__((packed)) ChirpPayload {
  uint32_t t_us;
};

struct __attribute__((packed)) RangePayload {
  uint8_t chirper;
  uint32_t delay_us;
  int8_t snr_db;
};

struct __attribute__((packed)) CmdPayload {
  uint8_t cmd;
  int16_t arg;
  uint8_t target;  // 255 = all
};

struct __attribute__((packed)) DeviceEntry {
  uint32_t hash;
  uint8_t kind;
  int8_t rssi_max;
  uint8_t count;
};

#define MAX_DEVICES 20
struct __attribute__((packed)) DeviceSeenPayload {
  uint32_t t_ms;
  uint8_t n;
  DeviceEntry devs[MAX_DEVICES];  // only n are sent
};

static_assert(sizeof(PktHeader) == 8, "header must be 8 bytes");
static_assert(sizeof(PktHeader) + sizeof(DeviceSeenPayload) <= PKT_MAX_LEN, "DEVICE_SEEN too big");
