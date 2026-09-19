"""The Spout2 runtime the product ships is present, tracked and linkable.

The old version of this test looked for `SpoutLibrary.dll` inside a Spout SDK
checkout under `_work/` - a path that is git-ignored and that nothing in the
repository creates or downloads. The file was never there, so the test printed
SKIP on every run while its docstring claimed to prove the Spout2 path is
viable on this machine.

What the product really uses is `SpoutDX`: the worker links `SpoutDX.lib` and
includes `spout/SpoutDX.h`, then ships `native/SpoutDX.dll` (and
`native/Spout.dll`, which SpoutDX loads) inside the release archive. That is a
link-time contract, not a run-time GetProcAddress one, so the check is about the
shipped files being present, tracked and usable - not about resolving flat
exports, which this DLL does not have.

Run:  runtime\\python.exe tests\\test_spout_library.py
"""
import ctypes
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
NATIVE = BASE / "native"
SHIPPED = {
    "SpoutDX.dll": "the sender the worker talks to",
    "Spout.dll": "loaded by SpoutDX at run time",
}
LIB = NATIVE / "SpoutDX.lib"
HEADER = NATIVE / "include" / "spout" / "SpoutDX.h"


def tracked(path: Path) -> bool:
    rel = path.relative_to(BASE).as_posix()
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel], cwd=BASE,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode == 0


def main() -> int:
    failures: list[str] = []

    for name, why in SHIPPED.items():
        path = NATIVE / name
        if not path.is_file():
            failures.append(f"{name} is missing ({why})")
            continue
        if not tracked(path):
            failures.append(f"{name} is not tracked by git - it cannot ship")
            continue
        try:
            ctypes.WinDLL(str(path))
        except OSError as exc:
            failures.append(f"{name} does not load: {exc}")
        else:
            print(f"  {name}: present, tracked, loads ({path.stat().st_size} bytes)")

    if not LIB.is_file():
        failures.append("SpoutDX.lib is missing - the worker cannot link")
    elif not tracked(LIB):
        failures.append("SpoutDX.lib is not tracked by git")
    else:
        print(f"  SpoutDX.lib: present and tracked ({LIB.stat().st_size} bytes)")

    if not HEADER.is_file():
        failures.append("spout/SpoutDX.h is missing - the worker cannot compile")
    else:
        print(f"  SpoutDX.h: present")

    if failures:
        print(f"FAIL: {len(failures)}")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("OK: the Spout2 runtime, its import library and its header all ship")
    return 0


if __name__ == "__main__":
    sys.exit(main())
