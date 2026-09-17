"""Compile and run the production scaling/sharpening shader regression on WARP.

The shader arithmetic is what decides whether the picture is right, so it is
checked by compiling the production shader source and reading pixels back on the
WARP software device - no GPU, no NVIDIA runtime and no HDR display. The suite
already insists on a freshly built worker, so the machine running it has the
compiler.

This used to run only with `--run`, and the runner passes no flags, so in
practice it printed SKIP on every suite run. A check nobody runs is a check
nobody has: the sibling test_hdr_shaders.py does the same kind of work and has
always run without a flag; this now matches it.

Run:  runtime\\python.exe tests\\test_quality_gpu.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAT = ROOT / "native" / "test-quality.bat"


def main() -> int:
    if not BAT.is_file():
        print(f"FAIL: no {BAT}")
        return 1
    try:
        result = subprocess.run(
            ["cmd", "/c", str(BAT)], cwd=str(BAT.parent),
            capture_output=True, text=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        print("FAIL: the WARP quality-shader run did not finish in 600s")
        return 1
    out = (result.stdout or "") + (result.stderr or "")
    for line in out.splitlines():
        if line.strip():
            print(f"    {line.rstrip()}")
    if result.returncode != 0:
        print(f"FAIL: the quality shader run exited {result.returncode}")
        return 1
    if "PASS" not in out:
        print("FAIL: the quality shader run printed no PASS line")
        return 1
    print("OK: the production quality shaders compile and hold their contract "
          "on WARP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
