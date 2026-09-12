"""The DLSSNR knob matrix: exact NGX names, defaults that change nothing.

The DLL silently ignores unknown parameter keys - a typo in a knob name
does not fail, it just does nothing. The ShortFuse RE (strings
@0x18022eaef-0x180232d25) gives the exact spellings; this module is the
single source of truth both sides import, so the host's params and the
tests cannot drift apart.

The defaults are the contract: every knob ships in the state that
preserves today's pipeline exactly. A knob the user has not touched is
NOT sent at all (an explicit -1 for GlobalToneStrength would still be a
visible change if the DLL ever starts honoring it), except the few the
pipeline always sends (Upscaling rides the work-scale machinery).

Phase D1/D2 of docs/PLAN-missing-features.md.
"""
from __future__ import annotations

# The knob table: key -> {name, default, sent_when_unset}.
#   name     - the EXACT NGX parameter string (the typos this table
#              exists to catch; the DLL ignores unknown keys silently).
#   default  - the value that preserves today's behavior. None means
#              "do not send the key at all" (see UNSET_BY_DEFAULT).
KNOB_TABLE: dict[str, dict] = {
    # GlobalToneStrength: the ShortFuse notes its effect is not visible
    # in the recovered NGX path (@0x180215e6b). Shipped unset: the knob
    # exists for parity and forward compatibility, not for a visible
    # change today.
    "global_tone": {"name": "DLSSNR.GlobalToneStrength", "default": None},
    # Jitter offsets: 0.0 = no offset (today's behavior).
    "jitter_x": {"name": "DLSSNR.JitterOffsetX", "default": 0.0},
    "jitter_y": {"name": "DLSSNR.JitterOffsetY", "default": 0.0},
    # Depth: this pipeline has no depth plane; the knob exists for
    # parity (crop/region capture may add one later).
    "depth_inverted": {"name": "DLSSNR.DepthInverted", "default": None},
    # Upscaling: ALWAYS sent (the work-scale machinery drives it); the
    # default here is only the pin - the value comes from the stream.
    "upscaling": {"name": "DLSSNR.Upscaling", "default": 0,
                  "sent_when_unset": True},
    # Indicator inversion: off.
    "indicator_x": {"name": "DLSSNR.Indicator.Invert.X", "default": None},
    "indicator_y": {"name": "DLSSNR.Indicator.Invert.Y", "default": None},
}

# Knobs whose default is None: NOT sent unless the user sets them.
UNSET_BY_DEFAULT = ("global_tone", "depth_inverted", "indicator_x",
                    "indicator_y")


def ui_correction_value(raw) -> int:
    """The UI-correction tri-state (Phase D2) as the host's int.

    -1 (auto) reads as ON: the evaluated source is always NeuralScreen's
    own overlay, so auto == on today (documented with the ShortFuse's
    own wording). 0 = explicitly off - for users who feed HUD-less
    sources. 1 = explicitly on. Anything unparseable clamps to auto.
    """
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return 1
    if v == 0:
        return 0
    return 1
