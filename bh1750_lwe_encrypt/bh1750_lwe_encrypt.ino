#include <Wire.h>
#include "lwe_public_key.h"
#include "lwe_private_key.h"

#define BH1750_ADDR           0x23
#define BH1750_ONE_TIME_H_RES 0x20
#define KP_SCALE              100
#define SERIAL_BUF_LEN        128
#define TX_BUF_LEN            80     // OPT 5: pre-built TX buffer

const int PWM_OUT_PINS[] = {4, 5, 6, 7};
static char serialBuf[SERIAL_BUF_LEN];
static char txBuf[TX_BUF_LEN];       // OPT 5: single-write TX buffer

// ─────────────────────────────────────────────────────────────────────────────
// OPT 1: Mersenne prime mod  (Q = 2^31 - 1 = 0x7FFFFFFF)
// Identity: 2^31 ≡ 1 (mod Q)  →  fold high bits into low bits
// Two folds cover the full int64_t range produced by our multiplications.
// No 64-bit division anywhere in this function.
// ─────────────────────────────────────────────────────────────────────────────
static inline uint32_t modQ(int64_t x) {
  // First fold
  int64_t r = (x >> 31) + (x & 0x7FFFFFFFLL);
  // Second fold (handles carry from first)
  r = (r >> 31) + (r & 0x7FFFFFFFLL);
  // Final range fix: r is now in [-Q, 2Q)
  if (r >= (int64_t)LWE_Q) r -= (int64_t)LWE_Q;
  if (r < 0)               r += (int64_t)LWE_Q;
  return (uint32_t)r;
}

// ─────────────────────────────────────────────────────────────────────────────
uint16_t readLuxBH1750() {
  Wire.beginTransmission(BH1750_ADDR);
  Wire.write(0x01);                     // power on
  Wire.endTransmission();
  delay(10);

  Wire.beginTransmission(BH1750_ADDR);
  Wire.write(BH1750_ONE_TIME_H_RES);
  if (Wire.endTransmission() != 0) {
    Serial.println("ERR: BH1750 not responding");
    return 0;
  }
  delay(180);

  Wire.requestFrom((uint8_t)BH1750_ADDR, (uint8_t)2);
  if (Wire.available() < 2) {
    Serial.println("ERR: BH1750 no data");
    return 0;
  }

  uint16_t raw = ((uint16_t)Wire.read() << 8) | Wire.read();
  float lux    = raw / 1.2f;
  lux          = constrain(lux, 0.0f, 500.0f);
  return (uint16_t)(lux + 0.5f);
}

// ─────────────────────────────────────────────────────────────────────────────
// OPT 2: Sparse r — only track indices where r[j] == 1
//         Eliminates multiply entirely (r[j] is always 1 when used)
//         On average halves the inner-loop iterations
//
// OPT 3: encode(lux) = lux << 1
//         Q = 2^31 - 1, MAX_PLAIN = (Q-1)/2 ≈ 2^30
//         round(lux × Q / MAX_PLAIN) ≈ lux × 2  (exact for lux ≤ 500)
//         Replace float multiply + round with a single left shift
// ─────────────────────────────────────────────────────────────────────────────
void lweEncryptLux(uint16_t luxVal, uint32_t *uOut, uint32_t &vOut) {
  // OPT 2: store only the column indices where r[j] == 1
  uint8_t ones[LWE_M];
  uint8_t nOnes = 0;

  for (uint8_t j = 0; j < LWE_M; ++j) {
    if (random(2)) {
      ones[nOnes++] = j;
    }
  }

  // u = A·r mod Q  — sum only columns where r[j] == 1 (no multiply needed)
  for (uint8_t i = 0; i < LWE_N; ++i) {
    int64_t sum = 0;
    for (uint8_t k = 0; k < nOnes; ++k)
      sum += (int64_t)LWE_A[i][ones[k]];   // r[j]=1 so just add the column
    uOut[i] = modQ(sum);
  }

  // v = b·r + encode(lux) mod Q
  int64_t sumV = 0;
  for (uint8_t k = 0; k < nOnes; ++k)
    sumV += (int64_t)LWE_b[ones[k]];

  // OPT 3: encode(lux) = lux * 2 = lux << 1  (no float, no round)
  sumV += (int64_t)luxVal << 1;
  vOut  = modQ(sumV);
}

// ─────────────────────────────────────────────────────────────────────────────
// OPT 5: Build CT line into txBuf, then send in one Serial.print call
//        Avoids many small Serial.print calls (each flushes separately)
//        ultoa: fast unsigned-long-to-ASCII with no heap allocation
// ─────────────────────────────────────────────────────────────────────────────
void sendEncryptedLux(uint16_t luxVal) {
  uint32_t u[LWE_N], v;
  lweEncryptLux(luxVal, u, v);

  char *p = txBuf;
  *p++ = 'C'; *p++ = 'T'; *p++ = ','; *p++ = '[';

  for (uint8_t i = 0; i < LWE_N; ++i) {
    ultoa(u[i], p, 10);      // write ASCII digits directly into buffer
    while (*p) ++p;          // advance pointer to end of written digits
    *p++ = ',';
  }
  ultoa(v, p, 10);
  while (*p) ++p;
  *p++ = ']'; *p++ = '\n'; *p = '\0';

  Serial.print(txBuf);       // one write instead of 10+ small prints
}

