"""#5882 A: a read answer over one page's size pages instead of failing.

`read_file` answers with at most one page of text. A file larger than that page
used to end in `pc_files_output_too_large` — an error the model could not act
on. It now hands back the same #6541 range answer the executor's `too_large`
marker already produced: first range, whole size, `next_offset`, and the
`read_file_chunk` continuation. Nothing new is invented here and the connector
is not involved.

The scenes ride the existing #5015 read harness (owner run, signed fake call,
`_result_row`), the same way test_5015_pc_read_handler does.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

# The shared PC read harness lives beside this file, and this suite does not
# put its own directory on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app.claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    PC_FILES_READ_MAX_BYTES,
    PC_READ_FILE_TOOL_ID,
    _make_pc_file_handler,
)
from padiem_ai_core.tool_runtime import ToolHandlerError

from test_5015_pc_read_handler import RUN_ID, _install, _result_row

SUBJECT = "sub_" + "5" * 32
DEVICE = "pc-com2"


@pytest.fixture(autouse=True)
def _owner_run():
    token = driver._PC_QUERY_OWNER.set((SUBJECT, RUN_ID, "padiem-chat", DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)


class FirstChunk:
    """The #6541 range call the read tool already owns."""

    def __init__(self, *, size: int) -> None:
        self.size = size
        self.calls: list[dict] = []

    async def __call__(self, arguments):
        self.calls.append(dict(arguments))
        return {
            "output": json.dumps({
                "unit": "bytes", "offset": 0, "text": "head",
                "next_offset": 4, "size_bytes": self.size, "eof": False,
            }),
            "unit": "bytes",
            "size_bytes": self.size,
            "next_offset": 4,
            "eof": False,
        }


def _handler(first_chunk=None):
    return _make_pc_file_handler(
        tool_id=PC_READ_FILE_TOOL_ID, op="read", service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
        first_chunk=first_chunk,
    )


def test_exactly_the_page_is_one_whole_answer(monkeypatch):
    content = "x" * PC_FILES_READ_MAX_BYTES
    _install(monkeypatch, result=_result_row(output=content))
    first_chunk = FirstChunk(size=len(content))
    result = asyncio.run(_handler(first_chunk)({"path": "notes.txt"}))

    assert result["content"] == content
    assert result["content_bytes"] == PC_FILES_READ_MAX_BYTES
    assert "continued" not in result
    assert first_chunk.calls == [], "a page-sized read must not page"


def test_one_byte_over_the_page_returns_the_first_range(monkeypatch):
    content = "x" * (PC_FILES_READ_MAX_BYTES + 1)
    _install(monkeypatch, result=_result_row(output=content))
    first_chunk = FirstChunk(size=len(content))
    result = asyncio.run(_handler(first_chunk)({"path": "huge.txt"}))

    assert first_chunk.calls == [{"path": "huge.txt", "offset": 0}]
    assert result["continued"] is True
    assert result["why"] == "file_over_single_read_cap"
    assert result["size_bytes"] == len(content)
    assert result["next_offset"] == 4
    assert result["eof"] is False
    body = json.loads(result["output"])
    assert body["text"] == "head" and body["size_bytes"] == len(content)


def test_a_hundred_mb_file_reports_its_whole_size_and_continues(monkeypatch):
    content = "가" * 40_000_000  # 120 MB of UTF-8 text.
    _install(monkeypatch, result=_result_row(output=content))
    first_chunk = FirstChunk(size=120_000_000)
    result = asyncio.run(_handler(first_chunk)({"path": "big.txt"}))

    assert result["continued"] is True
    assert result["size_bytes"] == 120_000_000
    assert result["next_offset"] == 4
    assert len(first_chunk.calls) == 1


def test_without_a_range_path_the_bounded_error_still_stands(monkeypatch):
    content = "x" * (PC_FILES_READ_MAX_BYTES + 1)
    _install(monkeypatch, result=_result_row(output=content))
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(_handler(None)({"path": "huge.txt"}))
    assert caught.value.code == "pc_files_output_too_large"


def test_a_binary_style_failure_is_never_paged(monkeypatch):
    """A non-text read keeps its existing refusal; paging is meaningless there."""
    _install(monkeypatch, result=_result_row(
        output="PADIEM_PC_FILE_ERROR:read_failed", exit_code=1,
    ))
    first_chunk = FirstChunk(size=10)
    with pytest.raises(ToolHandlerError) as caught:
        asyncio.run(_handler(first_chunk)({"path": "photo.jpg"}))
    assert caught.value.code == "pc_file_read_failed"
    assert first_chunk.calls == []
