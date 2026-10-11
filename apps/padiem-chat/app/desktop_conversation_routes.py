"""#3436 B2c — the GET-only canonical conversation surface for the Padiem Desktop.

``GET /api/desktop/conversations`` and ``GET /api/desktop/conversations/{id}``
project the same canonical HistoryStore conversations the Web
``/api/conversations`` surface reads, to the signed-in owner's paired Desktop,
through the canonical Local Agent Broker device session. Nothing else in B2c
feeds that surface.

Authority boundary
------------------
* Identity is the canonical broker device session only. The route forwards the
  caller-held session material (``session_id``, ``binding_ref``,
  ``credential_b64``) to the trusted ``LOCAL_AGENT_BROKER_AUTHORITY_SERVICE``
  binding, whose ``authenticate_device_session`` RPC runs the existing canonical
  verifier and derives ``account_ref`` / ``workspace_ref`` from the verified
  binding state. No browser cookie, no Desktop bearer token, no self-asserted
  identity exists on this surface:
  ``BROWSER_PADIEM_SESSION_COOKIE_COPY = 0``,
  ``DESKTOP_USER_SESSION_AUTHORITY = 0``,
  ``SECOND_IDENTITY_AUTHORITY = 0``,
  ``SECOND_SESSION_AUTHORITY = 0``,
  ``SECOND_CREDENTIAL_VERIFIER = 0``.
* The request can never name its owner or scope. There is no user_id,
  account_ref, workspace_ref, tenant or product input: query parameters and
  extra headers are ignored, never interpreted
  (``CALLER_WORKSPACE_AUTHORITY = 0``,
  ``SERVER_DERIVED_WORKSPACE_REF = True``).
* The read scope is the existing HistoryStore owner dimension, exactly the
  store the Web routes read (``HISTORY_STORE_REUSED = True``,
  ``NEW_CONVERSATION_DATABASE = 0``). The store's conversations are
  owner-wide: the canonical broker ``workspace_ref`` is derived, validated and
  reported to trusted server code only, but the store carries no workspace
  column, so the read is owner-scoped. That fact is recorded here and in the
  composition contract (``HISTORY_STORE_WORKSPACE_DIMENSION = "owner_wide"``),
  never silently dropped.
* Read-only and GET only. No create, no delete, no chat write, no composer:
  ``CREATE = 0``, ``DELETE = 0``, ``CHAT_WRITE = 0``, ``COMPOSER = 0``.
* Every refusal is non-disclosing. Authentiation failures are one uniform 401
  code; a foreign, malformed or unknown conversation id is the same 404 —
  whether an id exists in another owner's history is never disclosed.
* The device session material is read from closed headers, validated for
  shape, and never logged, echoed, or persisted. The conversation responses
  are assembled from the HistoryStore's own projection; no credential, digest,
  token or session material can reach the caller.

Contract markers
----------------
``READ_LIST = "YES"``
``READ_DETAIL = "YES"``
``CREATE = 0``
``DELETE = 0``
``CHAT_WRITE = 0``
``MUTATION = False``
``PRODUCTION_MUTATION = False``
"""

from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .desktop_conversation_authority import (
    DesktopDeviceSessionAuthority,
    UnconfiguredDesktopDeviceSessionAuthority,
)
from .history import HistoryStore, validate_conversation_id

__all__ = [
    "DESKTOP_CONVERSATIONS_PATH",
    "DESKTOP_CONVERSATION_DETAIL_PATH",
    "DEVICE_SESSION_ID_HEADER",
    "DEVICE_SESSION_BINDING_REF_HEADER",
    "DEVICE_SESSION_CREDENTIAL_HEADER",
    "DESKTOP_DEVICE_SESSION_AUTH_FAILED",
    "DESKTOP_AUTHORITY_UNCONFIGURED",
    "desktop_conversations",
    "desktop_conversation_detail",
]

DESKTOP_CONVERSATIONS_PATH = "/api/desktop/conversations"
DESKTOP_CONVERSATION_DETAIL_PATH = "/api/desktop/conversations/{conversation_id}"

# The closed device-session material headers. Exactly these three, exactly
# these shapes; anything else on the request is ignored, never interpreted.
DEVICE_SESSION_ID_HEADER = "x-padiem-device-session-id"
DEVICE_SESSION_BINDING_REF_HEADER = "x-padiem-device-binding-ref"
DEVICE_SESSION_CREDENTIAL_HEADER = "x-padiem-device-credential-b64"

