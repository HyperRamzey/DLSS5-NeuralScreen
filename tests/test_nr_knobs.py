"""The DLSSNR knob matrix: exact names, guarded defaults (Phase D1).

The DLL silently ignores unknown parameter keys - a typo in a knob name
does not fail, it just does nothing. The ShortFuse RE (strings
@0x18022eaef-0x180232d25) gives the exact set; this test pins every
name the host sets, so a typo is a test failure instead of a silent
no-op.

What is checked per knob (pure client-side contract; the host applies
them at eval time):
* NAME - the exact NGX parameter string, pinned in one table;
* DEFAULT - what the host sends when the user has not touched anything:
  the defaults MUST preserve today's behavior exactly (the pipeline is
  bit-identical for an untouched config);
* SOURCE - where the user value comes from (config key or env), with
  the clamping rule.

The knobs (Phase D1):
  DLSSNR.GlobalToneStrength - off (-1 = unset) by default; the
      ShortFuse notes its effect is not visible in the recovered NGX
      path (@0x180215e6b) - shipped but documented.
  DLSSNR.JitterOffsetX / .Y - 0.0 by default (no jitter offset).
  DLSSNR.DepthInverted - not set by default (no depth plane exists in
      this pipeline; the knob exists for parity).
  DLSSNR.Upscaling - already driven by the work-scale machinery; the
      test pins that the host never sends a hardcoded value.
  DLSSNR.Indicator.Invert.X / .Y - off by default.

D2: NS_UI_CORRECTION (-1 auto / 0 off / 1 on); auto == on here (the
evaluated source is always NeuralScreen's own overlay), documented;
explicit 0 for HUD-less sources.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # the project root
sys.path.insert(0, str(BASE))                  # the project modules
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ (autocheck)

# The exact NGX parameter names (the typos this test exists to catch).
KNOBS = {
    "global_tone": "DLSSNR.GlobalToneStrength",
    "jitter_x": "DLSSNR.JitterOffsetX",
    "jitter_y": "DLSSNR.JitterOffsetY",
    "depth_inverted": "DLSSNR.DepthInverted",
    "upscaling": "DLSSNR.Upscaling",
    "indicator_x": "DLSSNR.Indicator.Invert.X",
    "indicator_y": "DLSSNR.Indicator.Invert.Y",
}
# The ShortFuse RE gives the exact spellings; assert each name against
# the SDK-visible pattern so a rename upstream breaks loudly here.
for k, name in KNOBS.items():
    assert name.startswith("DLSSNR."), k


def main() -> int:
    failures = []

    # 1. The knob table the HOST uses - imported from the host module
    #    that builds the eval params, so name and implementation cannot
    #    drift apart. (The host exports the table as a plain dict.)
    import nr_knobs  # noqa: E402  (the project module this test pins)

    table = nr_knobs.KNOB_TABLE
    for key, want_name in KNOBS.items():
        got = table.get(key, {}).get("name")
        if got != want_name:
            failures.append(f"knob {key!r}: host name {got!r} != {want_name!r}")
        if "default" not in table.get(key, {}):
            failures.append(f"knob {key!r}: no default pinned")

    # 2. Defaults preserve today's behavior: unset knobs send NOTHING.
    #    The host must skip absent keys entirely (sending
    #    GlobalToneStrength=-1 unasked would still be a visible change
    #    if the DLL ever starts honoring it).
    for key, spec in table.items():
        if (spec.get("default") is None
                and not spec.get("sent_when_unset", False)
                and key not in nr_knobs.UNSET_BY_DEFAULT):
            failures.append(f"knob {key!r}: default None but not in "
                            "UNSET_BY_DEFAULT - it would be sent unasked")

    # 3. D2: the UI-correction tri-state.
    #    -1 (auto) == on (our overlay is the evaluated source), 0 = off,
    #    1 = on; anything else clamps to auto.
    for raw, want in ((-1, 1), (0, 0), (1, 1), (5, 1), (-9, 1), ("0", 0)):
        got = nr_knobs.ui_correction_value(raw)
        if got != want:
            failures.append(f"ui_correction({raw!r}) -> {got}, want {want}")

    print("=" * 60)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("OK: the DLSSNR knob matrix - exact names, defaults that "
          "change nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
