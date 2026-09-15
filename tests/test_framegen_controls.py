"""FG toggle, discrete multiplier, persisted config and frame-header wiring."""
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pygame
import commands
import protocol
import settings_io
from test_ui_buttons import build, find, paint, click


def main():
    pygame.init()
    menu = build()
    paint(menu)
    assert find(menu, "slider", "frame_multiplier") is None
    toggle = find(menu, "toggle", "frame_generation")
    assert toggle is not None
    st = SimpleNamespace(cfg={})
    with patch.object(settings_io, "save_menu_layout") as save:
        actions = click(menu, toggle)
        assert actions == [("toggle", "frame_generation")], actions
        commands.apply_menu_action(st, actions[0])
        assert st.cfg["frame_generation"]
        menu.set_state(st.cfg)
        paint(menu)
        # The multiplier rides the FG row: three small buttons beside the
        # switch, the active one filled, disabled while FG is off.
        btns = [i for i in menu.items
                if i.kind == "button" and i.key.startswith("frame_multiplier:")]
        assert len(btns) == 3, [i.extra["label"] for i in btns]
        active = [i for i in btns if i.extra["filled"]]
        assert len(active) == 1 and active[0].key == "frame_multiplier:2"
        for value, key in ((2, "frame_multiplier:2"),
                           (3, "frame_multiplier:3"),
                           (4, "frame_multiplier:4")):
            btn = next(i for i in btns if i.key == key)
            actions = click(menu, btn)
            assert actions == [("button", key)], actions
            commands.apply_menu_action(st, actions[0])
            assert st.cfg["frame_multiplier"] == value
            menu.set_state(st.cfg)
            paint(menu)
            worker = SimpleNamespace(stdin=io.BytesIO())
            protocol.send_frame(worker, 0, None, np.zeros((2, 2, 2), np.float16), False, 0,
                                no_color=True, split=0.5, frame_generation=True, frame_multiplier=value)
            header = struct.unpack(protocol.FRAME_FMT, worker.stdin.getvalue()[:struct.calcsize(protocol.FRAME_FMT)])
            flags = header[3]
            assert flags & 0x800 and flags & 0x100
            assert ((flags >> 9) & 3) + 2 == value
            assert flags >> 16 == 32768, "FG flags changed the comparison wipe"
        commands.apply_menu_action(st, ("toggle", "frame_generation"))
        menu.set_state(st.cfg)
        paint(menu)
        assert not st.cfg["frame_generation"]
        assert not [i for i in menu.items if i.extra.get("filled")
                    and i.key.startswith("frame_multiplier:")]
        assert save.call_count == 5
    # The prepared-capture flag rides the same header, independent of FG.
    worker = SimpleNamespace(stdin=io.BytesIO())
    protocol.send_frame(worker, 9, None, np.zeros((2, 2, 2), np.float16), False, 0,
                        no_color=True, split=.5, prepared=True,
                        frame_generation=True, frame_multiplier=4)
    flags = struct.unpack(protocol.FRAME_FMT, worker.stdin.getvalue()[:24])[3]
    assert flags & 0x1000 == 0x1000, "prepared rides the header"
    assert flags & 0x4000 == 0 and flags & 0x2000 == 0, "the removed SR flags stay unset"
    assert flags >> 16 == 32768
    assert ((flags >> 9) & 3) == 2
    # The resolution slider stays Boost-only: no SR to keep it company.
    menu.set_state({"nr_small": False, "work_scale": .8})
    paint(menu)
    assert find(menu, "slider", "nr_res") is None
    menu.set_state({"nr_small": True, "work_scale": .8})
    paint(menu)
    assert find(menu, "slider", "nr_res")
    # The real serializer must retain the FG settings.
    cfg = settings_io.load_config(ROOT / "config.json")
    cfg.update(frame_generation=True, frame_multiplier=4, ui_detection=True)
    params = settings_io.resolve_params(cfg)
    data = dict(cfg)
    data.update(settings_io._menu_layout_payload(cfg, params,
        cfg["monitor"] if isinstance(cfg["monitor"], int) else 0,
        cfg["lang"], cfg["work_scale"], 0.0, True, bool(cfg.get("nr_small")), menu))
    assert data["frame_generation"] and data["frame_multiplier"] == 4
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        restored = settings_io.load_config(path)
        assert restored["ui_detection"]
        assert restored["frame_generation"] and restored["frame_multiplier"] == 4
    pygame.quit()
    print("OK: FG controls, multiplier steps, persistence and wire flags")


def _fg_verdict_checks() -> None:
    """The switch follows reality (issue #76), pure unit level."""
    from types import SimpleNamespace

    # A refusal AFTER the enable marker -> off with the alert armed.
    alerts = []
    logs = ["[fg] UI: on, 2x", "[fg] Init_Ext -> 0xBAD00002",
            "[fg] CreateFeature failed 0xBAD00002"]
    st = SimpleNamespace(cfg={"frame_generation": True}, worker_logs=logs,
                         fg_alerted=False,
                         lang="en", display=SimpleNamespace(
                             alert=lambda *a, **k: alerts.append(a)))
    with patch.object(settings_io, "save_menu_layout"):
        settings_io.refresh_fg_ok(st)
    assert st.cfg["frame_generation"] is False, "the switch must flip back off"
    assert st.fg_alerted is True, "the alert must be armed once"
    assert len(alerts) == 1, f"exactly one alert, got {len(alerts)}"
    # The switch is off now: refresh is a no-op, nothing re-fires.
    settings_io.refresh_fg_ok(st)
    assert len(alerts) == 1, "the switch already off must not alert again"
    # Flipping it back on re-arms the alert (the user retries).
    st.cfg["frame_generation"] = True
    st.fg_alerted = False
    with patch.object(settings_io, "save_menu_layout"):
        settings_io.refresh_fg_ok(st)
    assert len(alerts) == 2, "a fresh attempt must be told again"

    # Success ("[fg] 2x enabled at ...") leaves the switch alone.
    logs_ok = ["[fg] UI: on, 2x", "[fg] 2x enabled at 3840x2160, format=28"]
    st2 = SimpleNamespace(cfg={"frame_generation": True}, worker_logs=logs_ok,
                          fg_alerted=False, lang="en",
                          display=SimpleNamespace(alert=lambda *a, **k: print("ALERT?")))
    settings_io.refresh_fg_ok(st2)
    assert st2.cfg["frame_generation"] is True, "a working FG must stay on"
    assert st2.fg_alerted is False

    # A stale refusal from BEFORE the last "UI: on" must not flip the switch.
    logs_stale = ["[fg] CreateFeature failed 0xBAD00002", "[fg] UI: off, 2x",
                  "[fg] UI: on, 2x"]
    st3 = SimpleNamespace(cfg={"frame_generation": True}, worker_logs=logs_stale,
                          fg_alerted=False, lang="en",
                          display=SimpleNamespace(alert=lambda *a, **k: None))
    settings_io.refresh_fg_ok(st3)
    assert st3.cfg["frame_generation"] is True, "a stale refusal must not flip it"
    print("    fg_verdict: refusal flips + alerts once; success and stale do not")


if __name__ == "__main__":
    main()
    _fg_verdict_checks()
