"""The worker captures the monitor the config points at - NS_MONITOR.

The worker's DDA path used to hardcode EnumOutputs(0): it captured output
0 no matter which monitor the config named. On a multi-monitor desktop
that silently captured the wrong screen; with HDR it became a loud failure
(the captured monitor's format - SDR BGRA8 or HDR FP16 - must match the
pipeline, which follows the CAPTURED monitor's HDR state as probed by the
client). Measured on this machine: config monitor \\.\\DISPLAY2 (HDR) while
output 0 is \\.\\DISPLAY1 (SDR) -> 'capture 87 vs pipeline 10' and every
frame refused.

The contract, same shape as NS_GPU/NS_HDR (read once per worker process,
so the value is in the environment before the first launch and reapplied
on every restart - a monitor switch is a full pipeline restart):
* the client sets NS_MONITOR to the captured monitor's GDI devicename
  ('\\\\.\\DISPLAY2') before the worker starts;
* an absent/unreadable value means output 0 (the old behavior - an old
  client talking to a new worker keeps working);
* the HDR auto-probe reads the CAPTURED monitor, not the primary: on a
  mixed SDR-primary + HDR-captured desktop auto must resolve HDR from
  the monitor that is actually captured.

Checked:
* _apply_hdr_env auto mode probes the monitor named by cfg['monitor']
  (a devicename string), not the primary - verified through a stand-in
  hdr module with per-monitor answers and a call log;
* a monitor name that is not connected falls back to output 0 - the
  same fallback the capture itself applies - so the probe and the DDA
  session stay on one screen;
* forced modes still beat the probe; nothing raises;
* _apply_monitor_env puts the captured monitor's devicename into
  NS_MONITOR (a plain string the C++ getenv/strcmp side can read);
* no monitor in cfg leaves NS_MONITOR unset.
"""

import os
import sys
import types
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import startup  # noqa: E402

# The deterministic DXGI layer: devicename -> output index and back. The
# real functions enumerate dxcam; the test pins the mapping so every
# assertion below is machine-independent (which output is 0 differs per
# desktop).
FAKE_IDX = {"\\\\.\\DISPLAY1": 0, "\\\\.\\DISPLAY2": 1}
FAKE_NAME = {0: "\\\\.\\DISPLAY1", 1: "\\\\.\\DISPLAY2"}


def _install_fake_hdr() -> dict:
    """A stand-in hdr module with per-monitor answers, plus a call log."""
    state = {
        # DISPLAY1 (output 0): SDR; DISPLAY2: HDR - the mixed desktop
        # that produced the field failure.
        "answers": {
            "\\\\.\\DISPLAY1": (False, 203.0),
            "\\\\.\\DISPLAY2": (True, 480.0),
        },
        "probed": [],
    }

    class _FakeHdrModule(types.ModuleType):
        def enabled_for(self, devicename=None):
            name = devicename if devicename is not None else "\\\\.\\DISPLAY1"
            state["probed"].append(name)
            return state["answers"].get(name, (False, 203.0))[0]

        def paper_white_nits(self, devicename=None):
            name = devicename if devicename is not None else "\\\\.\\DISPLAY1"
            return state["answers"].get(name, (False, 203.0))[1]

    fake = _FakeHdrModule("hdr")
    sys.modules["hdr"] = fake
    return state


