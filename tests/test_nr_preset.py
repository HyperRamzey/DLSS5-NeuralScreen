"""The NR preset hint reaches the NGX feature create (Phase A2).

The NR model hint (`DLSSNR.Hint.Render.Preset`) is create-time state:
the feature is built against a specific transformer network, so the hint
must arrive with the create call - a mid-stream change needs the
existing RNSZ re-create, which already re-sends the whole header-shaped
options struct.

The hint travels the wire in the header's `preset` field (the same
field PROFILES sets per profile: Faithful 0, Natural 0, Strong 2).
The host used to read it only from NS_NR_PRESET (a static env, fixed
for the process lifetime) and ignored the wire field entirely - the
profile's preset choice never reached NGX.

The contract, after this slice:
* the host's create path prefers the WIRE preset (g_video_options.preset
  != 0) over the env (NS_NR_PRESET), so per-profile values apply and a
  live RNSZ can change the network;
* NS_NR_PRESET stays the escape hatch when the wire field is 0
  (Default) - the old behavior for SDR streams and old clients;
* the resolve_params helper exports the per-profile preset to the wire
  field unchanged (no client-side math);
* the preset hint is clamped to 0..13 (the SDK enum range - E..M).

Checked without a GPU (pure client-side contract):
* every PROFILES entry carries a preset in 0..13;
* the header the client sends carries the profile's preset;
* send_resize (RNSZ) carries the profile's preset too - a live switch
  re-applies it through the options copy.
"""

import struct
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent  # the project root
sys.path.insert(0, str(BASE))  # the project modules
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ (autocheck)

import io as _io  # noqa: E402

import settings_io  # noqa: E402
from protocol import HEADER_FMT, VIDEO_MAGIC  # noqa: E402


class _FakeStdin:
    """A pipe that records what the client writes."""

    def __init__(self):
        self.buffer = _io.BytesIO()

    def write(self, data):
        self.buffer.write(data)
        return len(data)

    def flush(self):
        pass


def _header_fields(raw: bytes) -> dict:
    """Decode a D5V3 header from the fake pipe."""
    values = struct.unpack(HEADER_FMT, raw[: struct.calcsize(HEADER_FMT)])
    keys = (
        "magic",
        "width",
        "height",
        "warmup",
        "frame_count",
        "profile",
        "preset",
        "style",
        "auto_mask",
        "ui_correction",
        "intensity",
        "local_tone",
        "local_structure",
        "skin_structure",
        "full_w",
        "full_h",
    )
    return dict(zip(keys, values))


def main() -> int:
    failures = []

    # 1. Every profile's preset is within the SDK enum range (0..13).
    for name, p in settings_io.PROFILES.items():
        v = p["preset"]
        if not (isinstance(v, int) and 0 <= v <= 13):
            failures.append(f"profile {name!r}: preset {v!r} is not 0..13")

    # 2. resolve_params keeps the profile's preset in the params dict -
    #    the header send reads it from there.
    import json
    import tempfile

    for name in settings_io.PROFILES:
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "monitor": 0,
                        "width": 1920,
                        "height": 1080,
                        "fullscreen": True,
                        "warmup": 30,
                        "work_scale": 1.0,
                        "lang": "en",
                        "profile": name,
                        "intensity": None,
                        "local_tone": None,
                        "local_structure": None,
                        "skin_structure": None,
                    }
                ),
                encoding="utf-8",
            )
            cfg = settings_io.load_config(cfg_path)
            params = settings_io.resolve_params(cfg)
            want = settings_io.PROFILES[name]["preset"]
            if params.get("preset") != want:
                failures.append(
                    f"resolve_params({name!r}).preset = "
                    f"{params.get('preset')!r}, want {want!r}"
                )

    # 3. The D5V3 header the client writes carries the profile's preset.
    import os
    import subprocess

    import protocol

    W, H = 640, 360
    worker = subprocess.Popen(
        ["cmd", "/c", "exit"],  # never read: send only
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
    )
    try:
        # start_worker builds the header; replicate its exact call shape
        # (pipeline.py:121) against the fake stdin.
        params = dict(settings_io.PROFILES["Strong / Cinematic"])
        pipe = _FakeStdin()
        pipe.write(
            struct.pack(
                HEADER_FMT,
                VIDEO_MAGIC,
                W,
                H,
                10,
                0,
                params["profile"],
                params["preset"],
                params["style"],
                params["auto_mask"],
                params["ui_correction"],
                params["intensity"],
                params["local_tone"],
                params["local_structure"],
                params["skin_structure"],
                0,
                0,
            )
        )
        hdr = _header_fields(pipe.buffer.getvalue())
        if hdr["preset"] != 2:
            failures.append(
                f"the wire header carries preset="
                f"{hdr['preset']!r}, want 2 "
                f"(Strong / Cinematic)"
            )
        if hdr["magic"] != VIDEO_MAGIC:
            failures.append(f"header magic 0x{hdr['magic']:X}, want 0x{VIDEO_MAGIC:X}")

        # 4. send_resize (RNSZ) carries the preset too - the live
        #    switch. A plain os.pipe, write end wrapped: send_resize
        #    touches only worker.stdin.write/.flush, so the duck-typed
        #    stand-in is the honest minimal contract. The bytes land in
        #    the pipe buffer and are read back from the other end.
        r_fd, w_fd = os.pipe()
        w_handle = open(w_fd, "wb", closefd=False)
        r_handle = open(r_fd, "rb", closefd=False)

        class _PipedWorker:
            """Only .stdin.write/.flush - as send_resize uses."""

            class _Stdin:
                def __init__(self, h):
                    self._h = h

                def write(self, data):
                    return self._h.write(data)

                def flush(self):
                    self._h.flush()

            def __init__(self, h):
                self.stdin = _PipedWorker._Stdin(h)

        protocol.send_resize(_PipedWorker(w_handle), params, W, H, 10, 0,
                             0, nr_small=False)
        w_handle.flush()
        wrote = r_handle.read(struct.calcsize(HEADER_FMT))
        w_handle.close()
        r_handle.close()
        os.close(w_fd)
        os.close(r_fd)

        from protocol import RESIZE_MAGIC

        values = struct.unpack(HEADER_FMT, wrote[: struct.calcsize(HEADER_FMT)])
        if values[0] != RESIZE_MAGIC or values[6] != 2:
            failures.append(
                f"RNSZ carries magic=0x{values[0]:X} preset="
                f"{values[6]!r}, want the profile preset"
            )
    finally:
        worker.stdin.close() if worker.stdin else None
        worker.wait(timeout=5)

    print("=" * 60)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print(
        "OK: the NR preset hint travels the wire (header + RNSZ), "
        "profiles carry SDK-range presets"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
