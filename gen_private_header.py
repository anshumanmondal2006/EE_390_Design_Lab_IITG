# gen_private_header.py
import json
from pathlib import Path

KEY_DIR = Path("lwe_keys")

with open(KEY_DIR / "lwe_secret_key.json", "r") as f:
    sk = json.load(f)

N = sk["N"]
s = sk["s"]

s_values = ", ".join(str(int(x)) for x in s)

header = f"""#ifndef LWE_PRIVATE_KEY_H
#define LWE_PRIVATE_KEY_H

// ============================================================
//  WARNING — SECRET KEY
//  Do NOT commit this file to version control.
//  Do NOT share this file.
//  Flash to Arduino and delete from PC if security matters.
// ============================================================

#include <Arduino.h>

static const int16_t LWE_s[LWE_N] = {{ {s_values} }};

#endif  // LWE_PRIVATE_KEY_H
"""

out_path = KEY_DIR / "lwe_private_key.h"
with open(out_path, "w") as f:
    f.write(header)

print(f"Written: {out_path}")
print(f"  N={N},  s={s}")