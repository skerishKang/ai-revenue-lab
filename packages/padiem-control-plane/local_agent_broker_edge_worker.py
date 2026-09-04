from __future__ import annotations

import json
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

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
            response = await self.env.LOCAL_AGENT_BROKER_SERVICE.fetch(request)
        except Exception:
            return _error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")

        status = getattr(response, "status", None)
        if type(status) is not int or not 100 <= status <= 599 or status >= 500:
            return _error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")
        return response


PUBLIC_DEVICE_ROUTE_SOURCE = True
PRIVATE_SERVICE_BINDING = True
PRIVATE_SERVICE_BINDING_FETCH = True
EDGE_TO_STATE_DEVICE_TRANSPORT = "service_binding_fetch"
HTTPS_REQUIRED = True
POST_ONLY = True
CLOSED_DEVICE_ROUTES = True
BOUNDED_BODY_ENFORCED_BY_PRIVATE_STATE = True
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
ADMIN_BROKER_RPC_PUBLIC = False
RAW_DEVICE_SECRET_LOGGED = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_SECRET_BOUND = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
