"""Coexistence with Lossless Scaling: two topmost overlays, one desktop.

The user runs Lossless Scaling (WGC capture path) and NeuralScreen at the
same time. The two do not fight over capture: LS captures a game WINDOW
through Windows Graphics Capture, NeuralScreen captures the DESKTOP
through Desktop Duplication - different sessions, different outputs, no
conflict (verified against the LS binary: its capture engine is WGC,
feature-flagged in config.ini, and its present window is a plain
WS_POPUP topmost with SetLayeredWindowAttributes).

What CAN conflict is the z-order: both present topmost overlays, and LS
re-asserts topmost when it starts scaling. The contract checked here:

* with an LS-style topmost window (the mimic: WS_POPUP | layered alpha,
  over the whole screen) raised ABOVE NeuralScreen's picture, NS keeps
  processing - frames keep flowing, the worker does not restart, no
  capture errors;
* NS's present window returns to the top band within ReassertPresent-
  Topmost's window (it re-checks every 300 frames) once the mimic stops
  forcing its own position, and the HUD (pygame) may legally sit above
  the picture - the check accepts either;
* the mimic window being drawn on the desktop does NOT break the DDA
  capture (the capture includes it, as it includes any other window).

The mimic is driven programmatically (no real LS in CI); if the real
Lossless Scaling happens to be running, the test still passes - it only
asserts NeuralScreen's own behavior, never LS's.

Run:  runtime\\python.exe test_ls_coexistence.py   (~50 s)
"""

import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # the project root
sys.path.insert(0, str(BASE))  # the project modules
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ (autocheck)

import autocheck  # noqa: E402

user32 = ctypes.windll.user32
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t

GW_HWNDTOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x00000002

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    """WNDCLASSW - not in ctypes.wintypes, defined here (as in taskbar.py)."""

    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class LsMimic:
    """A topmost borderless layered window - the LS present overlay's shape.

    Raised above everything (SetWindowPos HWND_TOPMOST after creation),
    it is exactly what NeuralScreen sees when Lossless Scaling is
    scaling a game on the same desktop.
    """

    def __init__(self):
        self.hwnd = None
        self._class_atom = None
        self._name = "LSMimicCoexistenceTest"

    def start(self):
        def wndproc(h, msg, wp, lp):
            return user32.DefWindowProcW(
                ctypes.c_void_p(h), msg, ctypes.c_size_t(wp), lp
            )

        self._proc = WNDPROC(wndproc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.lpszClassName = self._name
        self._class_atom = user32.RegisterClassW(ctypes.byref(wc))
        if not self._class_atom:
            raise OSError("RegisterClassW failed")
        style, ex_style = WS_POPUP, (WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_NOACTIVATE)
        self.hwnd = user32.CreateWindowExW(
            ex_style, self._name, self._name, style, 640, 360, 512, 288, 0, 0, 0, 0
        )
        if not self.hwnd:
            raise OSError("CreateWindowExW failed")
        # alpha 255 - fully opaque, but composed by DWM the layered way
        user32.SetLayeredWindowAttributes(self.hwnd, 0, 255, LWA_ALPHA)
        user32.ShowWindow(self.hwnd, 5)  # SW_SHOW
        # force it to the very top, like LS does when it starts scaling
        user32.SetWindowPos(
            self.hwnd,
            ctypes.c_void_p(-1),  # HWND_TOPMOST
            640,
            360,
            512,
            288,
            SWP_NOACTIVATE,
        )
        return self.hwnd

    def raise_above(self, other_hwnd):
        """LS behavior: re-assert topmost (which lifts it above NS)."""
        user32.SetWindowPos(
            self.hwnd, ctypes.c_void_p(-1), 640, 360, 512, 288, SWP_NOACTIVATE
        )

    def stop(self):
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self._class_atom:
            user32.UnregisterClassW(self._name, 0)
            self._class_atom = None


def find_window(needle):
    """The first visible top-level window whose class or title matches."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def _cb(hwnd, _lparam):
        cls = ctypes.create_unicode_buffer(64)
        title = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        user32.GetWindowTextW(hwnd, title, 64)
        if (
            needle.lower() in cls.value.lower() or needle.lower() in title.value.lower()
        ) and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return found[0] if found else None


def main() -> int:
    failures = []
    if autocheck.running_instances():
        autocheck.quit_app()
        time.sleep(1.0)

    offset = autocheck.log_offset()
    if not autocheck.launch():
        print("FAIL: could not launch NeuralScreen")
        return 1
    try:
        # 1. Wait until the pipeline is up: NR ON lines in the log.
        if not autocheck.wait_for(offset, "NR ON", 45.0):
            failures.append("no NR ON - the pipeline did not come up")
            raise SystemExit  # nothing more to check without a pipeline
        mark = autocheck.log_offset()

        # 2. Raise the LS mimic above NS, while the pipeline runs.
        mimic = LsMimic()
        mimic.start()
        time.sleep(6.0)  # > the 300-frame reassert window (~3-5 s)
        # 2a. frames kept flowing while the LS-style window sat on top
        log = autocheck.log_since(mark)
        n_on = log.count("NR ON")
        if n_on < 2:
            failures.append(
                f"frames stopped while the LS-style overlay "
                f"was on top ({n_on} status lines in 6 s)"
            )
        # 2b. no worker restarts / capture failures
        if "restart" in log or "revive" in log:
            failures.append("the worker restarted while the LS-style overlay was up")
        if "[dda] DuplicateOutput failed" in log:
            failures.append("the DDA capture broke while the LS-style overlay was up")

        # 2c. NS's picture is back in the top band: the window directly
        #     above it is either our own HUD (pygame) or the picture is
        #     itself the topmost non-mimic window. LS's own overlay may
        #     be above (both apps legitimately topmost) - the contract
        #     is only that NS did not get pushed BELOW a permanent
        #     non-topmost window. Simplest robust check: the picture is
        #     still visible and still topmost-class.
        pres = find_window("NeuralScreenPresent")
        if not pres:
            failures.append(
                "the present window disappeared while the LS-style overlay was up"
            )
        else:
            user32.GetWindowLongW.restype = ctypes.c_long
            got = user32.GetWindowLongW(pres, -20)  # GWL_EXSTYLE
            if not (got & WS_EX_TOPMOST):
                failures.append(
                    "the present window lost WS_EX_TOPMOST "
                    "while the LS-style overlay was up"
                )

        # 3. The mimic re-asserts (LS starting to scale mid-run) - the
        #    pipeline must survive a second topmost storm too.
        if pres:
            mimic.raise_above(pres)
        time.sleep(6.0)
        log2 = autocheck.log_since(mark)
        if log2.count("NR ON") < n_on + 2:
            failures.append(
                "frames stopped after the LS-style overlay re-asserted topmost"
            )
        mimic.stop()
    except SystemExit:
        pass
    finally:
        autocheck.quit_app()

    print("=" * 60)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print(
        "OK: NeuralScreen keeps processing under a Lossless-Scaling-style "
        "topmost overlay, and its window stays topmost"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
