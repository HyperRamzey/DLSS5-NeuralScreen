r"""The surround of a window-sized frame is painted, every frame.

In one-window mode the layer is the whole screen while the frame is the
size of the captured window, and show() blits the frame where the window
is. The swap chain is flip-discard: what was on screen last time is not
in the back buffer, so anything show() does not paint is undefined - in
practice the frame from two flips ago. Left alone it reads as a still
photograph of the desktop pinned over the real one, and nothing in it
reacts (user, 13.09).

The surround has to be the key colour, which the layer already cuts out:
in one-window mode the capture is always WGC inside the worker, so the
key is on. Two earlier attempts set a second key from the draw path and
that was the blinking - so this test also pins down that show() does not
touch the layered attributes.

Expected: after a small frame is shown on a big layer, every pixel
outside the frame is CHROMA_KEY, the frame's own pixels survive, and
SetLayeredWindowAttributes was not called.
[#60 window mode]

Run:  runtime\python.exe tests\test_window_surround.py
"""
import os
import sys
from pathlib import Path


def _repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "main.py").is_file():
            return p
    return start


BASE = _repo_root(Path(__file__).resolve().parent)
sys.path.insert(0, str(BASE))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np  # noqa: E402
import pygame  # noqa: E402


def main() -> int:
    failures = []
    pygame.init()
    disp = None
    try:
        import display as display_mod

        key = display_mod.CHROMA_KEY
        disp = display_mod.Display(1920, 1080, click_through=False)

        # Dirty the layer the way a previous frame would have: this is the
        # stale picture the user was looking at.
        disp.screen.fill((11, 22, 33))

        # A captured window at (400, 200), 640x360, on the primary monitor.
        disp._frame_size = (640, 360)
        disp.set_window_layer(400, 200, 640, 360)

        calls = []
        real_set = display_mod.user32.SetLayeredWindowAttributes

        def spy_set(*a, **k):
            calls.append(a)
            return real_set(*a, **k)

        display_mod.user32.SetLayeredWindowAttributes = spy_set
        try:
            frame = np.empty((360, 640, 4), dtype=np.uint8)
            frame[:, :, 0] = 200
            frame[:, :, 1] = 100
            frame[:, :, 2] = 50
            frame[:, :, 3] = 255
            disp.show(frame)
        finally:
            display_mod.user32.SetLayeredWindowAttributes = real_set

        # Four probes around the frame, one per rectangle the fill covers.
        for name, pos in (("above", (960, 100)),
                          ("below", (960, 900)),
                          ("left", (100, 380)),
                          ("right", (1500, 380))):
            got = tuple(disp.screen.get_at(pos))[:3]
            if got != key:
                failures.append(
                    f"{name} of the frame is {got}, want the key {key} - the "
                    f"surround was left as whatever the last flip held")

        got = tuple(disp.screen.get_at((700, 380)))[:3]
        if got != (200, 100, 50):
            failures.append(
                f"the frame itself is {got}, want (200, 100, 50) - the fill "
                f"ate the picture")

        if calls:
            failures.append(
                f"show() wrote the layered attributes {len(calls)} time(s) - "
                f"that is what blinked twice a second (d10cfd4, e46a24b); "
                f"the key belongs to set_hud_only alone")
    finally:
        try:
            if disp is not None:
                disp.close()
        except Exception:
            pass
        pygame.quit()

    for f in failures:
        print("FAIL:", f)
    if failures:
        return 1
    print("OK: the surround of a window-sized frame is keyed out, and show() "
          "leaves the layer attributes alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
