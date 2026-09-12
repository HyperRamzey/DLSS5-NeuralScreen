"""RGBA8 sRGB -> float16 scRGB linear: the HDR frame conversion.

An HDR desktop composes SDR content into scRGB linear light; the neural
consumer must see that linear light (the Feeder's hdr_bridge exists for
exactly this - an RGBA8 frame clipped at 1.0 is wrong pixels above SDR
white). In scRGB linear 1.0 is 80 nits, and the OS composites SDR white
at the SDR-content-brightness level (paper white, PW nits) - so SDR white
(255) maps to PW/80 in linear units (e.g. 2.54 at the 203-nit BT.2408
default). That is exactly where DWM places SDR white in the FP16 it
hands Desktop Duplication - the two capture paths (native-FP16 DDA and
converted RGBA8) stay pixel-identical, and the SDR readback's 80/PW
tonemap round-trips the white point.

The sRGB EOTF is applied per channel; alpha is forced to 1.0 (the
pipeline treats every captured frame as opaque). Output is float16 -
the NGX feature expects FP16 linear.
"""

from __future__ import annotations

import numpy as np

# The sRGB EOTF: linear below 0.04045, the standard curve above.
_SRGB_THRESH = 0.04045
_SRGB_A = 0.055
_SRGB_PHI = 12.92
_SRGB_EXP = 2.4


def _srgb_to_linear(u8: np.ndarray) -> np.ndarray:
    """sRGB 0..255 -> linear 0..1, float32 (vectorized, exact curve)."""
    c = u8.astype(np.float32) / 255.0
    lin = np.where(
        c <= _SRGB_THRESH,
        c / _SRGB_PHI,
        ((c + _SRGB_A) / (1.0 + _SRGB_A)) ** _SRGB_EXP,
    )
    return lin.astype(np.float32)


def rgba8_to_scrgb_f16(frame: np.ndarray, paper_white_nits: float) -> np.ndarray:
    """RGBA8 sRGB -> float16 scRGB linear light, scaled to paper white.

    SDR white (255) maps to paper_white_nits/80 in linear units (scRGB
    1.0 = 80 nits): the OS composites SDR content at the paper-white
    brightness on the HDR desktop, so the network sees values above 1.0
    exactly where the desktop really has them - byte-identical to what
    DWM hands a native FP16 capture of the same screen. Pure function;
    the caller owns the paper-white value (the OS answer or the BT.2408
    default).
    """
    if frame.ndim != 3 or frame.shape[2] != 4:
        raise ValueError(f"want HxWx4 RGBA8, got {frame.shape}")
    if not paper_white_nits > 0:
        raise ValueError(f"paper_white_nits must be > 0, got {paper_white_nits}")
    lin = _srgb_to_linear(frame)
    lin[..., :3] *= np.float32(paper_white_nits / 80.0)
    lin[..., 3] = 1.0
    return lin.astype(np.float16)
