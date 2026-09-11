"""HDR desktop probing - the desktop analog of the Feeder's color-space query.

The Feeder's add-on asks ReShade what color space the game's swapchain is
in; the desktop has no ReShade, so the same question goes to the OS through
the DisplayConfig API. DXGI formats cannot answer it: R10G10B10A2 is
legitimately either 10-bit SDR or HDR10, and the desktop duplication format
does not say which monitor is HDR either (a mixed SDR+HDR desktop has one
answer per screen).

Two questions, both per-monitor:

  enabled_for(devicename)  - is THIS monitor an HDR desktop right now?
  sdr_white_level(devname)  - how bright SDR white is on it, in nits
                             (Windows' "SDR content brightness" slider;
                              the input for paper-white scaling).

Both answer False/None instead of raising: a probe must never take the
capture down - the same rule the environment header follows.

Layout notes (all verified empirically against Windows build 28000):

* DISPLAYCONFIG_PATH_INFO is sourceInfo, targetInfo, flags - the docs'
  description lists flags first, but the ABI has it last. Getting this
  wrong shifts every LUID by four bytes and every per-target query
  answers ERROR_INVALID_PARAMETER (87) with garbage ids.
* GET_ADVANCED_COLOR_INFO is type 6 (type 5 is virtual-resolution
  support) and takes a 24-byte struct (header + bits only).
* GET_SOURCE_NAME takes 212 bytes on released Windows but 84 on this
  Insider build - both are tried.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

# DisplayConfig: query only what is actually active on the desktop right now.
QDC_ONLY_ACTIVE_PATHS = 0x2

# Device-info request types (DISPLAYCONFIG_DEVICE_INFO_TYPE).
# NOTE: verified empirically - 6, not 5, is GET_ADVANCED_COLOR_INFO
# (5 is GET_SUPPORT_VIRTUAL_RESOLUTION and answers ERROR_INVALID_PARAMETER
# with the advanced-color struct).
GET_SOURCE_NAME = 1
GET_TARGET_PREFERRED_MODE = 2
GET_ADVANCED_COLOR_INFO = 6
GET_SDR_WHITE_LEVEL = 7

# DISPLAYCONFIG_ADVANCED_COLOR_INFO.bits - the two defined bits.
ADVANCED_COLOR_SUPPORTED = 0x1
ADVANCED_COLOR_ENABLED = 0x2


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _InfoHeader(ctypes.Structure):
    """DISPLAYCONFIG_DEVICE_INFO_HEADER: the request envelope."""
    _fields_ = [
        ("type", wintypes.UINT),
        ("size", wintypes.UINT),
        ("adapterId", _LUID),
        ("id", wintypes.UINT),
    ]


class _PathSourceInfo(ctypes.Structure):
    """DISPLAYCONFIG_PATH_SOURCE_INFO, per wingdi.h: LUID, id, the
    modeInfoIdx/cloneGroupId union (UINT32), then statusFlags (UINT32).
    20 bytes. The statusFlags field is easy to miss - without it every
    target offset shifts by four and the per-target queries get garbage.
    """
    _fields_ = [
        ("adapterId", _LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class _PathTargetInfo(ctypes.Structure):
    """DISPLAYCONFIG_PATH_TARGET_INFO - the full 48-byte layout from
    wingdi.h: LUID, id, modeInfoIdx union (UINT32), technology, rotation,
    scaling, refreshRate rational, scanline ordering, availability BOOL,
    statusFlags. The union is a UINT32 - modelling it as USHORT+pad was
    what broke the source-side offsets."""
    _fields_ = [
        ("adapterId", _LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("rotation", wintypes.UINT),
        ("scaling", wintypes.UINT),
        ("refreshRate", wintypes.ULONG * 2),   # DISPLAYCONFIG_RATIONAL
        ("scanLineOrdering", wintypes.UINT),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.UINT),
    ]


class _PathInfo(ctypes.Structure):
    """DISPLAYCONFIG_PATH_INFO: one active display path.

    Field order verified empirically: sourceInfo, targetInfo, flags - the
    C layout. Putting flags first (an easy mistake - the docs describe it
    first) shifts every LUID by four bytes and the downstream queries
    answer ERROR_INVALID_PARAMETER with garbage ids.
    """
    _fields_ = [
        ("sourceInfo", _PathSourceInfo),
        ("targetInfo", _PathTargetInfo),
        ("flags", wintypes.UINT),
    ]


class _ModeInfo(ctypes.Structure):
    """DISPLAYCONFIG_MODE_INFO (the union tail is never read here)."""
    _fields_ = [
        ("infoType", wintypes.UINT),
        ("id", wintypes.UINT),
        ("adapterId", _LUID),
        ("_tail", ctypes.c_byte * 64),
    ]


class _SourceName(ctypes.Structure):
    """DISPLAYCONFIG_SOURCE_DEVICE_NAME: the GDI \\\\.\\\\DISPLAYn name.

    Released Windows takes the full documented 212-byte struct (header +
    32 WCHAR GDI name + 64 WCHAR friendly name); this Insider build
    validates 84 bytes (header + the GDI name) and rejects 212. The query
    helper tries both - only the GDI name is read either way.
    """
    _fields_ = [
        ("header", _InfoHeader),
        ("viewGdiDeviceName", wintypes.WCHAR * 32),      # CCHDEVICENAME
        ("_friendly", wintypes.WCHAR * 64),  # only present for the 212 layout
    ]


def _query_source_name(user32, path):
    """The GDI \\\\.\\\\DISPLAYn name of a path's source, or None.

    Tries the documented 212-byte size first (released Windows), then the
    84-byte form this Insider build accepts. Both fill viewGdiDeviceName.
    """
    for size in (ctypes.sizeof(_SourceName), 84):
        name = _SourceName()
        name.header.type = GET_SOURCE_NAME
        name.header.size = size
        name.header.adapterId = path.sourceInfo.adapterId
        name.header.id = path.sourceInfo.id
        if user32.DisplayConfigGetDeviceInfo(ctypes.byref(name)) == 0:
            return name.viewGdiDeviceName
    return None


class _AdvancedColorInfo(ctypes.Structure):
    """DISPLAYCONFIG_ADVANCED_COLOR_INFO: the HDR state of one target.
    header + the bits union = 24 bytes (verified; a 28-byte layout with an
    extra trailing field is rejected)."""
    _fields_ = [
        ("header", _InfoHeader),
        ("bits", wintypes.UINT),
    ]


class _SdrWhiteLevel(ctypes.Structure):
    """DISPLAYCONFIG_SDR_WHITE_LEVEL: SDR white in thousandths of 80 nits."""
    _fields_ = [
        ("header", _InfoHeader),
        ("SDRWhiteLevel", wintypes.UINT),
    ]


def _query_display_config():
    """[(path, gdi_source_name), ...] for every active display path.

    The GDI name (\\\\.\\\\DISPLAY1) comes from a per-path GET_SOURCE_NAME
    query - that is the identity every other part of this program uses for
    monitors (capture.list_monitors, config.json).
    """
    user32 = ctypes.windll.user32
    n_paths_buf = wintypes.UINT(0)
    n_modes_buf = wintypes.UINT(0)
    # Size the two arrays. Two separate out-params: sharing one variable
    # would let the second write clobber the first (seen in testing:
    # paths=0 and everything downstream empty).
    if user32.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths_buf),
            ctypes.byref(n_modes_buf)):
        return []
    # The mode array is oversized on purpose: paths and modes count
    # differently and the caller only walks the paths.
    paths = (_PathInfo * n_paths_buf.value)()
    modes = (_ModeInfo * max(n_modes_buf.value, n_paths_buf.value * 4))()
    n_paths = wintypes.UINT(n_paths_buf.value)
    n_modes = wintypes.UINT(n_modes_buf.value)
    if user32.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), paths,
            ctypes.byref(n_modes), modes, None):
        return []
    out = []
    for i in range(n_paths.value):
        p = paths[i]
        name = _query_source_name(user32, p)
        if name is None:
            continue
        out.append((p, name))
    return out


def _target_info(path, req_type, struct_cls):
    """One DisplayConfigGetDeviceInfo query against a path's TARGET."""
    st = struct_cls()
    st.header.type = req_type
    st.header.size = ctypes.sizeof(struct_cls)
    st.header.adapterId = path.targetInfo.adapterId
    st.header.id = path.targetInfo.id
    if ctypes.windll.user32.DisplayConfigGetDeviceInfo(ctypes.byref(st)):
        return None
    return st



