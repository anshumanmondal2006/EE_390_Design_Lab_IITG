#include <Wire.h>
#include <BH1750.h>

BH1750 lightMeter;

const int LED_PINS[] = {7, 6, 5, 4};
const int NUM_LEDS   = 4;

// ── Setpoint: 75% of your measured max (138.33 lux) ──────────
const float SETPOINT = (75.0/100)*146.67;  // lux

// ── PID constants (tuned for your linear ~0.83 lux/PWM system)
float Kp = 1.2;
float Ki = 0.08;
float Kd = 0;

// ── PID state ─────────────────────────────────────────────────
float    integral  = 0;
float    prevError = 0;
int      pwmOut    = 100;   // Start near expected PWM for 75%
unsigned long prevTime = 0;

void setup() {
  Serial.begin(9600);
  Wire.begin();

  if (lightMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE)) {
    Serial.println("BH1750 ready.");
  } else {
    Serial.println("BH1750 error! Check wiring.");
    while (1);
  }

  for (int i = 0; i < NUM_LEDS; i++) {
    pinMode(LED_PINS[i], OUTPUT);
  }

  // Start at expected operating point (feedforward from your sweep data)
  for (int i = 0; i < NUM_LEDS; i++) {
    analogWrite(LED_PINS[i], pwmOut);
  }

  prevTime = millis();
  Serial.println("Setpoint,Lux,Error,PWM");  // CSV header for Serial plotter
}

void loop() {
  if (!lightMeter.measurementReady()) return;

  float lux = lightMeter.readLightLevel();

  // ── PID ───────────────────────────────────────────────────
  unsigned long now = millis();
  float dt = (now - prevTime) / 1000.0;
  if (dt <= 0) dt = 0.001;

  float error = SETPOINT - lux;

  float P = Kp * error;

  integral = constrain(integral + error * dt, -200, 200); // Anti-windup
  float I  = Ki * integral;

  float D  = Kd * (error - prevError) / dt;

  pwmOut = constrain((int)(pwmOut + P + I + D), 0, 255);

  prevError = error;
  prevTime  = now;

  // ── Write to LEDs ─────────────────────────────────────────
  for (int i = 0; i < NUM_LEDS; i++) {
    analogWrite(LED_PINS[i], pwmOut);
  }

  // ── Serial output (works with Serial Plotter too) ─────────
  Serial.print(SETPOINT); Serial.print(",");
  Serial.print(lux);      Serial.print(",");
  Serial.print(error);    Serial.print(",");
  Serial.println(pwmOut);

  delay(150);
}