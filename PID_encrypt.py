import serial
import serial.tools.list_ports
import time

# ── Must match lwe_public_key.h ───────────────────────────────────────────────
LWE_Q     = (2**31 - 1)
LWE_N     = 4
LWE_M     = 8
MAX_PLAIN = LWE_Q // 2   # = 65535

# ── Kp controller ─────────────────────────────────────────────────────────────
KP           = 0.5
KP_SCALE     = 100
KP_INT       = round(KP * KP_SCALE)   # 120
SETPOINT_LUX = 100                    # target lux (0–500)
BAUD         = 115200

# Delta: how lux is encoded into the ciphertext
# encode(lux) = round(lux × Q / MAX_PLAIN)
# After Kp multiply: encodes Kp_int × lux
# Max encoded value = 120 × 500 = 60000 < MAX_PLAIN=65535 ✓
DELTA = LWE_Q / MAX_PLAIN   # ≈ 2.0

# Constant shift for setpoint:
# CT(Kp_int × error) = CT(Kp_int × setpoint) − CT(Kp_int × lux)
# The setpoint term is plaintext, added directly to v
SETPOINT_V_SHIFT = int(round(KP_INT * SETPOINT_LUX * DELTA)) % LWE_Q

# ─────────────────────────────────────────────────────────────────────────────
def mod_q(x):
    return int(x) % LWE_Q

# ─────────────────────────────────────────────────────────────────────────────
def find_port():
    ports = serial.tools.list_ports.comports()
    print("Available ports:")
    for p in sorted(ports):
        print(f"  {p.device}  {p.description}")
    for p in ports:
        if any(x in p.description.lower() for x in
               ["arduino", "ch340", "ch341", "usb serial", "uart"]):
            return p.device
    if ports:
        return sorted(ports)[0].device
    raise RuntimeError("No COM ports found. Is the Arduino plugged in?")

# ─────────────────────────────────────────────────────────────────────────────
def parse_ct_line(line: str):
    """
    Parse single-integer ciphertext:
        CT,[u0,u1,u2,u3,v]
    Returns (u: list[int], v: int)
    """
    line = line.strip()
    if not line.startswith("CT,["):
        return None
    inner = line[4:-1]          # strip "CT,[" and "]"
    nums  = list(map(int, inner.split(',')))
    if len(nums) != LWE_N + 1:
        return None
    return nums[:LWE_N], nums[LWE_N]

# ─────────────────────────────────────────────────────────────────────────────
def compute_encrypted_pwm(u, v):
    """
    Received CT encodes lux (single integer, not bit-by-bit).

    Step 1 — Scale by Kp_int:   CT(Kp_int × lux)
        u_kp = Kp_int × u  mod Q
        v_kp = Kp_int × v  mod Q

    Step 2 — Compute error:     CT(Kp_int × error)
        error = setpoint − lux
        u_pwm = −u_kp                      mod Q   (negate lux term)
        v_pwm = −v_kp + SETPOINT_V_SHIFT   mod Q   (add setpoint constant)

    Decrypts to: Kp_int × (setpoint − lux)
    Arduino divides by KP_SCALE → Kp × error → PWM
    """
    # Step 1
    u_kp = [mod_q(KP_INT * x) for x in u]
    v_kp = mod_q(KP_INT * v)

    # Step 2
    u_pwm = [mod_q(-x) for x in u_kp]
    v_pwm = mod_q(-v_kp + SETPOINT_V_SHIFT)

    return u_pwm, v_pwm

# ─────────────────────────────────────────────────────────────────────────────
# def run():
#     port = find_port()
#     ser  = serial.Serial(port, BAUD, timeout=2)
#     time.sleep(2)

#     print("=" * 50)
#     print(f"  Port      = {port}")
#     print(f"  Kp        = {KP}  (Kp_int={KP_INT})")
#     print(f"  Setpoint  = {SETPOINT_LUX} lux")
#     print(f"  Q         = {LWE_Q}")
#     print(f"  Max lux   = {MAX_PLAIN // KP_INT}  (safe range for Q)")
#     print("=" * 50)

#     while True:
#         raw = ser.readline().decode("ascii", errors="ignore").strip()
#         if not raw:
#             continue

#         if not raw.startswith("CT,"):
#             print(f"  [Arduino] {raw}")
#             continue

#         result = parse_ct_line(raw)
#         if result is None:
#             print(f"  [!] Parse error: {raw[:80]}")
#             continue

#         u, v = result
#         u_pwm, v_pwm = compute_encrypted_pwm(u, v)

#         # Send "PWM,u0,u1,u2,u3,v\n"
#         reply = "PWM," + ",".join(str(x) for x in u_pwm) + "," + str(v_pwm) + "\n"
#         ser.write(reply.encode("ascii"))
#         print(f"  CT(lux): u={u} v={v}  →  Sent CT(Kp·err): u={u_pwm} v={v_pwm}")

def run():
    port = find_port()
    ser  = serial.Serial(port, BAUD, timeout=2)
    time.sleep(2)
    print(f"Opened {port}")

    while True:
        raw = ser.readline().decode("ascii", errors="ignore").strip()
        if not raw:
            print("  [timeout] no data from Arduino")
            continue

        print(f"  [RX raw] '{raw}'")          # ← shows exactly what arrived

        if not raw.startswith("CT,"):
            print(f"  [Arduino] {raw}")
            continue

        result = parse_ct_line(raw)

        if result is None:
            print(f"  [!] parse_ct_line FAILED on: '{raw}'")   # ← parse error
            continue

        u, v = result
        print(f"  [parsed] u={u}  v={v}")

        u_pwm, v_pwm = compute_encrypted_pwm(u, v)
        reply = "PWM," + ",".join(str(x) for x in u_pwm) + "," + str(v_pwm) + "\n"

        written = ser.write(reply.encode("ascii"))
        ser.flush()                             # ← force immediate send
        print(f"  [TX] sent {written} bytes: '{reply.strip()}'")

if __name__ == "__main__":
    run()