# Mirrors the canonical safe-reference grammar and the device credential bound:
# a 16 KiB raw credential is 21 848 base64 characters, so anything larger is
# refused before the authority is ever called.
_SAFE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_MAX_CREDENTIAL_B64_CHARS = ((16_384 + 2) // 3) * 4
_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")

DESKTOP_DEVICE_SESSION_AUTH_FAILED = "device_session_auth_required"
DESKTOP_AUTHORITY_UNCONFIGURED = "desktop_conversation_authority_unconfigured"

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

_NOT_FOUND_BODY = {"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _unauthorized() -> JSONResponse:
    """The one uniform authentication refusal. No deny reason is disclosed."""

    return _error(
        401,
        DESKTOP_DEVICE_SESSION_AUTH_FAILED,
        "Desktop device session authentication is required.",
    )


def _authority_unavailable() -> JSONResponse:
    return _error(
        503,
        DESKTOP_AUTHORITY_UNCONFIGURED,
        "Desktop conversation access is currently unavailable.",
    )


def _history_unavailable() -> JSONResponse:
    return _error(
        503,
        "history_unavailable",
        "저장된 대화를 현재 사용할 수 없습니다.",
    )


def _device_session_material(request: Request) -> tuple[str, str, str] | None:
    """The closed caller-held session material, or ``None``.

    Reads exactly the three closed headers under exactly the canonical shapes.
    The material is validated here so a malformed caller cannot reach the
    trusted authority at all, and it is never stored or logged afterwards.
    """

    session_id = request.headers.get(DEVICE_SESSION_ID_HEADER)
    binding_ref = request.headers.get(DEVICE_SESSION_BINDING_REF_HEADER)
    credential_b64 = request.headers.get(DEVICE_SESSION_CREDENTIAL_HEADER)
    if not isinstance(session_id, str) or not _SAFE_REF_PATTERN.fullmatch(session_id):
        return None
    if not isinstance(binding_ref, str) or not _SAFE_REF_PATTERN.fullmatch(binding_ref):
        return None
    if (
        not isinstance(credential_b64, str)
        or not credential_b64
        or len(credential_b64) > _MAX_CREDENTIAL_B64_CHARS
        or not _BASE64_PATTERN.fullmatch(credential_b64)
    ):
        return None
    return session_id, binding_ref, credential_b64


async def _authenticate_request(request: Request) -> tuple[str | None, JSONResponse | None]:
    """Authenticate one Desktop request against the canonical broker session.

    Returns ``(account_ref, None)`` on success — with the owner derived by the
    trusted authority from the verified canonical binding state, never from
    request content — or ``(None, response)`` with the one uniform refusal:
    503 while the trusted composition is absent, 401 for every authentication
    failure, with no deny reason ever distinguished.
    """

    authority: DesktopDeviceSessionAuthority = getattr(
        request.app.state,
        "desktop_device_session_authority",
        None,
    ) or UnconfiguredDesktopDeviceSessionAuthority()
    if getattr(authority, "configured", True) is False:
        return None, _authority_unavailable()
    material = _device_session_material(request)
    if material is None:
        return None, _unauthorized()
    session_id, binding_ref, credential_b64 = material
    try:
        projection = await authority.authenticate_device_session(
            session_id=session_id,
            binding_ref=binding_ref,
            credential_b64=credential_b64,
        )
    except Exception:
        return None, _unauthorized()
    if not isinstance(projection, dict) or projection.get("authenticated") is not True:
        return None, _unauthorized()
    account_ref = projection.get("account_ref")
    if not isinstance(account_ref, str) or not _SAFE_REF_PATTERN.fullmatch(account_ref):
        return None, _unauthorized()
    return account_ref, None


async def desktop_conversations(request: Request) -> JSONResponse:
    """List the owner's canonical conversations. GET only, owner-derived, no-store."""

    account_ref, refusal = await _authenticate_request(request)
    if refusal is not None:
        return refusal
    store: HistoryStore | None = request.app.state.history_store
    if store is None:
        return _history_unavailable()
    try:
        conversations = await store.list_conversations(account_ref)
    except Exception:
        return _history_unavailable()
    return JSONResponse(
        {"conversations": conversations},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def desktop_conversation_detail(request: Request) -> JSONResponse:
    """Read one canonical conversation. GET only, non-disclosing, no-store.

    The id grammar is validated before the authority or the store is touched:
    a malformed id can never disclose whether any lookup happened.
    """

    try:
        cid = validate_conversation_id(request.path_params.get("conversation_id"))
    except ValueError:
        cid = None
    if cid is None:
        return JSONResponse(_NOT_FOUND_BODY, status_code=404, headers=_NO_STORE_HEADERS)

    account_ref, refusal = await _authenticate_request(request)
    if refusal is not None:
        return refusal
    store: HistoryStore | None = request.app.state.history_store
    if store is None:
        return _history_unavailable()
    try:
        conversation = await store.get_conversation(account_ref, cid)
    except Exception:
        return _history_unavailable()
    if conversation is None:
        # Same answer for a foreign id and an unknown one: existence in
        # another owner's history is never disclosed.
        return JSONResponse(_NOT_FOUND_BODY, status_code=404, headers=_NO_STORE_HEADERS)
    return JSONResponse(
        {"conversation": conversation},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


# ---------------------------------------------------------------------------
# Contract markers
# ---------------------------------------------------------------------------

READ_LIST = "YES"
READ_DETAIL = "YES"
CREATE = 0
DELETE = 0
CHAT_WRITE = 0
COMPOSER = 0
MUTATION = False
PRODUCTION_MUTATION = False
SECOND_IDENTITY_AUTHORITY = 0
SECOND_SESSION_AUTHORITY = 0
SECOND_CREDENTIAL_VERIFIER = 0
SECOND_CONVERSATION_AUTHORITY = 0
BROWSER_PADIEM_SESSION_COOKIE_COPY = 0
DESKTOP_USER_SESSION_AUTHORITY = 0
CALLER_WORKSPACE_AUTHORITY = 0
SERVER_DERIVED_ACCOUNT_REF = True
SERVER_DERIVED_WORKSPACE_REF = True
HISTORY_STORE_REUSED = True
NEW_CONVERSATION_DATABASE = 0
HISTORY_STORE_WORKSPACE_DIMENSION = "owner_wide"
RAW_DEVICE_CREDENTIAL_RETURNED = False
RAW_DEVICE_CREDENTIAL_LOGGED = False
DESKTOP_DELETE_ENDPOINT_PRESENT = 0
DESKTOP_CREATE_ENDPOINT_PRESENT = 0
