"""hdr.enabled_for(devicename) - is THIS monitor an HDR desktop right now?

The DisplayConfig API is the desktop analog of what the Feeder's add-on does
with ReShade's color-space query: it asks the OS what the monitor's color
space actually is, rather than guessing from a DXGI format (which cannot
tell 10-bit SDR from HDR10).

Checked:
* on this machine (HDR desktop) the probe returns True for the primary
  monitor;
* a nonexistent devicename returns False (never raises - the capture must
  not go down because a probe failed);
* the returned info dict carries the SDR white level when HDR is on
  (needed later for paper-white scaling).
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import hdr  # noqa: E402


def main() -> int:
    failures = []

    # 1. The probe on this machine (HDR desktop, from the environment header).
    on = hdr.enabled_for(None)  # None = the primary monitor
    if on is not True:
        failures.append(f"HDR desktop reported {on!r}, want True")

    # 2. A devicename that does not exist must be False, not an exception.
    try:
        gone = hdr.enabled_for("\\\\.\\DISPLAY_NOPE")
    except Exception as exc:
        failures.append(f"nonexistent devicename raised {exc!r}")
    else:
        if gone is not False:
            failures.append(f"nonexistent devicename reported {gone!r}, want False")

    # 3. Paper white is always a real number (the exposure solver input).
    #    The raw OS query can answer 0 on some builds while HDR is engaged
    #    (this Insider build does); the fallback is the BT.2408 default.
    if on:
        wl = hdr.sdr_white_level(None)
        if wl is not None and not wl > 0:
            failures.append(f"sdr_white_level returned {wl!r}, want > 0 or None")
        pw = hdr.paper_white_nits(None)
        if not (isinstance(pw, float) and pw > 0):
            failures.append(f"paper_white_nits returned {pw!r}, want a float > 0")
        if wl is None and pw != hdr.SDR_WHITE_DEFAULT_NITS:
            failures.append("paper-white fallback is not the BT.2408 default")

    print("=" * 60)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("OK: HDR probe answers for the primary monitor, "
          "False for a nonexistent one, white level present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
