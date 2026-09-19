"""Pin the high-colour capture contract from issues #86 and #89.

The reporter's log alternates DDA source frames between BGRA8 and FP16. Each
change rebuilds the cross-API bridge and produces visible flicker.

The history matters, because the rule changed twice and both times for a
measured reason:

1. v1.12 asked DuplicateOutput1 for BGRA8 only (#86). Real logs showed the
   driver still alternated formats after that call succeeded.
2. v1.13 therefore moved SDR onto the legacy `DuplicateOutput`, on the theory
   that DXGI's own 32-bit BGRA conversion is the stronger contract. It is not:
   the v1.13.1 log from issue #89 carries that very string -
   `[dda] SDR capture fixed to BGRA8 through legacy duplication` - and then
   1955 FP16<->BGRA8 flips in 133 seconds, one bridge teardown each, with
   `grab 43.0ms` against `NR 18.3 fps`.
3. The same log settles what does work. After the reporter turns HDR
   compatibility on, the code takes the IDXGIOutput5 path and the storm stops
   completely: 0 flips for the rest of the session, `grab 3.0ms`, `NR 48.6 fps`.

So the contract is not "SDR never asks Output5". It is: a display that can
produce a high-colour surface (HDR-capable, or a scan-out deeper than 8 bits)
gets its format PINNED through DuplicateOutput1, whether or not HDR
compatibility is on, because otherwise the compositor picks per frame. The
capture shader already converts FP16 to SDR, so the picture is unchanged -
HDR compatibility governs the presentation, not the capture format, exactly as
the log's own `capture=FP16 (10-bit output) - presented as SDR` says.

An 8-bit display keeps the legacy path it has always had, and a driver that
refuses FP16 still gets BGRA8 as the second advertised format.

This host cannot force the condition (its display is 8-bit and not
HDR-capable), so the test pins the decision from the source, against the log
that proved it.

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

    # 1. A high-colour display must have its format pinned through Output5,
    #    with HDR compatibility OFF as well - that is the case the log proves
    #    was flipping.
    if "high_colour_display" not in dda:
        failures.append("the high-colour decision is gone - nothing gates the "
                        "pinned path, so a flipping display is not detected")
    else:
        if "g_capture_display.enabled" not in dda:
            failures.append("the decision no longer reads the display's "
                            "advanced-colour capability - an HDR-capable "
                            "display reporting 8 bits per colour (#89) would "
                            "be missed")
        if "g_capture_deep_bits > 8" not in dda:
            failures.append("the decision no longer reads the scan-out depth - "
                            "a deep SDR display would be missed")
        # The pinned branch must run with HDR compatibility OFF. If it only
        # ran when HDR is on, the reported case would still flip.
        if "!g_dda_hdr_mode && has_output5 && high_colour_display" not in dda:
            failures.append("the pinned path is not gated on HDR "
                            "compatibility being OFF - the exact reported "
                            "case would still reach the legacy call")

    # 2. It must ask for FP16 FIRST (the stable format the log shows working)
    #    and keep BGRA8 as the fallback for a refusing driver.
    if "DuplicateOutput1(" not in dda:
        failures.append("nothing calls DuplicateOutput1 - the format cannot "
                        "be pinned")
    if "DXGI_FORMAT_R16G16B16A16_FLOAT, DXGI_FORMAT_B8G8R8A8_UNORM" \
            not in dda.replace("\n", " ").replace("  ", " "):
        failures.append("FP16 is not requested first with BGRA8 as the "
                        "fallback")

    # 3. The legacy path and its diagnostic must survive: an 8-bit display
    #    still uses it, and that log line is what made this diagnosis possible.
    if "output1->DuplicateOutput(g_dda_d11, &g_dda_dup)" not in dda:
        failures.append("the legacy DuplicateOutput path is gone - an 8-bit "
                        "display would lose the behaviour that works today")
    if "SDR capture fixed to BGRA8 through legacy duplication" not in dda:
        failures.append("the legacy path lost its diagnostic - the next log "
                        "would not show which path was taken")

    # 4. HDR compatibility keeps its own request and its stable fallback.
    if "DuplicateOutput1(g_dda_d11, 0, _countof(hdr_formats)" not in dda:
        failures.append("HDR no longer requests FP16 through DuplicateOutput1")
    if "if (g_dda_hdr_mode && FAILED(hr))" not in dda:
        failures.append("HDR has no stable SDR fallback when Output5 refuses")

    # 5. A genuinely legacy format change still tears down only the bridge.
    #    Removing that guard would revive the old full DDA reopen storm.
    stage = SOURCE[SOURCE.index("static StageResult StageCapturedFrame"):]
    if "CloseCaptureBridge();\n            return StageResult::FormatChanged;" not in stage:
        failures.append("a legacy format change no longer tears down only the "
                        "bridge")

    for failure in failures:
        print("FAIL:", failure)
    if failures:
        return 1
    print("OK: a high-colour display is pinned to one format; 8-bit and HDR "
          "paths are intact")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
