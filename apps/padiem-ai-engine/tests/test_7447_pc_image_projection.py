"""#7447: the engine turns one image envelope into a note + one MCP image block.

The PC agent frames an image read as ``PADIEM_IMAGE_CONTENT=<mime>:<base64>``.
The projection parses it, downscales toward the wire limits (long edge 2000,
byte cap 300 KB) reusing the bounded ai-core image helpers, and says so in the
note; anything that is not the envelope returns untouched so an ordinary text
read keeps its exact shape. The retired stealth marker ``binary_not_supported``
keeps its own refusal hint.

The fixtures build real PNG bytes with zlib+struct so the suite needs no
imaging dependency of its own; the delivered dimensions are read back from the
IHDR header.
"""
from __future__ import annotations

import base64
import io
import struct
import zlib

import pytest

from app.claw_pc_query_step_driver import (
    PC_IMAGE_ENVELOPE_PREFIX,
    _pc_image_projection,
    _pc_read_marker,
    _pc_refusal_hint,
)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _png_bytes(width: int, height: int, *, noise: bool = False) -> bytes:
    import random

    rnd = random.Random(20261111)
    rows = []
    for _ in range(height):
        row = bytearray(b"\x00")
        for _ in range(width):
            if noise:
                row += bytes((rnd.randrange(256), rnd.randrange(256),
                              rnd.randrange(256)))
            else:
                row += b"\x1f\x2f\x3f"
        rows.append(bytes(row))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows))) + _chunk(b"IEND", b""))


def _png_dims(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _envelope(mime: str, raw: bytes) -> str:
    return PC_IMAGE_ENVELOPE_PREFIX + mime + ":" + base64.b64encode(raw).decode("ascii")


def test_a_small_envelope_becomes_a_note_and_one_image_block():
    pytest.importorskip('PIL.Image')
    raw = _png_bytes(64, 32)
    note, block = _pc_image_projection(_envelope("image/png", raw))
    assert block is not None
    assert block["type"] == "image"
    assert block["mimeType"] == "image/png"
    assert "64x32" in note
    assert "축소" not in note


def test_a_large_image_is_downscaled_to_the_long_edge_cap():
    pytest.importorskip('PIL.Image')
    raw = _png_bytes(2200, 1100)
    note, block = _pc_image_projection(_envelope("image/png", raw))
    assert block is not None
    width, height = _png_dims(base64.b64decode(block["data"]))
    assert max(width, height) <= 2000
    assert "축소" in note


def test_an_oversize_image_is_reframed_as_jpeg_under_the_byte_cap():
    pytest.importorskip('PIL.Image')
    raw = _png_bytes(1600, 900, noise=True)
    assert len(raw) > 300_000
    note, block = _pc_image_projection(_envelope("image/png", raw))
    assert block is not None
    assert block["mimeType"] == "image/jpeg"
    assert len(base64.b64decode(block["data"])) <= 300_000
    assert "JPEG" in note


def test_a_broken_envelope_returns_untouched():
    broken = PC_IMAGE_ENVELOPE_PREFIX + "image/png:" + "!!!not base64!!!"
    note, block = _pc_image_projection(broken)
    assert (note, block) == (broken, None)


def test_a_plain_text_output_returns_untouched():
    note, block = _pc_image_projection("그냥 텍스트 파일 내용")
    assert (note, block) == ("그냥 텍스트 파일 내용", None)


def test_the_binary_refusal_marker_keeps_its_own_hint():
    assert _pc_read_marker("PADIEM_PC_FILE_ERROR:binary_not_supported") == (
        "binary_not_supported")
    hint = _pc_refusal_hint("pc_file_binary_not_supported")
    assert "이진 파일" in hint
