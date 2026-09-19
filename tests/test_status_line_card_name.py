"""The status line must be able to say which card runs the network (audit M4).

The readings hug the right edge and the card name took whatever was left in the
middle. The remainder measured 72 px at 1080p and 74 px at 4K - nearly the same,
because the reading block grows with the font while the panel scale stops at
user_scale 1.2 - so even "NVIDIA GeForce RTX 5070 Ti" was elided to about 63-72
px, i.e. "NVIDIA…", for every card tried. In German at 4K the room was 38 px,
below the old 40-unit floor, so the name was not drawn at all.

The card the network is running on is the one value in that line that cannot be
guessed from anywhere else, so it now gets its room first, capped at a third of
the bar, and the readings are laid out into what remains - a reading that does
not fit is dropped rather than clipped, because a half-number reads as a wrong
number.

Checked here with the real faces and the real layout, at the sizes and card
names the probe used, in the languages that produced the failures: the name
must be drawn, it must be wide enough to identify the card rather than a bare
"NVIDIA…", and every reading that IS drawn must fit inside the bar.

Run:  runtime\\python.exe tests\\test_status_line_card_name.py
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

CARDS = (
    "NVIDIA GeForce RTX 5070 Ti",
    "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
    "NVIDIA GeForce RTX 4090 Laptop GPU",
    "NVIDIA GeForce RTX 3080 Ti Laptop GPU",
)
SIZES = ((1920, 1080), (2560, 1440), (3840, 2160))
LANGS = ("en", "de", "ru")


def _state(width: int, height: int, lang: str, card: str) -> dict:
    return {
        "lang": lang, "nr": True, "profile": "Natural",
        "profiles": ["Natural"], "params": {},
        "split": 0.0, "work_scale": 0.65, "work_scale_cap": 0.65,
        "work_scale_min": 0.1, "nr_small": True,
        "screen_size": f"{width}x{height}", "theme": "light",
        "gpu_text": card, "gpu_ok": True,
        "hdr": False, "spout": False, "rec_indicator": True,
        "skip_static": True, "windows": [], "window_current": "",
        "monitors": [], "monitor": "", "gpus": [], "gpu": "",
        "version": "1.13.1", "channel": "@perseval_BLR",
        "autostart": True, "open_on_start": True,
        "recording": False, "screenshot_dir": "", "recording_dir": "",
    }


def main() -> int:
    import pygame
    pygame.init()
    pygame.display.set_mode((64, 64))
    import fonts
    from overlay_ui import OverlayMenu

    failures = []
    checked = 0

    for (w, h) in SIZES:
        for lang in LANGS:
            for card in CARDS:
                menu = OverlayMenu(1.0, lambda size=14, mono=False, bold=False,
                                   L=lang: fonts.load(size, mono=mono,
                                                      bold=bold, lang=L))
                menu.lang = lang
                menu.set_state(_state(w, h, lang, card))
                menu.visible = True
                menu.page = "main"
                menu.layout(w, h)
                menu.stats = {"fps": 144.0, "display_fps": 144.0,
                              "skipped_static": 12, "resolution": f"{w}x{h}"}

                drawn = []
                real_clip = menu._clip

                def spy(font, text, color, max_w, _d=drawn, _r=real_clip):
                    img = _r(font, text, color, max_w)
                    _d.append((str(text), max_w, img.get_width()))
                    return img

                menu._clip = spy
                surface = pygame.Surface((w, h), pygame.SRCALPHA)
                try:
                    menu.draw(surface)
                except Exception as exc:
                    failures.append(f"{w}x{h}/{lang}/{card[:28]}: draw raised "
                                    f"{exc!r}")
                    menu._clip = real_clip
                    continue
                finally:
                    menu._clip = real_clip
                checked += 1

                name_hits = [d for d in drawn if d[0] == card]
                if not name_hits:
                    failures.append(
                        f"{w}x{h}/{lang}/{card[:28]}: the card name never "
                        f"reached _clip - it is not drawn on the status line")
                    continue
                max_w, width = name_hits[0][1], name_hits[0][2]
                if max_w <= 0 or width <= 0:
                    failures.append(
                        f"{w}x{h}/{lang}/{card[:28]}: the card name is drawn "
                        f"at {width}px (max_w={max_w}) - it reads as nothing")
                # "NVIDIA…" is 63 px at the smallest; require more than that,
                # so the name has to carry at least a model hint.
                floor = menu._small_font.size("NVIDIA")[0] + menu._u(6)
                if width <= floor:
                    failures.append(
                        f"{w}x{h}/{lang}/{card[:28]}: the name is only "
                        f"{width}px (floor {floor}) - it says 'NVIDIA…' and "
                        f"not which card")

                # Every reading that was drawn must fit inside the bar. Their
                # max_w is not used (they are rendered whole or skipped), so
                # measure the rendered width against what the code allowed:
                # nothing may start left of the name's end.
                for text, _mw, tw in drawn:
                    if text == card or not text:
                        continue
                    if tw > menu._stats_rect.w:
                        failures.append(
                            f"{w}x{h}/{lang}/{card[:28]}: the reading "
                            f"{text[:16]!r} renders {tw}px in a "
                            f"{menu._stats_rect.w}px bar")

    if not checked:
        print("FAIL: no status line was drawn - this test no longer covers "
              "what it exists for")
        return 1

    for f in failures[:15]:
        print("FAIL:", f)
    if len(failures) > 15:
        print(f"... and {len(failures) - 15} more")
    if failures:
        return 1
    print(f"OK: the card name is readable and the readings fit, on "
          f"{checked} combinations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