// ─────────────────────────────────────────────────────────────────────────────
// OPT 4: decode using right-shift instead of floating-point division
//        kp_int_error = round(phase × MAX_PLAIN / Q)
//        Since Q = 2^31-1 ≈ 2 × MAX_PLAIN:
//          round(phase / 2) = (phase + sign) >> 1
//        where sign = -1 for negative phase, +1 for positive
//
// OPT 1 (reused): Mersenne fold replaces % LWE_Q in centring step
// ─────────────────────────────────────────────────────────────────────────────
float lweDecryptScalar(uint32_t *u, uint32_t v) {
  int64_t phase = (int64_t)v;

  for (uint8_t i = 0; i < LWE_N; ++i)
    phase -= (int64_t)LWE_s[i] * (int64_t)u[i];

  // OPT 1: Mersenne fold instead of % LWE_Q
  int64_t r = (phase >> 31) + (phase & 0x7FFFFFFFLL);
  r = (r >> 31) + (r & 0x7FFFFFFFLL);
  if (r >= (int64_t)LWE_Q) r -= (int64_t)LWE_Q;
  if (r < 0)               r += (int64_t)LWE_Q;

  // Centre to (-Q/2, Q/2]
  if (r > (int64_t)(LWE_Q / 2)) r -= (int64_t)LWE_Q;

  // OPT 4: round(phase / 2) via arithmetic shift
  // Equivalent to round() but no float — works for both + and - phase
  int32_t kp_int_error = (int32_t)((r + (r < 0 ? -1LL : 1LL)) >> 1);

  return (float)kp_int_error / (float)KP_SCALE;
}

// ─────────────────────────────────────────────────────────────────────────────
// Use strtoul (unsigned) — strtol is signed and truncates values > 2^31-1
// ─────────────────────────────────────────────────────────────────────────────
bool parsePWMLine(const char *line, uint32_t *u_out, uint32_t &v_out) {
  if (strncmp(line, "PWM,", 4) != 0) return false;

  const char *p   = line + 4;
  uint32_t    vals[LWE_N + 1];
  uint8_t     idx = 0;

  while (*p != '\0' && idx <= LWE_N) {
    char          *end;
    unsigned long  val = strtoul(p, &end, 10);  // strtoul not strtol
    if (end == p) break;
    vals[idx++] = (uint32_t)val;
    p = end;
    if (*p == ',') ++p;
  }

  if (idx != LWE_N + 1) return false;
  for (uint8_t i = 0; i < LWE_N; ++i) u_out[i] = vals[i];
  v_out = vals[LWE_N];
  return true;
}

// ─────────────────────────────────────────────────────────────────────────────
bool readSerialLine() {
  static uint8_t pos = 0;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (pos > 0) { serialBuf[pos] = '\0'; pos = 0; return true; }
    } else if (pos < SERIAL_BUF_LEN - 1) {
      serialBuf[pos++] = c;
    }
  }
  return false;
}

// ─────────────────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Wire.begin();
  for (int i = 0; i < 4; i++) {
    pinMode(PWM_OUT_PINS[i], OUTPUT);
  }
  // OPT 6: better entropy — XOR two analog pins + micros
  randomSeed(analogRead(A0) ^ analogRead(A1) ^ micros());
  delay(500);
  Serial.println("BH1750 + LWE Kp ready  Q=2^31-1");
}

// ─────────────────────────────────────────────────────────────────────────────
void loop() {
  uint16_t lux = readLuxBH1750();
  sendEncryptedLux(lux);

  uint32_t deadline  = millis() + 500;  // increased from 1000 → 3000ms
  bool     gotResult = false;

  while (millis() < deadline && !gotResult) {
    if (readSerialLine()) {
      uint32_t u[LWE_N], v;
      if (parsePWMLine(serialBuf, u, v)) {
        float pwm_float = lweDecryptScalar(u, v);
        int   pwm_out   = (int)constrain(pwm_float, 0.0f, 255.0f);

        for (int i = 0; i < 4; i++) {
          analogWrite(PWM_OUT_PINS[i], pwm_out);
        }

        Serial.print("lux=");   Serial.print(lux);
        Serial.print(" pwm=");  Serial.println(pwm_out);
        gotResult = true;
      }
    }
  }

  if (!gotResult) Serial.println("WARN: no PWM reply");
  delay(250);
}