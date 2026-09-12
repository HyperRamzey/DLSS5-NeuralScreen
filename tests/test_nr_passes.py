"""N-pass NR: the cascade contract (Phase C1).

The Feeder runs up to three NR evaluates per frame, each stage keeping
its OWN history (own feature handle) - a two-pass cascade roughly
doubles the effective history length. The plan gates it with
NS_NR_PASSES (1-3) and a `nr_passes` config key; the single-pass
default must stay bit-identical.

Client-side contract (checked here without a GPU):
* `nr_passes` rides the CONFIG, not a new wire field - the knob is
  read once per worker process (the feature set is created at stream
  start), the same contract as nr_small: resolve_params/load_config
  accept it, the value is clamped to 1..3, and the env it produces
  (NS_NR_PASSES) is set before the first launch;
* the default is 1 - a config without the key keeps today's pipeline
  exactly (no extra features, no extra textures);
* an out-of-range value clamps instead of refusing (0 -> 1, 9 -> 3).

Host-side (verified by the worker's own log in the live run, pinned in
the docstring, not here): NS_NR_PASSES=2 creates two feature 18
handles, evaluates sequentially feeding pass k's Output into pass k+1's
Color, resets both on the same frame, and fences once after the last
pass. The log says '[video] NR passes 2'.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # the project root
sys.path.insert(0, str(BASE))                  # the project modules
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ (autocheck)

import settings_io  # noqa: E402
import startup  # noqa: E402


def _write_cfg(td: str, **extra) -> Path:
    cfg = {
        "monitor": 0, "width": 1920, "height": 1080, "fullscreen": True,
        "warmup": 30, "work_scale": 1.0, "lang": "en", "profile": "Natural",
        "intensity": None, "local_tone": None,
        "local_structure": None, "skin_structure": None,
    }
    cfg.update(extra)
    p = Path(td) / "config.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def main() -> int:
    failures = []
    saved = {k: os.environ.get(k) for k in ("NS_NR_PASSES", "NS_NR_SMALL")}

    # 1. The config accepts nr_passes; the env applier clamps 1..3.
    try:
        with tempfile.TemporaryDirectory() as td:
            # default (absent) -> 1, and no behavior change
            cfg = settings_io.load_config(_write_cfg(td))
            startup._apply_passes_env(cfg)
            got = os.environ.get("NS_NR_PASSES")
            if got != "1":
                failures.append(f"default nr_passes: NS_NR_PASSES={got!r}, "
                                "want '1' (the single-pass pipeline)")

            # explicit 2 -> 2
            cfg = settings_io.load_config(_write_cfg(td, nr_passes=2))
            startup._apply_passes_env(cfg)
            if os.environ.get("NS_NR_PASSES") != "2":
                failures.append("nr_passes=2: NS_NR_PASSES is not '2'")

            # clamp down: 0 -> 1 (a wrong value must not refuse to run)
            cfg = settings_io.load_config(_write_cfg(td, nr_passes=0))
            startup._apply_passes_env(cfg)
            if os.environ.get("NS_NR_PASSES") != "1":
                failures.append("nr_passes=0: must clamp to 1")

            # clamp up: 9 -> 3
            cfg = settings_io.load_config(_write_cfg(td, nr_passes=9))
            startup._apply_passes_env(cfg)
            if os.environ.get("NS_NR_PASSES") != "3":
                failures.append("nr_passes=9: must clamp to 3")

            # a non-number (hand-edited config) falls back to 1
            cfg = settings_io.load_config(_write_cfg(td, nr_passes="two"))
            startup._apply_passes_env(cfg)
            if os.environ.get("NS_NR_PASSES") != "1":
                failures.append("nr_passes='two': must fall back to 1")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    print("=" * 60)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("OK: nr_passes rides the config (default 1, clamped 1..3)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
