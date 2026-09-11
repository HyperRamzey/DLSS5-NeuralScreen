"""The HDR wiring: the desktop probe reaches the worker as NS_HDR.

The contract (auto-first, like the Feeder's hdr_bridge):
* config 'hdr' -1/absent  -> auto: NS_HDR=1 only when the captured monitor
  really is an HDR desktop (hdr.enabled_for, the DisplayConfig probe - NOT
  the registry, which cannot answer per-monitor);
* config 'hdr' 1          -> forced on, NS_HDR=1 even if the probe says SDR
  (the escape hatch for broken drivers);
* config 'hdr' 0          -> forced off, NS_HDR=0 (SDR identical to today).

The worker reads NS_HDR once at process start, so the value must be in the
environment BEFORE the first worker is launched (the same contract as
NS_SPOUT/NS_GPU), and reapplied on every restart.

Checked:
* auto with an HDR desktop sets NS_HDR=1;
* forced 0 keeps NS_HDR=0 even on an HDR desktop;
* forced 1 sets NS_HDR=1;
* the paper-white value lands in NS_HDR_PAPER_WHITE (nits, always a real
  number - the BT.2408 default when the OS does not answer).
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import startup  # noqa: E402
import hdr      # noqa: E402


def main() -> int:
    failures = []
    # This machine's primary desktop is HDR (test_hdr_probe verifies that),
    # so auto mode has a real answer to read.
    auto_on = hdr.enabled_for(None)
    if auto_on is not True:
        # not an HDR desktop right now - the auto case cannot be asserted
        # here; only the forced cases run below.
        print("[skip] primary desktop is not HDR right now")

    # 1. auto (absent key) on an HDR desktop -> NS_HDR=1
    os.environ.pop("NS_HDR", None)
    startup._apply_hdr_env({})
    got = os.environ.get("NS_HDR")
    want = "1" if auto_on else "0"
    if got != want:
        failures.append(f"auto: NS_HDR={got!r}, want {want!r}")

    # 2. auto (-1) behaves like absent
    startup._apply_hdr_env({"hdr": -1})
    got = os.environ.get("NS_HDR")
    if got != want:
        failures.append(f"auto (-1): NS_HDR={got!r}, want {want!r}")

    # 3. forced off (0) stays off even on an HDR desktop
    startup._apply_hdr_env({"hdr": 0})
    if os.environ.get("NS_HDR") != "0":
        failures.append("forced 0: NS_HDR is not '0'")

    # 4. forced on (1) is on even when the probe says SDR
    startup._apply_hdr_env({"hdr": 1})
    if os.environ.get("NS_HDR") != "1":
        failures.append("forced 1: NS_HDR is not '1'")

    # 5. paper white: always a real number, and the env carries it
    startup._apply_hdr_env({})
    pw = os.environ.get("NS_HDR_PAPER_WHITE")
    try:
        pw_val = float(pw)
        if not pw_val > 0:
            failures.append(f"NS_HDR_PAPER_WHITE={pw!r} is not > 0")
    except (TypeError, ValueError):
        failures.append(f"NS_HDR_PAPER_WHITE={pw!r} is not a number")

    print("=" * 60)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("OK: NS_HDR follows auto/forced from the config, paper white set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
