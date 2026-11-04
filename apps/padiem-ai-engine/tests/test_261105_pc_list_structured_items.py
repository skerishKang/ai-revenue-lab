"""261105: pc_list answers fields, one complete page, and readable times.

The MCP answer carried the PowerShell transcript as one string, its middle cut to
"...", and the same text three times (output, output_ref.head, output_ref.tail).
A page of 50 rows therefore arrived with rows missing and a `/Date(…)/` time.
These tests drive the handler with the real wire shapes.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    PC_LIST_FILES_TOOL_ID,
    _make_pc_file_handler,
)

RUN_ID = "run_261105_list"
SUBJECT = "sub_" + "1" * 32
PRODUCT = "b54-padiem-claw"
DEVICE = "pc-com2"
DISPATCH_ID = "dsp_261105"

PAGE = {
    "offset": 0,
    "total": 51,
    "has_more": True,
    "items": [
        {"Name": "chat.log", "Length": 12, "Modified": "2026-11-05T06:12:34.5670000Z",
         "PSIsContainer": False},
        {"Name": "chat", "Length": None, "Modified": "/Date(1793821590883)/",
         "PSIsContainer": True},
    ],
}


@pytest.fixture(autouse=True)
def _owner_run():
    token = driver._PC_QUERY_OWNER.set((SUBJECT, RUN_ID, PRODUCT, DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)


async def _no_sleep(_seconds: float) -> None:
    return None


def _install_wire(monkeypatch, *, output: str, full: str | None = None,
                  stored: bool = False) -> None:
    """A result leg that answers a preview plus the stored original behind it."""
    stored_text = output if full is None else full
    stored_bytes = stored_text.encode("utf-8")
    preview_bytes = output.encode("utf-8")

    async def fake_call(**kwargs):
        mode = kwargs["mode"]
        if mode == "dispatch":
            return {"dispatch": {"run_id": RUN_ID, "kind": "command",
                                 "dispatch_id": DISPATCH_ID}}
        if mode == "command_status":
            return {"dispatch": {"dispatch_id": DISPATCH_ID, "run_id": RUN_ID,
                                 "kind": "command", "state": "done"}}
        if mode == "result":
            dispatch = {
                "dispatch_id": DISPATCH_ID, "run_id": RUN_ID, "kind": "command",
                "output": output, "result_sha256": "a" * 64,
                "content_sha256": "a" * 64, "content_bytes": len(stored_bytes),
                "termination": "no_exit_code", "exit_code": None,
            }
            if stored:
                dispatch["output_ref"] = {
                    "handle": "b" * 64, "size": len(stored_bytes),
                    "head": output[:16], "tail": output[-16:], "truncated": True,
                }
            return {"dispatch": dispatch}
        if mode == "read_output":
            offset = kwargs["payload"]["offset"]
            length = kwargs["payload"]["length"]
            return {"result": {"content": stored_bytes[offset:offset + length].decode("utf-8"),
                               "offset": offset, "size": len(stored_bytes)}}
        raise AssertionError("unexpected mode " + str(mode))

    monkeypatch.setattr(driver, "_signed_files_call", fake_call)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    assert preview_bytes  # the preview is the first answer, never the parse source


def _list():
    return asyncio.run(_make_pc_file_handler(
        tool_id=PC_LIST_FILES_TOOL_ID, op="list", service=object(),
        request_factory=lambda *a, **k: None, secret="s" * 40,
    )({"path": "."}))


def test_a_page_is_returned_as_fields_not_as_a_transcript(monkeypatch) -> None:
    _install_wire(monkeypatch, output=json.dumps(PAGE))
    result = _list()

    listing = result["output"]
    assert isinstance(listing, dict)
    assert listing["ok"] is True and listing["path"] == "."
    assert listing["offset"] == 0 and listing["total"] == 51
    assert listing["has_more"] is True
    assert [item["name"] for item in listing["items"]] == ["chat.log", "chat"]
    assert listing["items"][0] == {
        "name": "chat.log", "type": "file", "size": 12,
        "modified": "2026-11-05T06:12:34.5670000Z", "path": "chat.log",
    }
    assert listing["items"][1]["type"] == "dir"
    assert listing["items"][1]["size"] is None
    # The serialized PowerShell date becomes an explicit instant.
    from datetime import datetime, timezone
    expected = datetime.fromtimestamp(1793821590883 / 1000, tz=timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")
    assert listing["items"][1]["modified"] == expected
    assert result["has_more"] is True and result["total"] == 51
    assert "output_ref" not in result


def test_a_previewed_page_is_parsed_from_the_stored_original(monkeypatch) -> None:
    full = json.dumps(PAGE)
    preview = full[:16] + "\n...\n" + full[-16:]
    _install_wire(monkeypatch, output=preview, full=full, stored=True)
    result = _list()

    # Every row of the page survives even though the wire answer was a preview.
    assert [item["name"] for item in result["output"]["items"]] == ["chat.log", "chat"]
    assert "output_ref" not in result


def test_an_old_wrapped_listing_still_answers_fields(monkeypatch) -> None:
    _install_wire(monkeypatch, output=json.dumps({
        "ok": True, "entries": [{"Name": "old.txt", "Length": 3, "PSIsContainer": False}],
        "truncated": True,
    }))
    result = _list()

    assert [item["name"] for item in result["output"]["items"]] == ["old.txt"]
    assert result["output"]["has_more"] is True


def test_a_folder_error_still_names_its_failure(monkeypatch) -> None:
    _install_wire(monkeypatch, output=json.dumps({"error": "denied"}))
    with pytest.raises(driver.ToolHandlerError) as caught:
        _list()

    assert caught.value.code == "pc_list_failed"
