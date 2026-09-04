from __future__ import annotations

import base64
import json
from urllib.parse import urlparse

from workers import Response

from padiem_control_plane.local_agent_broker_http import MAX_LOCAL_AGENT_HTTP_BODY_BYTES
from local_agent_broker_device_http import DEVICE_HTTP_ROUTES

_PRIVATE_DEVICE_ROUTE_SET = frozenset(DEVICE_HTTP_ROUTES)
_RESPONSE_HEADERS = {"cache-control": "no-store", "content-type": "application/json"}


def _response(status: int, body: dict) -> Response:
    return Response(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        status=status,
        headers=_RESPONSE_HEADERS,
    )


def _error(status: int, code: str, message: str) -> Response:
    return _response(status, {"ok": False, "error": {"code": code, "message": message}})


async def _bounded_request_body(request) -> bytes:
    if request.body is None:
        return b""
    output = bytearray()
    async for chunk in request.body:
        to_bytes = getattr(chunk, "to_bytes", None)
        raw = to_bytes() if callable(to_bytes) else bytes(chunk)
        if not isinstance(raw, bytes):
            raw = bytes(raw)
        if len(output) + len(raw) > MAX_LOCAL_AGENT_HTTP_BODY_BYTES:
            raise OverflowError("Local Agent private device request exceeds size bound")
        output.extend(raw)
    return bytes(output)


async def handle_private_device_fetch(request, stub_factory) -> Response:
    """Translate a private Service Binding Request into the canonical device envelope."""

    parsed = urlparse(str(getattr(request, "url", "")))
    if parsed.path not in _PRIVATE_DEVICE_ROUTE_SET:
        return Response("Not Found", status=404, headers={"cache-control": "no-store"})
    if parsed.scheme.lower() != "https":
        return _error(403, "local_agent_http_tls_required", "Local Agent broker requires HTTPS")
    if getattr(request, "method", None) != "POST":
        return _error(405, "local_agent_http_post_required", "Local Agent broker routes accept POST only")

    try:
        body = await _bounded_request_body(request)
    except OverflowError:
        return _error(413, "local_agent_http_body_too_large", "Local Agent broker request body exceeds size bound")
    except Exception:
        return _error(400, "local_agent_http_invalid_json", "Local Agent broker request body is invalid")

    headers = getattr(request, "headers", None)
    content_type = headers.get("content-type") if headers is not None else None
    envelope = {
        "method": "POST",
        "route": parsed.path,
        "content_type": str(content_type) if content_type is not None else "",
        "body_b64": base64.b64encode(body).decode("ascii"),
        "tls_verified": True,
    }

    try:
        result = await stub_factory().handle_device_http(envelope)
    except Exception:
        return _error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")

    if (
        type(result) is not dict
        or type(result.get("status")) is not int
        or type(result.get("headers")) is not dict
        or type(result.get("body")) is not dict
        or not 100 <= result["status"] <= 599
    ):
        return _error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")
    return _response(result["status"], result["body"])


PRIVATE_SERVICE_BINDING_FETCH = True
CANONICAL_DEVICE_HTTP_SERVICE_REUSED = True
SECOND_DEVICE_AUTHORITY = False
ADMIN_RPC_HTTP_EXPOSED = False
BOUNDED_BODY = True
