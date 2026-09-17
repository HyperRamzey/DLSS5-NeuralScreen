"""Every acquired DXGI reference is released on every path (audit B1 follow-up).

Found while writing up the B1 fix for issue #89, in the fix itself: the
high-colour capture path was added with its own DuplicateOutput1 request, and
the release of the IDXGIOutput5 reference stayed where it was - inside the HDR
branch. The reference is created by an UNCONDITIONAL QueryInterface above all
the branches, so the release has to be unconditional too.

The paths that leaked:

- an 8-bit display (this bench): never enters the HDR branch;
- an HDR-capable display reporting 8 bits per colour - the reporter's own log
  line in #89 - which a "deeper than 8 bits" condition does not cover either;
- a display whose DuplicateOutput1 is refused, since the failure branch is not
  the one holding the release.

One leaked reference per capture open, and the capture opens on every pipeline
rebuild: a monitor switch, a window-mode change, a settings change. The object
is a DXGI output interface, so the reference count is on the adapter's output,
not on a per-open allocation - the cost is that the output is never released
while the process lives, and the fix is a one-line move, not a rewrite.

The test counts the acquisition and the release in the DDA open path. Both must
be present, the release must not sit inside a conditional, and the acquire must
be the one that actually guards it.

Run: runtime\\python.exe tests\\test_dda_output5_released.py
"""
from __future__ import annotations

import re
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
SOURCE = (BASE / "native" / "dlss5-feed-host64.cpp").read_text(encoding="utf-8")


def dda_open() -> str:
    begin = SOURCE.index("static bool OpenDda")
    end = SOURCE.index("// The phase profiler", begin)
    return SOURCE[begin:end]


def main() -> int:
    failures = []
    body = dda_open()

    # 1. The reference exists exactly once - acquired unconditionally.
    acquires = body.count("__uuidof(IDXGIOutput5)")
    if acquires != 1:
        failures.append(f"the IDXGIOutput5 interface is acquired {acquires} "
                        f"times - the release count below assumes one")
    if "SUCCEEDED(output->QueryInterface(\n        __uuidof(IDXGIOutput5)" \
            not in body.replace("\r\n", "\n"):
        failures.append("the IDXGIOutput5 acquisition is no longer the "
                        "unconditional QueryInterface this test expects - a "
                        "conditional acquisition needs a matching conditional "
                        "release")

    # 2. Exactly one release per acquisition.
    releases = body.count("output5->Release()")
    if releases != acquires:
        failures.append(f"{acquires} acquisition(s) but {releases} release(s) "
                        f"of IDXGIOutput5 - a leak")

    # 3. The release must be guarded by the SAME fact that guards the acquire.
    #    Anything else (a bit-depth test, the HDR mode flag, a specific format)
    #    leaves the paths it does not cover leaking.
    guard = re.search(
        r"if \(has_output5\)\s*\n\s*output5->Release\(\);", body)
    if not guard:
        failures.append("the IDXGIOutput5 release is not guarded by "
                        "`has_output5` - the same flag the acquisition sets. "
                        "Guarding it with a capture mode instead is what leaked "
                        "on the 8-bit and the refused-FP16 paths")

    # 4. No release may sit inside a mode branch: that is the shape that leaked.
    if re.search(r"output5->Release\(\);", body.split("if (has_output5)")[0]):
        failures.append("an IDXGIOutput5 release sits before the unconditional "
                        "one, i.e. inside a capture-mode branch")

    # 5. The other interfaces in the same function keep their pairs, so a fix
    #    here cannot quietly unbalance them.
    for name in ("out6", "output1", "output", "adapter", "factory"):
        if f"{name}->Release()" not in body:
            failures.append(f"{name} is no longer released in the DDA open "
                            f"path")

    for failure in failures:
        print("FAIL:", failure)
    if failures:
        return 1
    print("OK: the IDXGIOutput5 reference is acquired and released on the "
          "same, unconditional, path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
