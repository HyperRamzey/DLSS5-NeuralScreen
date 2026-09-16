"""Raw-worker reply helpers shared by direct native protocol tests.

The v1.13 worker emits one asynchronous CACK immediately after the D5V3 video
header.  Production's ``VideoWorker`` routes it on its reader queue, while the
small direct-worker tests read stdout themselves.  Those tests must consume the
24-byte CACK before interpreting the reply to their first command or frame.
"""
from __future__ import annotations

import struct
from typing import BinaryIO, Callable


CREATE_ACK_MAGIC = 0x4B434143  # CACK
CREATE_ACK_FMT = "<4Iq"
CREATE_ACK_SIZE = struct.calcsize(CREATE_ACK_FMT)


def read_exact(stream: BinaryIO, size: int) -> bytes:
    """Read exactly ``size`` bytes or raise EOFError with a useful count."""
    chunks: list[bytes] = []
    received = 0
    while received < size:
        chunk = stream.read(size - received)
        if not chunk:
            raise EOFError(f"worker stdout ended after {received}/{size} bytes")
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)


def read_reply(
    stream: BinaryIO,
    size: int,
    *,
    on_create_ack: Callable[[tuple[int, int, int]], None] | None = None,
) -> bytes:
    """Read one fixed-size reply, consuming any preceding successful CACK.

    A failed CreateFeature is never hidden: direct GPU tests require a usable
    feature, so the helper raises with the explicit NGX result/category instead
    of letting a later command timeout or misparse four leftover CACK bytes.
    """
    if size < 4:
        raise ValueError(f"reply size must include a 4-byte magic, got {size}")
    magic_raw = read_exact(stream, 4)
    while struct.unpack("<I", magic_raw)[0] == CREATE_ACK_MAGIC:
        rest = read_exact(stream, CREATE_ACK_SIZE - 4)
        _magic, ok, ngx_result, category, _pts = struct.unpack(
            CREATE_ACK_FMT, magic_raw + rest)
        verdict = int(ok), int(ngx_result), int(category)
        if on_create_ack is not None:
            on_create_ack(verdict)
        if not ok:
            raise RuntimeError(
                "worker CreateFeature failed: "
                f"ngx=0x{ngx_result:08X}, category={category}"
            )
        magic_raw = read_exact(stream, 4)
    return magic_raw + read_exact(stream, size - 4)
