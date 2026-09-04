from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from workers import Response, WorkerEntrypoint


CONNECT_PATH = "/v1/google/connect"
CALLBACK_PATH = "/v1/google/callback"
MAX_CONNECT_BODY_BYTES = 32_768
MAX_CALLBACK_QUERY_CHARS = 16_384
MAX_RPC_RESULT_CHARS = 65_536

_BASE_HEADERS = {
    "cache-control": "no-store, max-age=0",
    "content-type": "application/json; charset=utf-8",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
}
_ERROR_STATUS = {
    "invalid_connect_ticket": 401,
    "expired_connect_ticket": 410,
    "replayed_connect_ticket": 409,
    "invalid_google_oauth_ingress": 400,
    "invalid_google_oauth_ingress_secret": 503,
    "unreviewed_connect_scope": 403,
    "unreviewed_google_oauth_scope": 403,
    "duplicate_google_oauth_state": 409,
    "missing_google_oauth_state": 410,
    "expired_google_oauth_state": 410,
    "google_oauth_state_mismatch": 400,
    "google_oauth_authorization_denied": 400,
    "google_oauth_token_exchange_failed": 502,
    "google_oauth_scope_mismatch": 403,
    "google_oauth_seal_failed": 503,
    "google_oauth_unseal_failed": 400,
}


def _json_response(status: int, body: dict[str, Any], *, origin: str | None = None) -> Response:
    headers = dict(_BASE_HEADERS)
    if origin is not None:
        headers.update(
            {
                "access-control-allow-origin": origin,
                "vary": "Origin",
            }
        )
    return Response(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        status=status,
        headers=headers,
    )


def _error(status: int, code: str, *, origin: str | None = None) -> Response:
    return _json_response(
        status,
        {
            "ok": False,
            "error": {
                "code": code,
                "message": "Google connector request was rejected",
            },
        },
        origin=origin,
    )


def _required_allowed_origin(env: Any) -> str:
    value = getattr(env, "GOOGLE_OAUTH_ALLOWED_ORIGIN", None)
    if not isinstance(value, str):
        raise RuntimeError("GOOGLE_OAUTH_ALLOWED_ORIGIN is not configured")
    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or len(normalized) > 2_048
    ):
        raise RuntimeError("GOOGLE_OAUTH_ALLOWED_ORIGIN must be one exact HTTPS origin")
    return f"https://{parsed.netloc}"


def _request_origin(request) -> str | None:
    value = request.headers.get("origin")
    return str(value) if value is not None else None


async def _bounded_body(request) -> bytes:
    if request.body is None:
        return b""
    output = bytearray()
    async for chunk in request.body:
        to_bytes = getattr(chunk, "to_bytes", None)
        raw = to_bytes() if callable(to_bytes) else bytes(chunk)
        if not isinstance(raw, bytes):
            raw = bytes(raw)
        if len(output) + len(raw) > MAX_CONNECT_BODY_BYTES:
            raise OverflowError("Google OAuth connect body exceeds the trusted bound")
        output.extend(raw)
    return bytes(output)


def _parse_connect_body(raw: bytes) -> dict[str, Any]:
    if not raw:
        raise ValueError("empty body")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"connect_ticket"}:
        raise ValueError("connect body must contain only connect_ticket")
    ticket = payload.get("connect_ticket")
    if not isinstance(ticket, str) or not ticket:
        raise ValueError("connect_ticket is required")
    return {"connect_ticket": ticket}


def _one(params: dict[str, list[str]], name: str, *, required: bool = False) -> str | None:
    values = params.get(name)
    if not values:
        if required:
            raise ValueError(f"{name} is required")
        return None
    if len(values) != 1 or not isinstance(values[0], str) or not values[0]:
        raise ValueError(f"{name} must appear exactly once")
    return values[0]


def _parse_callback_query(query: str) -> dict[str, Any]:
    if not isinstance(query, str) or len(query) > MAX_CALLBACK_QUERY_CHARS:
        raise ValueError("callback query exceeds the trusted bound")
    params = parse_qs(query, keep_blank_values=True, strict_parsing=False)
    state_ref = _one(params, "state", required=True)
    code = _one(params, "code")
    provider_error = _one(params, "error")
    if (code is None) == (provider_error is None):
        raise ValueError("callback must contain exactly one of code or error")
    # Google may append bounded non-authoritative metadata such as scope,
    # authuser, prompt or hd. None of it is accepted as Padiem authority.
    return {
        "state_ref": state_ref,
        "authorization_code": code,
        "provider_error": provider_error,
    }


