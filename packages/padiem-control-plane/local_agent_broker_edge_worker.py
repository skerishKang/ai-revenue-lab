from __future__ import annotations

import base64
import json
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from padiem_control_plane.local_agent_broker_http import MAX_LOCAL_AGENT_HTTP_BODY_BYTES
from local_agent_broker_device_http import DEVICE_HTTP_ROUTES

_ROUTE_SET = frozenset(DEVICE_HTTP_ROUTES)
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
        if callable(to_bytes):
            raw = to_bytes()
        else:
            raw = bytes(chunk)
        if not isinstance(raw, bytes):
            raw = bytes(raw)
        if len(output) + len(raw) > MAX_LOCAL_AGENT_HTTP_BODY_BYTES:
            raise OverflowError("Local Agent edge request body exceeds size bound")
        output.extend(raw)
    return bytes(output)


class Default(WorkerEntrypoint):
    """Thin HTTPS-only device edge forwarding to a private broker Service Binding."""

    async def fetch(self, request):
        parsed = urlparse(str(request.url))
        if parsed.scheme.lower() != "https":
            return _error(403, "local_agent_http_tls_required", "Local Agent broker requires HTTPS")
        if request.method != "POST":
            return _error(405, "local_agent_http_post_required", "Local Agent broker routes accept POST only")
        if parsed.path not in _ROUTE_SET:
            return _error(404, "local_agent_http_route_not_found", "Local Agent broker route was not found")

        try:
            body = await _bounded_request_body(request)
        except OverflowError:
            return _error(413, "local_agent_http_body_too_large", "Local Agent broker request body exceeds size bound")
        if not body:
            return _error(400, "local_agent_http_invalid_json", "Local Agent broker request body is invalid")

        content_type = request.headers.get("content-type")
        envelope = {
            "method": request.method,
            "route": parsed.path,
            "content_type": str(content_type) if content_type is not None else "",
            "body_b64": base64.b64encode(body).decode("ascii"),
            "tls_verified": True,
        }
        result = await self.env.LOCAL_AGENT_BROKER_SERVICE.handle_device_http(envelope)
        if (
            type(result) is not dict
            or type(result.get("status")) is not int
            or type(result.get("headers")) is not dict
            or type(result.get("body")) is not dict
        ):
            return _error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")
        status = result["status"]
        if not 100 <= status <= 599:
            return _error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")
        return _response(status, result["body"])


PUBLIC_DEVICE_ROUTE_SOURCE = True
PRIVATE_SERVICE_BINDING = True
HTTPS_REQUIRED = True
POST_ONLY = True
BOUNDED_BODY = True
CLOSED_DEVICE_ROUTES = True
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
ADMIN_BROKER_RPC_PUBLIC = False
RAW_DEVICE_SECRET_LOGGED = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_SECRET_BOUND = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
