"""RGBA8 sRGB -> float16 scRGB linear: the HDR frame conversion.

An HDR desktop composes SDR content into scRGB linear light; the neural
consumer must see that linear light (the Feeder's hdr_bridge exists for
exactly this - an RGBA8 frame clipped at 1.0 is wrong pixels above SDR
white). Values above 1.0 exist only above paper white, so SDR white (80
nits) maps to 80/paper_white in linear units and everything scales from
there.

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

    SDR white (255) maps to 80/paper_white_nits in linear units - the
    OS composites SDR content at 80 nits on the HDR desktop, so the
    network sees highlights above 1.0 only when the desktop really has
    them. Pure function; the caller owns the paper-white value (the OS
    answer or the BT.2408 default).
    """
    if frame.ndim != 3 or frame.shape[2] != 4:
        raise ValueError(f"want HxWx4 RGBA8, got {frame.shape}")
    if not paper_white_nits > 0:
        raise ValueError(f"paper_white_nits must be > 0, got {paper_white_nits}")
    lin = _srgb_to_linear(frame)
    lin[..., :3] *= np.float32(80.0 / paper_white_nits)
    lin[..., 3] = 1.0
    return lin.astype(np.float16)
