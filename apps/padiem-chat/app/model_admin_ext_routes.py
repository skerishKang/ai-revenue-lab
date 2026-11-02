"""Owner model console write surface.

Every route here reuses the existing global-model-administrator authority and
relays one bounded request to B14 over the caller-proof lane. The browser never
talks to B14 and never holds a Provider key; B14 is the only process that reads
or writes a credential slot file.

Two extra rules apply to the whole surface:

* **A key value is write-only.** The credential route requires a login minted
  inside the last five minutes, and the response is scrubbed to the fields the
  screen needs (slot, length, last four, target, backup flag).
* **Nothing is inferred to be a success.** A transport failure is a closed 5xx
  code and a refused write keeps its own code; neither becomes an empty result.

The registry is read here as well, so the model and Provider tabs can render
what B14 actually installed instead of a browser-side copy that could drift.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import SESSION_COOKIE, decode_session_claims
from .b14_model_ops_source import (
    AUDIT_PATH,
    CREDENTIAL_WRITE_PATH,
    MAX_REQUEST_BYTES,
    MODEL_APPLY_PATH,
    MODEL_RETIRE_PATH,
    PROBE_PATH,
    PROVIDER_APPLY_PATH,
    REGISTRY_PATH,
    ModelOpsUnavailable,
)
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .central_model_control_routes import _central_admin, _error

REGISTRY_ROUTE = "/api/admin/model-admin/registry"
PROBE_ROUTE = "/api/admin/model-admin/model-probe"
MODEL_APPLY_ROUTE = "/api/admin/model-admin/model-apply"
MODEL_RETIRE_ROUTE = "/api/admin/model-admin/model-retire"
PROVIDER_APPLY_ROUTE = "/api/admin/model-admin/provider-apply"
CREDENTIAL_WRITE_ROUTE = "/api/admin/model-admin/credential-write"
AUDIT_ROUTE = "/api/admin/model-admin/audit"

REAUTH_WINDOW_SECONDS = 300
MAX_RESPONSE_KEYS = 20000
MAX_RESPONSE_DEPTH = 8
MAX_RESPONSE_STRING = 4096
MAX_MESSAGE_LENGTH = 200
_SAFE_STATUSES = frozenset({200, 400, 404, 409, 413, 503})
_CODE = re.compile(r"\A[a-z0-9_]{1,64}\Z")
_FORBIDDEN_KEY = re.compile(
    r"\A(?:value|values|secret|secrets|key|keys|token|tokens|raw|raw_body|"
    r"api_key|apikey|credential_value|password)\Z",
    re.IGNORECASE,
)
_NO_STORE = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


def _relay_error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status, headers=_NO_STORE,
    )


class _ScrubError(ValueError):
    pass


def _scrub(value: Any, *, depth: int = 0) -> Any:
    """Keep the document JSON-shaped and drop any field that names a secret.

    B14 is trusted, but this route is the last place a value could leave the
    boundary, so the response is rebuilt from the same allowlist idea the
    read-only slot board uses: known shape, bounded size, no secret field name.
    """
    if depth > MAX_RESPONSE_DEPTH:
        raise _ScrubError("too deep")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_RESPONSE_STRING:
            raise _ScrubError("string too long")
        return value
    if isinstance(value, list):
        if len(value) > MAX_RESPONSE_KEYS:
            raise _ScrubError("list too long")
        return [_scrub(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > MAX_RESPONSE_KEYS:
            raise _ScrubError("mapping too long")
        clean: dict[str, Any] = {}
        for name, item in value.items():
            if not isinstance(name, str) or _FORBIDDEN_KEY.fullmatch(name):
                raise _ScrubError("secret field")
            clean[name] = _scrub(item, depth=depth + 1)
        return clean
    raise _ScrubError("unsupported type")


def _relay_payload(status: int, payload: Any) -> JSONResponse:
    if status not in _SAFE_STATUSES:
        return _relay_error(502, "b14_model_ops_invalid_response")
    if not isinstance(payload, dict):
        return _relay_error(502, "b14_model_ops_invalid_response")
    if status == 200:
        if payload.get("ok") is not True:
            return _relay_error(502, "b14_model_ops_invalid_response")
        try:
            body = _scrub(payload)
        except _ScrubError:
            return _relay_error(502, "b14_model_ops_invalid_response")
        return JSONResponse(body, status_code=200, headers=_NO_STORE)
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if not isinstance(code, str) or _CODE.fullmatch(code) is None:
        return _relay_error(502, "b14_model_ops_invalid_response")
    body: dict[str, Any] = {"ok": False, "error": {"code": code}}
    if isinstance(message, str) and 0 < len(message) <= MAX_MESSAGE_LENGTH:
        body["error"]["message"] = message
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _recent_login(request: Request) -> bool:
    """Whether this session proved the owner's password in the last five minutes.

    A cookie minted before the ``iat`` claim existed carries no issued time, so
    it can never satisfy a fresh-login requirement: the owner logs in again
    instead of this route assuming the old cookie is recent.
    """
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        return False
    claims = decode_session_claims(settings, request.cookies.get(SESSION_COOKIE))
    if claims is None or claims.issued_at is None:
        return False
    age = int(time.time()) - claims.issued_at
    return 0 <= age <= REAUTH_WINDOW_SECONDS


async def _dispatch(
    request: Request, path: str, *, method: str, require_recent_login: bool = False,
) -> JSONResponse:
    denied = await _central_admin(request)
    if denied is not None:
        return denied
    if require_recent_login and not _recent_login(request):
        return _error(403, "reauth_required")
    source = getattr(request.app.state, "b14_model_ops_source", None)
    call = getattr(source, "call", None)
    if not callable(call):
        return _error(503, "b14_model_ops_unconfigured")

    payload: dict[str, Any] | None = None
    if method != "GET":
        try:
            raw = await read_bounded_request_body(request, max_bytes=MAX_REQUEST_BYTES)
        except RequestBodyTooLarge:
            return _error(413, "request_body_too_large")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return _error(400, "request_body_invalid")
        if not isinstance(decoded, dict):
            return _error(400, "request_body_invalid")
        payload = decoded

    try:
        status, response = await call(path, payload)
    except ModelOpsUnavailable as exc:
        code = exc.code
        http_status = 503 if code.endswith("unconfigured") else 502
        return _error(http_status, code)
    except Exception:
        return _error(502, "b14_model_ops_unavailable")
    return _relay_payload(status, response)


async def model_admin_registry(request: Request):
    return await _dispatch(request, REGISTRY_PATH, method="GET")


async def model_admin_audit(request: Request):
    return await _dispatch(request, AUDIT_PATH, method="GET")


async def model_admin_probe(request: Request):
    return await _dispatch(request, PROBE_PATH, method="POST")


async def model_admin_model_apply(request: Request):
    return await _dispatch(request, MODEL_APPLY_PATH, method="POST")


async def model_admin_model_retire(request: Request):
    return await _dispatch(request, MODEL_RETIRE_PATH, method="POST")


async def model_admin_provider_apply(request: Request):
    return await _dispatch(request, PROVIDER_APPLY_PATH, method="POST")


async def model_admin_credential_write(request: Request):
    return await _dispatch(
        request, CREDENTIAL_WRITE_PATH, method="POST", require_recent_login=True,
    )


MODEL_ADMIN_ROUTES = (
    (REGISTRY_ROUTE, model_admin_registry, "GET"),
    (AUDIT_ROUTE, model_admin_audit, "GET"),
    (PROBE_ROUTE, model_admin_probe, "POST"),
    (MODEL_APPLY_ROUTE, model_admin_model_apply, "POST"),
    (MODEL_RETIRE_ROUTE, model_admin_model_retire, "POST"),
    (PROVIDER_APPLY_ROUTE, model_admin_provider_apply, "POST"),
    (CREDENTIAL_WRITE_ROUTE, model_admin_credential_write, "POST"),
)