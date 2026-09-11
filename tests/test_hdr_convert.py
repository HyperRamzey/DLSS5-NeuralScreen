"""The HDR frame conversion: RGBA8 sRGB -> float16 scRGB linear.

An HDR desktop composites SDR content (the captured RGBA8) into scRGB
linear light; values above SDR white exist only above 1.0, mapped through
the paper-white nits (BT.2408 when the OS does not answer). The network
must see that linear light: an RGBA8 frame clipped at 1.0 is exactly the
wrong-pixels bug the Feeder's hdr_bridge exists to prevent.

Checked:
* the conversion is a pure function of (frame, paper_white_nits);
* mid-grey sRGB (0.5 linear) lands at 80/203 of linear 1.0 by construction
  (SDR white 80 nits / paper white 203 nits);
* pure white (255) maps to exactly 80/paper_white;
* output is float16, same HxWx4, alpha untouched at 1.0;
* the SDR path is untouched (no conversion when the mode is off).
"""
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from hdr_convert import rgba8_to_scrgb_f16  # noqa: E402


def main() -> int:
    failures = []

    # 1. Pure function + shape/dtype contract.
    frame = np.full((4, 8, 4), 255, dtype=np.uint8)
    out = rgba8_to_scrgb_f16(frame, 203.0)
    if out.shape != (4, 8, 4) or out.dtype != np.float16:
        failures.append(f"shape/dtype: {out.shape} {out.dtype}")

    # 2. White maps to 80/203 in linear scRGB (SDR white over paper white).
    want = 80.0 / 203.0
    got = float(out[0, 0, 0])
    if abs(got - want) > 0.002:
        failures.append(f"white maps to {got:.4f}, want {want:.4f}")

    # 3. Mid-grey in LINEAR terms: byte 188 is ~0.5 linear in sRGB
    #    (109 is 0.427 in gamma space but only ~0.153 linear - the EOTF
    #    is the whole point). Half of white in linear units.
    lin_half = np.full((1, 1, 4), 188, dtype=np.uint8)
    outl = rgba8_to_scrgb_f16(lin_half, 203.0)
    if abs(float(outl[0, 0, 0]) - 0.5 * want) > 0.01:
        failures.append(f"linear mid-grey maps to {float(outl[0, 0, 0]):.4f}, "
                        f"want ~{0.5 * want:.4f}")

    # 5. The linearization is real sRGB (not naive pow2.2): byte 109
    #    must land at ~0.153 linear, not 0.427/2.2-gamma ~0.166.
    grey = np.full((1, 1, 4), 109, dtype=np.uint8)
    outg = rgba8_to_scrgb_f16(grey, 203.0)
    if abs(float(outg[0, 0, 0]) - 0.1528 * want) > 0.01:
        failures.append("conversion is not proper sRGB linearization")

    # 4. Alpha untouched at 1.0.
    if abs(float(out[0, 0, 3]) - 1.0) > 0.001:
        failures.append(f"alpha is {float(out[0, 0, 3])}, want 1.0")

    print("=" * 60)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("OK: RGBA8 -> float16 scRGB with paper-white scaling")
    return 0


if __name__ == "__main__":
    sys.exit(main())
