// sensor_test.ino: bench check for one XIAO ESP32-C5 field node's Grove wiring.
// Wiring under test (docs/HARDWARE.md): Sound Sensor D0 (ADC), SW-420 D1, Buzzer D4 (LED = on-board).
//
// Prints one line every 200 ms:
//   snd: mean/min/max/p2p/ac_rms in raw 12-bit counts, mean-crossings per window, clipped samples
//   sw:  current SW-420 level and edges seen in the window
// Serial commands (send a single character):
//   b = beep the buzzer (2.3 kHz, 300 ms)     l = blink the LED 3x
//   B = buzzer on for ~1 s WITHOUT blocking, so the mic stats show whether the mic hears it
//   w = dump 512 raw D0 samples at 8 kHz (one per line, between "# dump begin" / "# dump end")
//
// Flash:  arduino-cli compile --upload -p COMx -b esp32:esp32:XIAO_ESP32C5:CDCOnBoot=cdc firmware/sensor_test

#include <Arduino.h>
#include <algorithm>

#define PIN_SOUND D0
#define PIN_SW420 D1
#define PIN_BUZZER D4
#define PIN_LED LED_BUILTIN  // no external LED on the nodes

#define FS_HZ 8000
#define WINDOW_MS 200
#define BUZZ_HZ 2300

volatile uint32_t swEdges = 0, swTaps = 0, swLastUs = 0;
void IRAM_ATTR onSw() {  // edges closer than 60 ms belong to the same tap (switch chatter)
  uint32_t now = micros();
  if (now - swLastUs > 60000) swTaps++;
  swLastUs = now;
  swEdges++;
}

void beep(uint32_t ms) {
  ledcWriteTone(PIN_BUZZER, BUZZ_HZ);
  delay(ms);
  ledcWriteTone(PIN_BUZZER, 0);
}

void blink(int n) {
  for (int i = 0; i < n; i++) {
    digitalWrite(PIN_LED, HIGH); delay(150);
    digitalWrite(PIN_LED, LOW);  delay(150);
  }
}

void dump() {
  static uint16_t buf[512];
  const uint32_t period = 1000000UL / FS_HZ;
  uint32_t t = micros();
  for (int i = 0; i < 512; i++) {
    while ((int32_t)(micros() - t) < 0) {}
    t += period;
    buf[i] = analogRead(PIN_SOUND);
  }
  Serial.println("# dump begin");
  for (int i = 0; i < 512; i++) Serial.println(buf[i]);
  Serial.println("# dump end");
}

void setup() {
  Serial.begin(921600);
  delay(1500);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_SW420, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_SW420), onSw, CHANGE);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_SOUND, ADC_11db);
  ledcAttach(PIN_BUZZER, BUZZ_HZ, 8);
  ledcWriteTone(PIN_BUZZER, 0);

  Serial.println("# sensor_test up: Sound=D0 SW420=D1 Buzzer=D4 LED=builtin");
  // measure how fast analogRead is on this core
  uint32_t t0 = micros();
  for (int i = 0; i < 200; i++) analogRead(PIN_SOUND);
  Serial.printf("# analogRead takes %.1f us\n", (micros() - t0) / 200.0f);
  Serial.println("# self-test: LED blinks 3x, then buzzer beeps");
  blink(3);
  beep(300);
}

uint32_t beepOffMs = 0;

void loop() {
  if (beepOffMs && millis() > beepOffMs) { ledcWriteTone(PIN_BUZZER, 0); beepOffMs = 0; Serial.println("# beep off"); }
  const uint32_t period = 1000000UL / FS_HZ;
  const int n = FS_HZ * WINDOW_MS / 1000;
  // pass 1: sample the window into a buffer at a fixed rate
  static uint16_t s[FS_HZ * WINDOW_MS / 1000];
  uint32_t t = micros();
  uint32_t late = 0;
  for (int i = 0; i < n; i++) {
    int32_t wait = (int32_t)(t - micros());
    if (wait < 0) late++;
    while ((int32_t)(micros() - t) < 0) {}
    t += period;
    s[i] = analogRead(PIN_SOUND);
  }
  // pass 2: stats
  uint32_t sum = 0; uint16_t mn = 4095, mx = 0; uint32_t clip = 0;
  for (int i = 0; i < n; i++) {
    sum += s[i]; mn = min(mn, s[i]); mx = max(mx, s[i]);
    if (s[i] <= 8 || s[i] >= 4087) clip++;
  }
  float mean = (float)sum / n, acc = 0; uint32_t xings = 0;
  for (int i = 0; i < n; i++) {
    float d = s[i] - mean; acc += d * d;
    if (i && ((s[i - 1] < mean) != (s[i] < mean))) xings++;
  }
  // onset strength: loudest 10 ms frame vs the median frame (mean abs deviation), in dB
  const int FR = FS_HZ / 100, NF = n / FR;
  float fe[32];
  for (int f = 0; f < NF; f++) {
    float a = 0;
    for (int i = f * FR; i < (f + 1) * FR; i++) a += fabsf(s[i] - mean);
    fe[f] = a / FR + 1;
  }
  float pk = 0; for (int f = 0; f < NF; f++) pk = max(pk, fe[f]);
  float srt[32]; memcpy(srt, fe, sizeof(float) * NF); std::sort(srt, srt + NF);
  float onset_db = 20 * log10f(pk / srt[NF / 2]);
  noInterrupts(); uint32_t edges = swEdges, taps = swTaps; swEdges = 0; swTaps = 0; interrupts();
  Serial.printf("snd mean=%4.0f min=%4u max=%4u p2p=%4u ac_rms=%6.1f xings=%3lu clip=%lu late=%lu onset_db=%4.1f | sw lvl=%d edges=%lu taps=%lu\n",
                mean, mn, mx, mx - mn, sqrtf(acc / n), (unsigned long)xings, (unsigned long)clip,
                (unsigned long)late, onset_db, digitalRead(PIN_SW420), (unsigned long)edges, (unsigned long)taps);

  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'b') { Serial.println("# beep"); beep(300); }
    else if (c == 'B') { Serial.println("# beep on (non-blocking, ~1 s)"); ledcWriteTone(PIN_BUZZER, BUZZ_HZ); beepOffMs = millis() + 1000; }
    else if (c >= '1' && c <= '6') {  // tone sweep: 1=1000 2=1500 3=2000 4=2300 5=3000 6=500 Hz, ~0.6 s, non-blocking
      static const uint16_t hz[] = {1000, 1500, 2000, 2300, 3000, 500};
      ledcWriteTone(PIN_BUZZER, hz[c - '1']); beepOffMs = millis() + 600;
      Serial.printf("# tone %u Hz\n", hz[c - '1']);
    }
    else if (c == 't') {
      uint32_t t0 = micros();
      for (int i = 0; i < 1000; i++) analogRead(PIN_SOUND);
      Serial.printf("# analogRead takes %.1f us\n", (micros() - t0) / 1000.0f);
    }
    else if (c == 'l') { Serial.println("# blink"); blink(3); }
    else if (c == 'w') dump();
  }
}
