"""Scan-page read lane: one image page under a bounded 120-second policy.

Why a separate route
--------------------
A completed (non-streaming) image read sends its first body byte only after the
whole answer, reasoning included, is generated, so the normal first-byte and
chain bounds cut a dense page before it can answer. Widening the shared policy
would slow every text call and lengthen the window in which a failed candidate
holds the chain.

This route is the smallest way to give one lane its own bound:

* the path itself selects the policy (`/v1/scan-pages/read`), not a body field;
* the handler accepts only a single-image, non-streaming, tool-free request;
* the canonical gateway still performs its own caller-proof and schema checks,
  so an unproven caller is refused before any provider request is built;
* the switch ``B14_SCAN_READ_ENABLED`` defaults to false, and while it is off
  the route answers 404 without reading a body or touching the gateway.

A caller that sends the same body to the ordinary completions path keeps the
15/40/55 defaults. A body field named like this lane has no effect there, and
no value in this request's body can widen its own deadline.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, Router

SCAN_READ_PATH = "/v1/scan-pages/read"
SCAN_READ_ENABLED_ENV = "B14_SCAN_READ_ENABLED"


def scan_read_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Only the exact value ``true`` opens the lane; everything else is off."""

    source = os.environ if environ is None else environ
    raw = source.get(SCAN_READ_ENABLED_ENV, "")
    return isinstance(raw, str) and raw.strip().lower() == "true"


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": "scan_read_unavailable",
                "message": "이 배포에서는 스캔 쪽 판독 경로를 사용할 수 없습니다.",
            }
        },
        status_code=404,
    )


def _invalid(code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=400)


def _is_single_image_read(raw: Any) -> bool:
    """True for exactly one text+image message, no stream and no tools."""

    if not isinstance(raw, dict) or raw.get("stream") is True:
        return False
    if raw.get("tools"):
        return False
    messages = raw.get("messages")
    if not isinstance(messages, list) or not messages:
        return False
    image_parts = 0
    has_text = False
    for message in messages:
        if not isinstance(message, dict):
            return False
        content = message.get("content")
        if isinstance(content, str):
            has_text = has_text or bool(content.strip())
            continue
        if not isinstance(content, list):
            return False
        for part in content:
            if not isinstance(part, dict):
                return False
            if part.get("type") == "image_url":
                image_parts += 1
            elif part.get("type") == "text" and isinstance(part.get("text"), str):
                has_text = has_text or bool(part["text"].strip())
            else:
                return False
    return image_parts == 1 and has_text


async def pilot_scan_read(request: Request) -> JSONResponse:
    """Serve one scan page read under the scan policy, or refuse before work."""

    if not scan_read_enabled():
        return _unavailable()
    from . import gateway
    from .b14_timeout_policy import scan_read_timeout

    try:
        raw = await gateway._read_json_body(request)
    except Exception:  # noqa: BLE001 - body decoding is the boundary that answers 400
        return _invalid("invalid_request", "요청 본문이 올바른 JSON이 아닙니다.")
    if not _is_single_image_read(raw):
        return _invalid(
            "scan_read_image_required",
            "스캔 판독 경로는 이미지 한 장과 글 한 부분이 있는 비스트리밍 요청만 받습니다.",
        )
    with scan_read_timeout():
        # The canonical gateway repeats the schema/proof checks and performs the
        # provider call. This route only chooses the deadline.
        return await gateway.pilot_chat_completions(request)


router = Router(
    routes=[Route(SCAN_READ_PATH, pilot_scan_read, methods=["POST"])]
)


__all__ = [
    "SCAN_READ_ENABLED_ENV",
    "SCAN_READ_PATH",
    "pilot_scan_read",
    "router",
    "scan_read_enabled",
]
