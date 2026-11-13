"""#7447/#7078 후속 — Chat copy of the pc_read image envelope projection.

The projection is the Chat gateway's own copy of the Engine driver's
conversion: one ``PADIEM_IMAGE_CONTENT`` envelope becomes a bounded note plus
one MCP image block. The wire limits are long edge 2000 px and a 300,000-byte
cap. When Pillow is unavailable the note says so and the caller receives no
picture at all once the original exceeds the byte cap — an unscaled oversized
original never ships (CTO decision 2026-11-13). A broken envelope (bad base64
or a disallowed mime) still passes through untouched.
"""
from __future__ import annotations

import base64
import io
import struct
import sys
import zlib

import pytest

from app.oracle_mesh_read_return_routes import (
    PC_IMAGE_BYTE_CAP,
    PC_IMAGE_ENVELOPE_PREFIX,
    _pc_image_projection,
)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _png_bytes(width: int, height: int, *, noise: bool = False) -> bytes:
    import random

    rnd = random.Random(20261113)
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


def _encoded_image(mime: str, raw: bytes) -> str:
    import PIL.Image

    if mime == "image/jpeg":
        buffer = io.BytesIO()
        PIL.Image.open(io.BytesIO(raw)).convert("RGB").save(buffer, format="JPEG")
        raw = buffer.getvalue()
    elif mime == "image/webp":
        buffer = io.BytesIO()
        PIL.Image.open(io.BytesIO(raw)).save(buffer, format="WEBP")
        raw = buffer.getvalue()
    elif mime == "image/gif":
        buffer = io.BytesIO()
        PIL.Image.open(io.BytesIO(raw)).save(buffer, format="GIF")
        raw = buffer.getvalue()
    return PC_IMAGE_ENVELOPE_PREFIX + mime + ":" + base64.b64encode(raw).decode("ascii")


def test_a_large_png_is_downscaled_into_one_block_within_both_caps():
    raw = _png_bytes(3000, 1500)
    note, block = _pc_image_projection(_encoded_image("image/png", raw))
    assert block is not None
    assert block["type"] == "image"
    assert block["mimeType"] in ("image/png", "image/jpeg")
    data = base64.b64decode(block["data"])
    if block["mimeType"] == "image/png":
        width, height = _png_dims(data)
        assert max(width, height) <= 2000
    assert len(data) <= PC_IMAGE_BYTE_CAP
    assert "긴 변 3000px를 2000px로 축소" in note


def test_a_small_png_keeps_the_original_dimensions():
    raw = _png_bytes(64, 32)
    note, block = _pc_image_projection(_encoded_image("image/png", raw))
    assert block is not None
    assert block["mimeType"] == "image/png"
    width, height = _png_dims(base64.b64decode(block["data"]))
    assert (width, height) == (64, 32)
    assert "축소" not in note


@pytest.mark.parametrize("mime", ["image/jpeg", "image/webp", "image/gif"])
def test_each_allowed_format_becomes_one_block(mime: str):
    raw = _png_bytes(80, 40)
    note, block = _pc_image_projection(_encoded_image(mime, raw))
    assert block is not None
    assert block["type"] == "image"
    assert block["mimeType"] in ("image/png", "image/jpeg")
    assert len(base64.b64decode(block["data"])) <= PC_IMAGE_BYTE_CAP
    assert "이미지 파일을 읽었습니다" in note


def test_without_pil_an_oversized_original_sends_text_only(monkeypatch):
    # CTO decision 2026-11-13: without Pillow there is no way to meet the
    # byte cap, so an oversized original ships as bounded text only. This is
    # the before/after test: before the fix the oversized original travelled
    # unscaled as an image block.
    monkeypatch.setitem(sys.modules, "PIL", None)
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * (PC_IMAGE_BYTE_CAP + 50_000)
    note, block = _pc_image_projection(
        PC_IMAGE_ENVELOPE_PREFIX + "image/png:" + base64.b64encode(raw).decode("ascii"))
    assert block is None
    assert "이미지 축소를 쓸 수 없어 그림을 보내지 못했습니다" in note
    assert f"{len(raw):,}바이트" in note


def test_without_pil_an_original_within_the_cap_still_ships(monkeypatch):
    monkeypatch.setitem(sys.modules, "PIL", None)
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 5_783
    note, block = _pc_image_projection(
        PC_IMAGE_ENVELOPE_PREFIX + "image/png:" + base64.b64encode(raw).decode("ascii"))
    assert block is not None
    assert block["mimeType"] == "image/png"
    assert base64.b64decode(block["data"]) == raw
    assert "(축소 없이 원본 그대로)" in note


def test_a_broken_envelope_returns_untouched():
    broken = PC_IMAGE_ENVELOPE_PREFIX + "image/png:" + "!!!not base64!!!"
    note, block = _pc_image_projection(broken)
    assert (note, block) == (broken, None)


def test_a_disallowed_mime_returns_untouched():
    envelope = PC_IMAGE_ENVELOPE_PREFIX + "image/bmp:" + base64.b64encode(b"bmp").decode()
    note, block = _pc_image_projection(envelope)
    assert (note, block) == (envelope, None)
