"""The HDR frame format: float16 colour through the shared-memory slot.

When the desktop is HDR the colour frame is scRGB linear light - the format
the neural consumer expects. RGBA8 cannot carry it: anything above SDR white
is clipped before the network ever sees it. The SHM slot therefore carries
float16 (8 bytes per pixel, same HxW), signalled by SHM_FLAG_F16 at
negotiation - the layout change is decided once, at SHMI time, not per frame.

Checked:
* put_f16() stores an (H, W, 4) float16 frame into the same mapping, at the
  same colour offset, without exceeding the capacity it was negotiated with
  (the capacity is computed for 8 B/px when hdr is agreed);
* a frame put through put_f16() reads back byte-identical through the
  worker-side view of the mapping;
* the RGBA8 path (put) is untouched - same bytes in, same bytes out (SDR
  stays bit-identical, the acceptance bar of the whole HDR phase).
"""
import sys
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from protocol import SharedFrameBuffer, SHM_FLAG_F16, WORK_MAX_W, WORK_MAX_H  # noqa: E402


def main() -> int:
    failures = []
    W, H = 320, 180

    # An HDR-negotiated buffer: the colour capacity must cover 8 B/px.
    shm = SharedFrameBuffer(W, H, max_work_w=WORK_MAX_W, max_work_h=WORK_MAX_H,
                            hdr=True)
    if shm.color_capacity != W * H * 8:
        failures.append(f"HDR colour capacity {shm.color_capacity} != {W * H * 8}")
    try:
        # 1. put_f16 stores a float16 frame byte-identically.
        frame = np.random.default_rng(42).standard_normal(
            (H, W, 4)).astype(np.float16)
        shm.put_f16(frame, np.zeros((H // 2, W // 2, 2), np.float16))
        back = np.frombuffer(
            shm._buf[:shm.color_capacity], dtype=np.uint8
        )[:frame.nbytes].reshape(H, W, 8).view(np.float16)
        if not np.array_equal(back, frame):
            failures.append("put_f16 did not store the frame byte-identically")

        # 2. A float16 frame that exceeds a buffer negotiated for RGBA8
        #    is refused, not silently truncated: a capacity mismatch is a
        #    protocol desync, not a degraded picture.
        sdr_shm = SharedFrameBuffer(W, H)
        try:
            sdr_shm.put_f16(frame, np.zeros((H // 2, W // 2, 2), np.float16))
            failures.append("put_f16 accepted into an RGBA8-sized buffer")
        except ValueError:
            pass  # the refusal is the contract

        # 3. The SDR path is untouched: put() of the same pixels, same bytes.
        rgba = np.arange(H * W * 4, dtype=np.uint8).reshape(H, W, 4)
        shm2 = SharedFrameBuffer(W, H)
        shm2.put(rgba, np.zeros((H // 2, W // 2, 2), np.float16))
        back2 = np.frombuffer(
            shm2._buf[:shm2.color_capacity], dtype=np.uint8
        )[:rgba.nbytes].reshape(H, W, 4)
        if not np.array_equal(back2, rgba):
            failures.append("the SDR put path changed")

        # 4. The flag exists and is a distinct bit (protocol stability).
        if not isinstance(SHM_FLAG_F16, int) or SHM_FLAG_F16 & 0x1:
            failures.append("SHM_FLAG_F16 must be a new bit, not 0x1 (SHM)")
    finally:
        shm.close()
    print("=" * 60)
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("OK: float16 frames ride the SHM slot, SDR bytes unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
