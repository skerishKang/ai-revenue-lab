"""#7447/#7078 후속 — the Engine driver must not drop the projected image block.

The Chat result leg projects the stored image envelope before the Engine
reads it: the response carries the bounded note as ``output`` plus the image
block as ``_pc_image``. The driver's re-wrap used to rebuild its outcome from
``output`` alone, silently discarding that block, so the MCP caller received
the note and never the picture (CTO decision 2026-11-13 queue incident).

Both return shapes are pinned here: the stored-output reference branch and
the plain result branch forward the block the Chat leg already produced.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    PC_READ_FILE_TOOL_ID,
    _make_pc_file_handler,
)
from test_7447_pc_image_projection import _png_bytes


RUN_ID = "run_7447_delivery"
SUBJECT = "sub_" + "7" * 32
PRODUCT = "padiem-chat"
DEVICE = "pc-com2"
DISPATCH_ID = "dsp_" + "b" * 32

BLOCK = {"type": "image", "mimeType": "image/png",
         "data": __import__("base64").b64encode(_png_bytes(64, 32)).decode("ascii")}


@pytest.fixture(autouse=True)
def _owner_run():
    token = driver._PC_QUERY_OWNER.set((SUBJECT, RUN_ID, PRODUCT, DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)


async def _no_sleep(_seconds: float) -> None:
    return None


def _install(monkeypatch, *, final: dict) -> list[str]:
    modes: list[str] = []

    async def fake_call(**kwargs):
        mode = kwargs["mode"]
        modes.append(mode)
        if mode == "dispatch":
            return {"dispatch": {"run_id": RUN_ID, "kind": "read",
                                 "dispatch_id": DISPATCH_ID}}
        if mode == "command_status":
            return {"dispatch": {"dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                                 "kind": "read", "state": "done",
                                 "termination": "exited", "exit_code": 0}}
        if mode == "result":
            return {"dispatch": final}
        raise AssertionError("unexpected mode " + str(mode))

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    return modes


def _handler():
    return _make_pc_file_handler(
        tool_id=PC_READ_FILE_TOOL_ID, op="read", service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
    )


def test_stored_output_branch_forwards_the_projected_image_block(monkeypatch):
    encoded = BLOCK["data"]
    note = ("이미지 파일을 읽었습니다: image/png, 64x32 → 64x32, "
            f"{len(__import__('base64').b64decode(encoded)):,}바이트.")
    final = {
        "dispatch_id": DISPATCH_ID, "run_id": RUN_ID, "kind": "read",
        "output": note, "_pc_image": BLOCK,
        "result_sha256": "c" * 64, "content_sha256": "c" * 64,
        "content_bytes": len(encoded),
        "termination": "exited", "exit_code": 0,
        "output_ref": {"handle": "a" * 64, "size": len(encoded),
                       "head": "", "tail": "", "truncated": False},
    }
    _install(monkeypatch, final=final)

    result = asyncio.run(_handler()({"path": "shot.png"}))

    assert result["execution_confirmed"] is True
    # Before the fix this re-wrap rebuilt the outcome from `output` alone and
    # the block the Chat leg produced never reached the MCP caller.
    assert result["_pc_image"] == BLOCK


def test_plain_result_branch_forwards_the_projected_image_block(monkeypatch):
    note = "이미지 파일을 읽었습니다: image/png, 64x32 → 64x32, 120바이트."
    encoded = note.encode("utf-8")
    final = {
        "dispatch_id": DISPATCH_ID, "run_id": RUN_ID, "kind": "read",
        "output": note, "_pc_image": BLOCK,
        "result_sha256": "d" * 64, "content_sha256": "d" * 64,
        "content_bytes": len(encoded),
        "termination": "exited", "exit_code": 0,
    }
    _install(monkeypatch, final=final)

    result = asyncio.run(_handler()({"path": "shot.png"}))

    assert result["content"] == note
    assert result["content_bytes"] == len(encoded)
    assert result["_pc_image"] == BLOCK


def test_without_pil_an_oversized_original_sends_text_only(monkeypatch):
    # CTO decision 2026-11-13: without Pillow the byte cap is unreachable, so
    # an oversized original ships as bounded text only — the unscaled image
    # block the pre-fix fallback returned is exactly what this refuses.
    import base64
    import sys
    monkeypatch.setitem(sys.modules, "PIL", None)
    from app.claw_pc_query_step_driver import (
        PC_IMAGE_BYTE_CAP, PC_IMAGE_ENVELOPE_PREFIX, _pc_image_projection,
    )
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * (PC_IMAGE_BYTE_CAP + 50_000)
    note, block = _pc_image_projection(
        PC_IMAGE_ENVELOPE_PREFIX + "image/png:" + base64.b64encode(raw).decode("ascii"))
    assert block is None
    assert "이미지 축소를 쓸 수 없어 그림을 보내지 못했습니다" in note
