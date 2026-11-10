"""#7447: a pc_read image arrives as one MCP image block, never inline base64.

The engine frames a read image as ``_pc_image`` (already downscaled there);
the transport pops it into one image block beside the bounded text. The
base64 must not leak into the model text or the structured payload.
"""
from __future__ import annotations

import base64
import json

from test_mcp_gateway_transport import gateway, post  # noqa: F401


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
