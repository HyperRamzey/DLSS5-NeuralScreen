"""Direct-worker tests consume v1.13 CACK without corrupting the next reply."""
from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from worker_reply import CREATE_ACK_FMT, read_exact, read_reply


WACK_MAGIC = 0x4B434157
WACK_FMT = "<4Iq"


def main() -> int:
    failures: list[str] = []
    cack = struct.pack(CREATE_ACK_FMT, 0x4B434143, 1, 0, 0, 17)
    wack = struct.pack(WACK_FMT, WACK_MAGIC, 1, 0, 0, 18)
    seen: list[tuple[int, int, int]] = []

    if read_reply(io.BytesIO(wack), len(wack)) != wack:
        failures.append("an ordinary reply changed")
    if read_reply(io.BytesIO(cack + wack), len(wack),
                  on_create_ack=seen.append) != wack:
        failures.append("CACK was not removed before WACK")
    if seen != [(1, 0, 0)]:
        failures.append(f"wrong CACK payload: {seen!r}")

    failed = struct.pack(CREATE_ACK_FMT, 0x4B434143, 0, 0xBAD00001, 1, 19)
    try:
        read_reply(io.BytesIO(failed + wack), len(wack))
        failures.append("failed CACK was hidden")
    except RuntimeError as exc:
        if "0xBAD00001" not in str(exc):
            failures.append(f"failed CACK lost its result: {exc}")

    try:
        read_exact(io.BytesIO(b"ab"), 3)
        failures.append("short reply was accepted")
    except EOFError:
        pass

    if failures:
        print(f"FAIL: {len(failures)} - {failures}")
        return 1
    print("OK: direct-worker replies consume CACK exactly once and fail closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
