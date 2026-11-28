"""#7447: a pc_read image arrives as one MCP image block, never inline base64.

The engine frames a read image as ``_pc_image`` (already downscaled there);
the transport pops it into one image block beside the bounded text. The
base64 must not leak into the model text or the structured payload.
"""
from __future__ import annotations

import base64
import json

from _support.mcp_gateway_transport import gateway, post  # noqa: F401


def test_pc_read_image_is_one_image_block_and_never_inline_text(gateway):
    encoded = base64.b64encode(b"synthetic PC image fixture only").decode()

    async def read(*args, **kwargs):
        return {"status": "completed", "content": "이미지 파일을 읽었습니다.",
                "_pc_image": {"type": "image", "mimeType": "image/png",
                              "data": encoded}}

    gateway.app.state.mcp_gateway_executor = read
    result = post(gateway, "tools/call", params={"name": "pc_read",
                  "arguments": {"path": "screenshot.png"}}).json()["result"]
    images = [block for block in result["content"] if block["type"] == "image"]
    assert images == [{"type": "image", "mimeType": "image/png", "data": encoded}]
    assert encoded not in json.dumps(result["structuredContent"])
    assert encoded not in result["content"][0]["text"]


def test_pc_read_image_nested_under_output_is_also_lifted(gateway):
    # The engine wrapper nests the file result under "output"; the transport
    # lifts the same image block from there (#7447).
    encoded = base64.b64encode(b"nested PC image fixture").decode()

    async def read(*args, **kwargs):
        return {"status": "completed", "answer": "PC 작업 결과를 확인했습니다.",
                "output": {"content": "이미지 파일을 읽었습니다.",
                           "_pc_image": {"type": "image", "mimeType": "image/png",
                                         "data": encoded}}}

    gateway.app.state.mcp_gateway_executor = read
    result = post(gateway, "tools/call", params={"name": "pc_read",
                  "arguments": {"path": "screenshot.png"}}).json()["result"]
    images = [block for block in result["content"] if block["type"] == "image"]
    assert images == [{"type": "image", "mimeType": "image/png", "data": encoded}]
    assert encoded not in json.dumps(result["structuredContent"])


def test_pc_read_mcp_final_image_size_cap_is_fail_closed(gateway):
    # Even a future/older engine that accidentally hands over an oversized
    # image cannot bypass the final MCP 300 KB boundary.
    oversized = base64.b64encode(b"x" * 300001).decode("ascii")
    async def read(*args, **kwargs):
        return {"status":"completed","content":"file seen",
                "_pc_image":{"type":"image","mimeType":"image/png",
                             "data":oversized,"resized":False,
                             "original_size":[600,400],"result_size":[600,400],
                             "original_bytes":300001,"result_bytes":300001}}
    gateway.app.state.mcp_gateway_executor = read
    result=post(gateway,"tools/call",params={"name":"pc_read",
                  "arguments":{"path":"oversized.png"}}).json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["status"] == "failed"
    assert result["structuredContent"]["code"] == "pc_image_size_limit_exceeded"
    assert not any(item["type"]=="image" for item in result["content"])
    assert oversized not in json.dumps(result["structuredContent"])


def test_pc_read_mcp_image_keeps_metadata_but_no_inline_payload(gateway):
    small = base64.b64encode(b"small image fixture").decode("ascii")
    async def read(*args, **kwargs):
        return {"status":"completed","content":"read one image",
                "_pc_image":{"type":"image","mimeType":"image/png","data":small,
                            "resized":True,"original_size":[3000,1500],
                            "result_size":[2000,1000],"original_bytes":400000,
                            "result_bytes":19}}
    gateway.app.state.mcp_gateway_executor = read
    result=post(gateway,"tools/call",params={"name":"pc_read",
                "arguments":{"path":"small.png"}}).json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["image_info"]["resized"] is True
    assert result["structuredContent"]["image_info"]["original_size"]==[3000,1500]
    assert result["structuredContent"]["image_info"]["result_size"]==[2000,1000]
    image=[item for item in result["content"] if item["type"]=="image"]
    assert image == [{"type":"image","mimeType":"image/png","data":small}]
    assert small not in result["content"][0]["text"]