def main() -> int:
    failures = []
    real_hdr = sys.modules.get("hdr")
    real_resolve = getattr(startup, "resolve_output_idx", None)
    real_devicename = getattr(startup, "devicename_for_output_idx", None)

    startup.resolve_output_idx = lambda name: FAKE_IDX.get(name)
    startup.devicename_for_output_idx = lambda idx: FAKE_NAME.get(idx)
    state = _install_fake_hdr()
    try:
        # --- 1. the HDR auto-probe reads the captured monitor ---------
        # cfg['monitor'] is a devicename string in current configs. Auto
        # mode must answer for THAT monitor: DISPLAY2 is HDR, the
        # primary (DISPLAY1) is SDR - the old code probed the primary
        # and would have said SDR for an HDR capture.
        os.environ.pop("NS_HDR", None)
        state["probed"].clear()
        startup._apply_hdr_env({"monitor": "\\\\.\\DISPLAY2"})
        if os.environ.get("NS_HDR") != "1":
            failures.append("auto: the captured HDR monitor must set NS_HDR=1")
        if state["probed"] != ["\\\\.\\DISPLAY2"]:
            failures.append(
                f"auto: probed {state['probed']!r}, want the captured monitor only"
            )
        if os.environ.get("NS_HDR_PAPER_WHITE") != "480.0":
            failures.append(
                "auto: paper white must come from the captured "
                f"monitor (got {os.environ.get('NS_HDR_PAPER_WHITE')!r})"
            )

        # auto + an SDR captured monitor (mixed desktop, mirrored case):
        # another screen being HDR must not leak into the SDR capture.
        os.environ.pop("NS_HDR", None)
        state["probed"].clear()
        startup._apply_hdr_env({"monitor": "\\\\.\\DISPLAY1"})
        if os.environ.get("NS_HDR") != "0":
            failures.append(
                "auto: the captured SDR monitor must keep "
                "NS_HDR=0 even when another screen is HDR"
            )
        if state["probed"] != ["\\\\.\\DISPLAY1"]:
            failures.append(
                f"auto (SDR): probed {state['probed']!r}, want "
                "the captured monitor only"
            )

        # forced modes still win over any probe
        startup._apply_hdr_env({"hdr": 1, "monitor": "\\\\.\\DISPLAY1"})
        if os.environ.get("NS_HDR") != "1":
            failures.append("forced 1 must beat the probe")
        startup._apply_hdr_env({"hdr": 0, "monitor": "\\\\.\\DISPLAY2"})
        if os.environ.get("NS_HDR") != "0":
            failures.append("forced 0 must beat the probe")

        # a monitor that is not connected falls back to output 0 - the
        # capture's own fallback - so the probe still answers for the
        # screen that is actually captured, never for the stale name.
        os.environ.pop("NS_HDR", None)
        state["probed"].clear()
        startup._apply_hdr_env({"monitor": "\\\\.\\DISPLAY9"})
        if state["probed"] != ["\\\\.\\DISPLAY1"]:
            failures.append(
                f"unconnected monitor: probed {state['probed']!r}, "
                "want the output-0 fallback"
            )
        if os.environ.get("NS_HDR") != "0":
            failures.append("an unconnected monitor must probe output 0, not crash")

        # an int monitor (old configs) resolves to that output's name
        os.environ.pop("NS_HDR", None)
        state["probed"].clear()
        startup._apply_hdr_env({"monitor": 1})
        if os.environ.get("NS_HDR") != "1" or state["probed"] != ["\\\\.\\DISPLAY2"]:
            failures.append(
                f"int monitor: NS_HDR="
                f"{os.environ.get('NS_HDR')!r}, probed "
                f"{state['probed']!r} - want output 1's answer"
            )

        # --- 2. NS_MONITOR lands in the environment -------------------
        # A plain string the C++ getenv side can read; absent monitor
        # key -> no env var (the worker's fallback is output 0).
        os.environ.pop("NS_MONITOR", None)
        startup._apply_monitor_env({"monitor": "\\\\.\\DISPLAY2"})
        if os.environ.get("NS_MONITOR") != "\\\\.\\DISPLAY2":
            failures.append(
                f"NS_MONITOR={os.environ.get('NS_MONITOR')!r}, "
                "want the captured devicename"
            )

        # an int monitor resolves to the output's devicename
        os.environ.pop("NS_MONITOR", None)
        startup._apply_monitor_env({"monitor": 0})
        if os.environ.get("NS_MONITOR") != "\\\\.\\DISPLAY1":
            failures.append(
                f"NS_MONITOR(int)={os.environ.get('NS_MONITOR')!r}, "
                "want output 0's devicename"
            )

        # an unconnected monitor falls back to output 0 - same as the
        # capture - instead of shipping a stale name to the worker
        os.environ.pop("NS_MONITOR", None)
        startup._apply_monitor_env({"monitor": "\\\\.\\DISPLAY9"})
        if os.environ.get("NS_MONITOR") != "\\\\.\\DISPLAY1":
            failures.append(
                f"NS_MONITOR(unconnected)="
                f"{os.environ.get('NS_MONITOR')!r}, want the "
                "output-0 fallback"
            )

        # no monitor key at all: nothing set, no crash
        os.environ.pop("NS_MONITOR", None)
        startup._apply_monitor_env({})
        if "NS_MONITOR" in os.environ:
            failures.append("no monitor in cfg must leave NS_MONITOR unset")
    finally:
        if real_hdr is not None:
            sys.modules["hdr"] = real_hdr
        else:
            sys.modules.pop("hdr", None)
        if real_resolve is not None:
            startup.resolve_output_idx = real_resolve
        else:
            del startup.resolve_output_idx
        if real_devicename is not None:
            startup.devicename_for_output_idx = real_devicename
        else:
            del startup.devicename_for_output_idx

    print("=" * 60)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("OK: NS_MONITOR + the HDR probe follow the captured monitor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