def _primary_devicename() -> str | None:
    """The GDI devicename EnumDisplayMonitors lists first, or None.

    The primary monitor is not always \\\\.\\\\DISPLAY1: on this machine the
    only screen is \\\\.\\\\DISPLAY2 (Windows assigns the numbers by adapter
    path, and a re-dock or driver change can leave DISPLAY1 unused).
    """
    found: list[str] = []

    class _MONINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    def _cb(hmon, _hdc, _lprect, _lparam) -> bool:
        info = _MONINFO()
        info.cbSize = ctypes.sizeof(_MONINFO)
        if ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            found.append("".join(info.szDevice).rstrip("\x00"))
        return True

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    ctypes.windll.user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)
    return found[0] if found else None


def enabled_for(devicename: str | None) -> bool:
    """Is the monitor with this GDI devicename an HDR desktop right now?

    devicename None means the primary monitor (the first one
    EnumDisplayMonitors lists - NOT a hardcoded \\\\.\\\\DISPLAY1, which is not
    always the primary: on this machine the only screen is \\\\.\\\\DISPLAY2).
    False when the monitor is not found or the OS refuses to answer -
    never an exception: a probe failure must not take the capture down.
    """
    try:
        entries = _query_display_config()
    except Exception:
        return False
    if devicename is None:
        devicename = _primary_devicename()
        if devicename is None:
            return False
    for path, name in entries:
        if name != devicename:
            continue
        info = _target_info(path, GET_ADVANCED_COLOR_INFO, _AdvancedColorInfo)
        if info is None:
            return False
        return bool(info.bits & ADVANCED_COLOR_ENABLED)
    return False


