import serial
import time
import matplotlib.pyplot as plt
from collections import deque

# ─────────────────────────────────────────────
#  CONFIG  — edit these before running
# ─────────────────────────────────────────────
PORT = 'COM4'          # Windows: 'COM4'  |  Linux/Mac: '/dev/ttyUSB0'
BAUD = 9600

# Target lux  =  75% of your measured max (146.67 lux)
SETPOINT = 0.75 * 320   # ≈ 110.0 lux

# PID gains  (same values that worked in your Arduino version)
Kp = 1.2
Ki = 0.0
Kd = 0.0

# Smoothing factor for PWM changes (0=no change, 1=instant)
ALPHA = 0.3

# Anti-windup clamp on the integral term
INTEGRAL_CLAMP = 200
# ─────────────────────────────────────────────


# ── PID state ────────────────────────────────
integral   = 0.0
prev_error = 0.0
pwm        = 100        # start near expected operating point
prev_time  = None       # set after first valid lux reading

# ── Serial ───────────────────────────────────
print(f"Opening {PORT} at {BAUD} baud …")
ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(2)           # wait for Arduino reset after DTR toggle
print("Connected. Waiting for sensor …")

# Flush any startup messages ("READY", "ERROR", etc.)
while True:
    line = ser.readline().decode(errors='replace').strip()
    if not line:
        continue
    try:
        float(line)     # first numeric line = first lux reading
        break
    except ValueError:
        print(f"[Arduino] {line}")

# ── Live plot ────────────────────────────────
WINDOW = 100
lux_buf = deque(maxlen=WINDOW)
set_buf = deque(maxlen=WINDOW)
pwm_buf = deque(maxlen=WINDOW)

plt.ion()
fig, (ax_lux, ax_pwm) = plt.subplots(2, 1, figsize=(9, 5), tight_layout=True)
ax_lux.set_ylabel("Lux")
ax_lux.set_title("Light level vs setpoint")
ax_pwm.set_ylabel("PWM (0–255)")
ax_pwm.set_xlabel("Samples")
ax_pwm.set_title("Control output")

print("Running PID loop — close the plot window to stop.\n")
print(f"{'Lux':>8}  {'Setpoint':>8}  {'Error':>8}  {'PWM':>5}")
print("-" * 40)

# ── Main loop ────────────────────────────────
while plt.get_fignums():        # exits cleanly when plot window is closed
    try:
        raw = ser.readline().decode(errors='replace').strip()
        if not raw:
            continue

        # Skip any non-numeric lines (e.g. sensor errors)
        try:
            lux = float(raw)
        except ValueError:
            print(f"[Arduino] {raw}")
            continue

        # ── Timing ───────────────────────────
        now = time.time()
        if prev_time is None:
            prev_time = now
            ser.write(f"{pwm}\n".encode())
            continue

        dt = now - prev_time
        if dt <= 0:
            dt = 0.001
        prev_time = now

        # ── PID ──────────────────────────────
        error = SETPOINT - lux

        P = Kp * error

        integral = max(min(integral + error * dt, INTEGRAL_CLAMP), -INTEGRAL_CLAMP)
        I = Ki * integral

        D = Kd * (error - prev_error) / dt

        raw_pwm  = pwm + P + I + D
        new_pwm  = ALPHA * raw_pwm + (1 - ALPHA) * pwm   # exponential smoothing
        pwm      = int(max(min(new_pwm, 255), 0))

        prev_error = error

        # ── Send PWM to Arduino ───────────────
        ser.write(f"{pwm}\n".encode())

        # ── Console log ──────────────────────
        print(f"{lux:8.2f}  {SETPOINT:8.2f}  {error:8.2f}  {pwm:5d}")

        # ── Update plot ──────────────────────
        lux_buf.append(lux)
        set_buf.append(SETPOINT)
        pwm_buf.append(pwm)

        ax_lux.clear()
        ax_lux.plot(lux_buf,         color='steelblue',  label='Lux')
        ax_lux.plot(set_buf, '--',   color='tomato',     label=f'Setpoint ({SETPOINT:.1f})')
        ax_lux.legend(loc='upper right', fontsize=8)
        ax_lux.set_ylabel("Lux")
        ax_lux.set_ylim(bottom=0)

        ax_pwm.clear()
        ax_pwm.plot(pwm_buf, color='darkorange', label='PWM')
        ax_pwm.set_ylim(0, 255)
        ax_pwm.set_ylabel("PWM (0-255)")
        ax_pwm.legend(loc='upper right', fontsize=8)

        plt.pause(0.01)

    except KeyboardInterrupt:
        print("\nStopped by user.")
        break
    except Exception as e:
        print(f"[Error] {e}")

# ── Cleanup ──────────────────────────────────
ser.write(b"0\n")   # turn LEDs off when script exits
ser.close()
print("Serial closed. Goodbye.")