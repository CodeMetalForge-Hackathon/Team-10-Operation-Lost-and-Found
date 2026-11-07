const assert = require("assert");
const Review = require("../ui/review.js");

const tap = {
  kind: "TAP_PATTERN",
  t_ms: 51800,
  t_host: 40000,
  count: 3,
  conf: 80,
  peak_db: -20
};
const loud = {
  kind: "LOUD",
  t_ms: 10,
  t_host: 90000,
  count: 1,
  conf: 10,
  peak_db: -12
};
const snapshot = {
  t_host: 100000,
  nodes: [
    {
      id: 3,
      status: "inactive",
      last_t_host: 50000,
      evidence: [tap]
    },
    {
      id: 4,
      status: "active",
      last_t_host: 100000,
      evidence: [loud]
    }
  ],
  devices: [
    { hash: "9f3a01c2", kind: "BLE_APPLE", heard_by: 4, t_host: 80000, t_ms: 60000, count: 14, rssi_max: -52 }
  ]
};

const observations = Review.collectObservations(snapshot);
assert.strictEqual(observations.length, 3);
assert.strictEqual(Review.replaceHistory(snapshot).length, 3, "a repeated snapshot must not multiply evidence");
assert.strictEqual(Review.readableKind("TAP_PATTERN"), "Tap pattern");
assert.strictEqual(Review.countText(3), "Reported count 3");
assert.strictEqual(Review.countText(3).includes("tap"), false);
assert.strictEqual(Review.confText(80).includes("%"), false);
assert.strictEqual(Review.confText(80).includes("probability"), true);

const node3 = observations.find((row) => row.kind === "TAP_PATTERN");
assert.strictEqual(Review.evidenceAgeMs(node3, snapshot.t_host), 60000);
assert.strictEqual(Review.sensorAgeMs(node3, snapshot.t_host), 50000);
assert.notStrictEqual(Review.evidenceAgeMs(node3, snapshot.t_host), Review.sensorAgeMs(node3, snapshot.t_host));

const first = Review.chooseSelection({ selectedKey: null, userChose: false }, observations);
assert.strictEqual(first.reason, "auto");
assert.strictEqual(first.selectedKey, Review.cueKey(4, loud), "first load picks the newest acoustic cue");

const kept = Review.chooseSelection({ selectedKey: first.selectedKey, userChose: false }, observations.concat([{
  key: "cue:9:TAP_PATTERN:1:110000",
  family: "acoustic",
  tHost: 110000
}]));
assert.strictEqual(kept.selectedKey, first.selectedKey, "a later cue must not replace an existing selection");

const pinned = Review.chooseSelection({ selectedKey: node3.key, userChose: true }, observations);
assert.strictEqual(pinned.reason, "keep-user");
assert.strictEqual(pinned.selectedKey, node3.key);

const gone = Review.chooseSelection({ selectedKey: "cue:missing", userChose: true }, observations);
assert.strictEqual(gone.selectedKey, "cue:missing");
assert.strictEqual(gone.userChose, true);

const recentNow = 40000 + Review.RECENT_WINDOW_MS + 1000;
const recent = Review.chartWindow(observations, "recent", recentNow, node3.key, false);
assert.strictEqual(recent.points.some((row) => row.key === node3.key), false);
assert.strictEqual(recent.outside, true, "historical evidence stays inspectable outside the chart window");
assert.strictEqual(recent.points.some((row) => row.kind === "LOUD"), true);

const fallback = Review.chartWindow(observations, "recent", 100000 + Review.RECENT_WINDOW_MS, node3.key, true);
assert.strictEqual(fallback.effective, "retained");
assert.strictEqual(fallback.points.length, 3);

const forced = Review.chartWindow(observations, "recent", 100000 + Review.RECENT_WINDOW_MS, node3.key, false);
assert.strictEqual(forced.effective, "recent");
assert.strictEqual(forced.points.length, 0);

const before = { counts: { packets: 12 } };
const after = { counts: { packets: 1 } };
assert.strictEqual(Review.resetLanded({ packets: 12, keys: [node3.key] }, after, observations), true);
assert.strictEqual(Review.resetLanded({ packets: 12, keys: [node3.key] }, before, observations), false);
assert.strictEqual(
  Review.resetLanded({ packets: 2, keys: ["old-key"] }, { counts: { packets: 4 } }, observations),
  false,
  "a growing packet count is not a replay reset"
);

console.log("review policy ok");
