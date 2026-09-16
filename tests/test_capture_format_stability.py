"""Pin the 10-bit SDR capture contract from issues #86 and #89.

The reporter's log alternates DDA source frames between BGRA8 and FP16. Each
change rebuilds the cross-API bridge and produces visible flicker. v1.12 asked
DuplicateOutput1 for BGRA8 only, but two fresh logs prove that real drivers can
still alternate formats after that call succeeds. This host cannot force the
condition, so the test verifies the stronger contract: SDR uses the original
DuplicateOutput conversion; DuplicateOutput1 is reserved for opt-in HDR.

Run: runtime\\python.exe tests\\test_capture_format_stability.py
"""
from __future__ import annotations

import sys
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
SOURCE = (BASE / "native" / "dlss5-feed-host64.cpp").read_text(encoding="utf-8")


def main() -> int:
    failures = []
    begin = SOURCE.index("static bool OpenDda")
    end = SOURCE.index("// The phase profiler", begin)
    dda = SOURCE[begin:end]

    # SDR must take the documented 32-bit BGRA conversion path directly.  In
    # particular it must not advertise FP16 to DuplicateOutput1 again.
    try:
        sdr = dda.index("if (!g_dda_hdr_mode)")
        hdr = dda.index("else if (SUCCEEDED(output->QueryInterface", sdr)
        sdr_branch = dda[sdr:hdr]
        if "output1->DuplicateOutput(g_dda_d11, &g_dda_dup)" not in sdr_branch:
            failures.append("SDR no longer uses DuplicateOutput's BGRA conversion")
        if "DuplicateOutput1(" in sdr_branch:
            failures.append("SDR still reaches the driver-dependent Output5 format path")
    except ValueError:
        failures.append("the SDR/HDR duplication split is missing")
    if "DuplicateOutput1(g_dda_d11, 0, _countof(hdr_formats)" not in dda:
        failures.append("HDR no longer requests FP16 through DuplicateOutput1")
    if "if (g_dda_hdr_mode && FAILED(hr))" not in dda:
        failures.append("HDR has no stable SDR fallback when Output5 refuses")
    if "SDR capture fixed to BGRA8 through legacy duplication" not in dda:
        failures.append("the stable SDR path has no diagnostic for future logs")

    # A genuinely legacy/driver-refused format change still rebuilds only the
    # bridge. Removing that guard would revive the old full DDA reopen storm.
    stage = SOURCE[SOURCE.index("static StageResult StageCapturedFrame"):]
    if "CloseCaptureBridge();\n            return StageResult::FormatChanged;" not in stage:
        failures.append("a legacy format change no longer tears down only the bridge")

    for failure in failures:
        print("FAIL:", failure)
    if failures:
        return 1
    print("OK: SDR DDA uses stable BGRA8 conversion; Output5 is HDR-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