def _validate_rpc_result(result: Any, success_field: str) -> dict[str, Any]:
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        raise RuntimeError("Google OAuth private RPC returned an invalid result")
    if result["ok"] is True:
        if set(result) != {"ok", success_field} or not isinstance(result[success_field], dict):
            raise RuntimeError("Google OAuth private RPC success result is not closed")
    else:
        if set(result) != {"ok", "error"} or not isinstance(result["error"], dict):
            raise RuntimeError("Google OAuth private RPC error result is not closed")
        error = result["error"]
        if set(error) != {"code", "message"} or not isinstance(error["code"], str):
            raise RuntimeError("Google OAuth private RPC error payload is not closed")
    if len(json.dumps(result, separators=(",", ":"), ensure_ascii=False)) > MAX_RPC_RESULT_CHARS:
        raise RuntimeError("Google OAuth private RPC result exceeds the trusted bound")
    return result


def _rpc_http_response(result: dict[str, Any], *, success_field: str, origin: str | None) -> Response:
    if result["ok"] is True:
        return _json_response(200, result, origin=origin)
    code = result["error"]["code"]
    return _error(_ERROR_STATUS.get(code, 400), code, origin=origin)


class Default(WorkerEntrypoint):
    """Dedicated HTTPS edge for Google OAuth only; no Local Agent route overlap."""

    async def fetch(self, request):
        parsed = urlparse(str(request.url))
        if parsed.scheme.lower() != "https":
            return _error(403, "google_oauth_https_required")

        if parsed.path == CONNECT_PATH and request.method == "OPTIONS":
            try:
                allowed_origin = _required_allowed_origin(self.env)
            except RuntimeError:
                return _error(503, "google_oauth_origin_not_configured")
            origin = _request_origin(request)
            requested_method = request.headers.get("access-control-request-method")
            requested_headers = str(request.headers.get("access-control-request-headers") or "").lower()
            if origin != allowed_origin or str(requested_method).upper() != "POST":
                return _error(403, "google_oauth_origin_rejected")
            if requested_headers and requested_headers != "content-type":
                return _error(403, "google_oauth_preflight_headers_rejected", origin=allowed_origin)
            headers = dict(_BASE_HEADERS)
            headers.update(
                {
                    "access-control-allow-origin": allowed_origin,
                    "access-control-allow-methods": "POST",
                    "access-control-allow-headers": "Content-Type",
                    "access-control-max-age": "300",
                    "vary": "Origin",
                }
            )
            return Response("", status=204, headers=headers)

        if parsed.path == CONNECT_PATH:
            if request.method != "POST":
                return _error(405, "google_oauth_connect_post_required")
            if parsed.query:
                return _error(400, "google_oauth_connect_query_forbidden")
            try:
                allowed_origin = _required_allowed_origin(self.env)
            except RuntimeError:
                return _error(503, "google_oauth_origin_not_configured")
            origin = _request_origin(request)
            if origin != allowed_origin:
                return _error(403, "google_oauth_origin_rejected")
            content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                return _error(415, "google_oauth_connect_json_required", origin=allowed_origin)
            try:
                payload = _parse_connect_body(await _bounded_body(request))
                result = await self.env.GOOGLE_OAUTH_SERVICE.begin_connect(payload)
                result = _validate_rpc_result(result, "authorization")
            except OverflowError:
                return _error(413, "google_oauth_connect_body_too_large", origin=allowed_origin)
            except ValueError:
                return _error(400, "google_oauth_connect_body_invalid", origin=allowed_origin)
            except Exception:
                return _error(503, "google_oauth_dependency_unavailable", origin=allowed_origin)
            return _rpc_http_response(result, success_field="authorization", origin=allowed_origin)

        if parsed.path == CALLBACK_PATH:
            if request.method != "GET":
                return _error(405, "google_oauth_callback_get_required")
            try:
                payload = _parse_callback_query(parsed.query)
                result = await self.env.GOOGLE_OAUTH_SERVICE.complete_callback(payload)
                result = _validate_rpc_result(result, "connection")
            except ValueError:
                return _error(400, "google_oauth_callback_invalid")
            except Exception:
                return _error(503, "google_oauth_dependency_unavailable")
            return _rpc_http_response(result, success_field="connection", origin=None)

        return _error(404, "google_oauth_route_not_found")


GOOGLE_OAUTH_PUBLIC_EDGE_SOURCE = True
HTTPS_REQUIRED = True
CONNECT_POST_ONLY = True
CONNECT_TICKET_BODY_ONLY = True
CONNECT_QUERY_FORBIDDEN = True
CONNECT_EXACT_ORIGIN_REQUIRED = True
CORS_WILDCARD = False
CREDENTIALLED_CORS = False
STRICT_BOOLEAN_RPC_STATUS = True
CALLBACK_GET_ONLY = True
CALLBACK_AUTHORIZATION_CODE_QUERY_PROTOCOL_REQUIRED = True
CALLBACK_QUERY_AUTHORITY = False
PRIVATE_SERVICE_BINDING_RPC = True
LOCAL_AGENT_ROUTE_OVERLAP = False
RAW_CONNECT_TICKET_LOGGED = False
RAW_AUTHORIZATION_CODE_LOGGED = False
RAW_REFRESH_TOKEN_RETURNED = False
PUBLIC_HOSTNAME_CONFIGURED = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