# BT.2408 reference white: the paper-white default when the OS does not
# answer the SDR-white-level query (this Insider build returns raw 0 while
# HDR is engaged; released Windows answers e.g. 1000 = 80 nits).
SDR_WHITE_DEFAULT_NITS = 203.0


def paper_white_nits(devicename: str | None) -> float:
    """Nits that linear 1.0 maps to on this monitor (paper white).

    The OS answer when there is one, otherwise the BT.2408 reference
    white. Never None and never an exception: this number feeds the
    exposure solver, which needs a real value on every path.
    """
    level = sdr_white_level(devicename)
    return SDR_WHITE_DEFAULT_NITS if level is None else float(level)


def sdr_white_level(devicename: str | None) -> float | None:
    """How bright SDR white is on this monitor, in nits.

    Windows' "SDR content brightness" slider. The API returns thousandths
    of 80 nits (1000 = 80 nits, the default). None when the monitor is
    unknown or the OS does not answer with a real value: this Insider
    build returns raw 0 while HDR is engaged, and 0 nits is not a
    brightness. Callers that need a number use paper_white_nits(),
    which falls back to the BT.2408 reference white.
    """
    try:
        entries = _query_display_config()
    except Exception:
        return None
    if devicename is None:
        devicename = _primary_devicename()
        if devicename is None:
            return None
    for path, name in entries:
        if name != devicename:
            continue
        wl = _target_info(path, GET_SDR_WHITE_LEVEL, _SdrWhiteLevel)
        if wl is None or wl.SDRWhiteLevel == 0:
            return None
        return wl.SDRWhiteLevel / 1000.0 * 80.0
    return None
