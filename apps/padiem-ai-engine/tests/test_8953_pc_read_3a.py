"""#8953 3a — engine validates the line cursor and all byte/image limits."""
from __future__ import annotations

import base64
import json
import sys
import types

import pytest

from app.claw_pc_query_step_driver import (
    _pc_chunk_projection, _pc_image_projection, PC_IMAGE_BYTE_CAP,
    PC_IMAGE_ENVELOPE_PREFIX,
)


def line_reply(**overrides):
    data = dict(ok=True,unit="lines",size_bytes=1000,start_line=10,
                line_count=2,text="a\nb",eof=False,partial=False,
                truncated=True,truncation_reason="line_count_limit",
                has_more=True,next_cursor=12,source_complete=True)
    data.update(overrides)
    return json.dumps(data,ensure_ascii=False)


def test_one_based_line_page_validation_and_common_fields():
    page=_pc_chunk_projection(line_reply(),start_line=10,line_count=50)
    assert page["next_cursor"] == 12 and page["truncated"] is True
    assert page["eof"] is False and page["source_complete"] is True
    assert page["truncation_reason"]=="line_count_limit"
    byte=dict(ok=True,unit="bytes",size_bytes=10,offset=0,next_offset=4,
              eof=False,text="abcd")
    old=_pc_chunk_projection(json.dumps(byte),offset=0,length=4)
    assert old["next_offset"]==4 and old["next_cursor"]==4
    assert old["has_more"] is True and old["truncated"] is True
    assert old["truncation_reason"]=="range_limit"
    doc=dict(ok=True,unit="chars",size_bytes=100,offset=0,next_offset=3,
             text="abc",eof=False,partial=True,text_chars=3)
    partial=_pc_chunk_projection(json.dumps(doc),offset=0,length=10)
    assert partial["source_complete"] is False
    assert partial["partial"] is True and partial["truncation_reason"]=="source_prefix_limit"


@pytest.mark.parametrize("mutate",[
    {"next_cursor":11}, {"truncated":False}, {"source_complete":False},
    {"line_count":1001}, {"truncation_reason":"secret"},
    {"text":"a\nb\nc"}, {"partial":True}, {"has_more":False},
    {"unit":"bytes"}, {"size_bytes":-1},
])
def test_untrusted_line_page_invariant_failure(mutate):
    from app.claw_pc_query_step_driver import ToolHandlerError
    with pytest.raises(ToolHandlerError):
        _pc_chunk_projection(line_reply(**mutate),start_line=10,line_count=50)


def test_missing_pillow_oversize_image_is_refused_not_shipped(monkeypatch):
    monkeypatch.setitem(sys.modules,"PIL",None)
    raw=b"\x89PNG\r\n\x1a\n"+b"x"*(PC_IMAGE_BYTE_CAP+10)
    note,block=_pc_image_projection(
        PC_IMAGE_ENVELOPE_PREFIX+"image/png:"+base64.b64encode(raw).decode())
    assert block["type"]=="error" and block["code"]=="pc_image_size_limit_exceeded"
    assert block["original_bytes"]>PC_IMAGE_BYTE_CAP
    assert block["resized"] is False
    assert "보내지 못" in note


def test_final_compression_step_cannot_emit_oversize_block(monkeypatch):
    class FakeImage:
        size=(150,80)
        def save(self,buffer,format=None,quality=None):
            buffer.write(b"y"*(PC_IMAGE_BYTE_CAP+10))
        def convert(self,_mode): return self
        def resize(self,_size): return self
    pil=types.ModuleType("PIL")
    image=types.ModuleType("PIL.Image")
    image.open=lambda _:FakeImage()
    pil.Image=image
    monkeypatch.setitem(sys.modules,"PIL",pil)
    monkeypatch.setitem(sys.modules,"PIL.Image",image)
    raw=b"\x89PNG\r\n\x1a\n"+b"z"*50
    note,block=_pc_image_projection(
        PC_IMAGE_ENVELOPE_PREFIX+"image/png:"+base64.b64encode(raw).decode())
    assert block["type"]=="error" and block["result_bytes"]>PC_IMAGE_BYTE_CAP
    assert block["original_size"] == [150,80] and block["result_size"]==[150,80]
    assert "보내지 못" in note


@pytest.mark.asyncio
async def test_line_mode_uses_same_authorized_chunk_dispatch_with_line_cursor(monkeypatch):
    from test_6460_pc_chunk_read import _install_wire, _chunk_handler
    staged = []
    _install_wire(monkeypatch, [line_reply()], captured=staged)
    answer = await _chunk_handler()({"path":"notes.txt","start_line":10,"line_count":50})
    assert len(staged) == 1
    assert staged[0]["op"] == "read_chunk"
    assert staged[0]["start_line"] == 10 and staged[0]["line_count"] == 50
    assert "offset" not in staged[0] and "length" not in staged[0]
    assert answer["next_offset"] is None
    assert answer["next_cursor"] == 12
    assert answer["has_more"] is True
    assert answer["source_complete"] is True
    for bad in (
        {"path":"notes.txt","start_line":10},
        {"path":"notes.txt","start_line":10,"line_count":1001},
        {"path":"notes.txt","start_line":10,"line_count":2,"offset":0},
        {"path":"notes.txt","start_line":True,"line_count":2},
    ):
        with pytest.raises(Exception):
            await _chunk_handler()(bad)


@pytest.fixture(autouse=True)
def _owner_session_for_chunk_dispatch():
    from app import claw_pc_query_step_driver as driver
    from test_6460_pc_chunk_read import SUBJECT, RUN_ID, PRODUCT, DEVICE
    token=driver._PC_QUERY_OWNER.set((SUBJECT,RUN_ID,PRODUCT,DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(token)
