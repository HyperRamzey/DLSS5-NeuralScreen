"""Every NVSDK_NGX failure code the header defines must be named in the log.

The worker prints NGX results through NgxResultName(); anything the switch
does not cover comes out as a bare "?", which turns a one-line diagnosis
into a support round trip. That is exactly what happened twice:

* raycornea's #99 log carries `feature requirements query failed
  0xBAD0000C` - FAIL_OutOfDate, an older-driver refusal - and the log said
  `?`. The user had no way to know the driver was the answer.
* our own bench log carries `0xBAD00012` - FAIL_NotImplemented - also `?`,
  and a code comment called it OutOfDate. The header's literals are
  DECIMAL (`NVSDK_NGX_Result_Fail | 12` is 0x0C, not 0x12), which is how
  the two got conflated.

So this test derives the required set from `nvsdk_ngx_defs.h` itself and
demands a case for each one. It fails when the SDK grows a code we do not
name, and it fails when a case is written with the wrong hex value -
`Fail | N` is converted with the same arithmetic the compiler uses.

Run:  runtime\\python.exe tests\\test_ngx_result_names.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "native" / "include" / "nvsdk_ngx_defs.h"
SOURCE = ROOT / "native" / "dlss5-feed-host64.cpp"

FAIL_BASE = 0xBAD00000


def header_codes() -> dict[int, str]:
    """{value: enumerator name} for every NVSDK_NGX_Result_FAIL_*, from the header.

    The literals are decimal (`| 12`), and the base is hex - so the value is
    computed the way C does it, not by string concatenation.
    """
    text = HEADER.read_text(encoding="utf-8")
    found: dict[int, str] = {}
    for name, offset in re.findall(
        r"(NVSDK_NGX_Result_FAIL_[A-Za-z0-9_]+)\s*=\s*"
        r"NVSDK_NGX_Result_Fail\s*\|\s*(\d+)\s*,",
        text,
    ):
        found[FAIL_BASE | int(offset)] = name
    return found


def named_codes() -> dict[int, str]:
    """{value: label} for every case of the NgxResultName switch."""
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index("static const char *NgxResultName(")
    end = text.index("default:", start)
    body = text[start:end]
    return {
        int(hexval, 16): label
        for hexval, label in re.findall(
            r"case\s+(0x[0-9A-Fa-f]+)\s*:\s*return\s+\"([^\"]+)\"", body
        )
    }


def main() -> int:
    failures: list[str] = []

    required = header_codes()
    if len(required) < 18:
        failures.append(
            f"only {len(required)} FAIL codes parsed from the header - the "
            f"pattern stopped matching (expected the full set)"
        )

    have = named_codes()

    # 1. Nothing the header defines may print as "?".
    missing = {v: n for v, n in required.items() if v not in have}
    if missing:
        failures.append(
            "codes the header defines but NgxResultName does not name "
            "(these print as '?'): "
            + ", ".join(f"{n} (0x{v:08X})" for v, n in sorted(missing.items()))
        )

    # 2. Names must agree with the header - a case at the wrong value would
    #    label a different failure. `Fail | 12` is OutOfDate (0x0C), not
    #    0x12; that conflation is why this test exists.
    for value, name in required.items():
        label = have.get(value)
        if label is None:
            continue
        expected = name[len("NVSDK_NGX_Result_FAIL_"):]
        if label != expected:
            failures.append(
                f"0x{value:08X} is labelled {label!r} but the header calls it "
                f"{expected!r}"
            )

    # 3. The two codes that actually reached user logs must be right.
    if have.get(0xBAD0000C) != "OutOfDate":
        failures.append(
            "0xBAD0000C must be OutOfDate - it is the code an older driver "
            "answers on the requirements query (raycornea, #99)"
        )
    if have.get(0xBAD00012) != "NotImplemented":
        failures.append("0xBAD00012 must be NotImplemented (Fail | 18)")
    if 0xBAD00000 not in have:
        failures.append("the bare NVSDK_NGX_Result_Fail (0xBAD00000) must be named")

    # 4. The comment that conflated the two must not come back.
    source = SOURCE.read_text(encoding="utf-8")
    if "FAIL_OutOfDate (0xBAD00012)" in source:
        failures.append(
            "the R6 comment calls 0xBAD00012 OutOfDate again - it is "
            "NotImplemented"
        )

    # 5. The requirements line must PRINT the name: the code alone cost
    #    raycornea a support round trip (his log says 0xBAD0000C, and the
    #    answer - an older driver - was in the name nobody saw). The Log call
    #    spans two lines, so the window is taken around it rather than the
    #    single line that carries the format string.
    lines = source.splitlines()
    window = ""
    for i, l in enumerate(lines):
        if "feature requirements query failed" in l:
            window = "\n".join(lines[i:i + 3])
            break
    if "NgxResultName(qrr)" not in window:
        failures.append(
            "the 'feature requirements query failed' line does not print the "
            "result name - keep NgxResultName(qrr) in that Log call"
        )

    for f in failures:
        print(f"FAIL: {f}")
    if failures:
        return 1
    print(
        f"OK: all {len(required)} NVSDK_NGX_Result_FAIL codes are named, "
        f"values match the header, and 0x0C/0x12 are not conflated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
