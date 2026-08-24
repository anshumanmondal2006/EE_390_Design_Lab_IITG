import json
import secrets
import random
from pathlib import Path

# ── Parameters tuned for lux range [0, 500] with Kp_int=120 ──────────────────
N   = 4
M   = 8
Q   = (2**31 - 1)    # prime (2^31 - 1), Mersenne Prime 

# MAX_PLAIN must be > Kp_int × lux_max = 120 × 500 = 60000
# Set it to Q // 2 so the encoding uses the full space
MAX_PLAIN = Q // 2   # = 65535

OUT_DIR = Path("bh1750_lwe_encrypt")
OUT_DIR.mkdir(exist_ok=True)

def rand_q():
    return secrets.randbelow(Q)

def small_error():
    # Small error keeps decryption correct
    return random.choice([-1, 0, 0, 0, 1])   # biased toward 0

# Secret key — small values reduce noise accumulation
s = [random.choice([-1, 0, 1]) for _ in range(N)]

# Public matrix A — full range
A = [[rand_q() for _ in range(M)] for _ in range(N)]

# Error vector
e = [small_error() for _ in range(M)]

# b = A^T s + e mod Q
b = []
for j in range(M):
    total = sum(s[i] * A[i][j] for i in range(N)) + e[j]
    b.append(total % Q)

# ── Save JSON ─────────────────────────────────────────────────────────────────
pub = {"N": N, "M": M, "Q": Q, "MAX_PLAIN": MAX_PLAIN, "A": A, "b": b}
sk  = {"N": N, "M": M, "Q": Q, "MAX_PLAIN": MAX_PLAIN, "s": s}

with open(OUT_DIR / "lwe_public_key.json",  "w") as f: json.dump(pub, f, indent=2)
with open(OUT_DIR / "lwe_secret_key.json",  "w") as f: json.dump(sk,  f, indent=2)

# ── Public header ─────────────────────────────────────────────────────────────
def c_2d(name, mat):
    rows = "\n".join("  {" + ", ".join(str(x) for x in row) + "}," for row in mat)
    return f"const uint32_t {name}[LWE_N][LWE_M] = {{\n{rows}\n}};"

def c_1d(name, vec):
    return f"const uint32_t {name}[LWE_M] = {{ {', '.join(str(x) for x in vec)} }};"

pub_header = f"""#ifndef LWE_PUBLIC_KEY_H
#define LWE_PUBLIC_KEY_H
#include <Arduino.h>

#define LWE_N       {N}
#define LWE_M       {M}
#define LWE_Q       {Q}UL
#define LWE_MAX_PLAIN {MAX_PLAIN}UL

{c_2d("LWE_A", A)}
{c_1d("LWE_b", b)}

#endif
"""

# ── Private header ────────────────────────────────────────────────────────────
priv_header = f"""#ifndef LWE_PRIVATE_KEY_H
#define LWE_PRIVATE_KEY_H
// WARNING: Keep secret. Do not commit to version control.
#include <Arduino.h>

static const int8_t LWE_s[LWE_N] = {{ {', '.join(str(x) for x in s)} }};

#endif
"""

with open(OUT_DIR / "lwe_public_key.h",  "w") as f: f.write(pub_header)
with open(OUT_DIR / "lwe_private_key.h", "w") as f: f.write(priv_header)

print("Generated files in ./lwe_keys/")
print(f"  Q         = {Q}  (headroom: Q/2={Q//2} > Kp_int×lux_max=60000 ✓)")
print(f"  MAX_PLAIN = {MAX_PLAIN}")
print(f"  s         = {s}")