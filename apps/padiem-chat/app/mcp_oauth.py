"""MCP OAuth 2.1 authorization server hosted by Chat.

The user authentication remains the existing Chat common login session. This
module adds only the MCP-wide authorization endpoints, short-lived access
tokens and rotating refresh tokens; it does not create a second Google login
or touch padiem-auth keys.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

from padiem_ai_core.pc_device_identity import is_pc_device_id
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .auth_routes import current_user_id
from .mcp_device_selection import McpDeviceRefusal, owner_devices, owner_linked_ids
from .mcp_gateway_store import McpGatewayStoreError
from .mcp_oauth_metadata import (
    AUTHORIZATION_SERVER_METADATA_PATH,
    AUTHORIZE_INFO_PATH,
    AUTHORIZE_PATH,
    MCP_OAUTH_SCOPE,
    PROTECTED_RESOURCE_METADATA_PATH,
    REGISTER_PATH,
    REVOKE_PATH,
    TOKEN_PATH,
    canonical_resource,
    issuer,
    normalize_resource,
)
from .mcp_oauth_metadata import (
    authorization_server_metadata as _as_metadata_document,
)
from .mcp_oauth_metadata import (
    protected_resource_metadata as _prm_document,
)
from .same_origin_guard import expected_browser_origin

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_CONSENT_FILE = STATIC_DIR / "mcp-oauth-consent.html"
_NO_STORE = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_PKCE_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_PKCE_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}\Z")
_CLIENT_ID = re.compile(r"mcpc_[0-9a-f]{32}\Z")
_ALLOWED_AUTH_METHODS = {"none", "client_secret_post", "client_secret_basic"}
_ALLOWED_GRANTS = {"authorization_code", "refresh_token"}
_MAX_BODY = 16_384
_MAX_REDIRECT_URI = 2_048
_MAX_STATE = 1_024
_MAX_CLIENT_NAME = 100
_OAUTH_CORS_ORIGINS = frozenset({
    "https://chatgpt.com",
    "https://claude.ai",
})
_OAUTH_CORS_HEADERS = frozenset({"authorization", "content-type"})

_LOG = logging.getLogger(__name__)


def _cors_origin_header(request, *, methods, preflight=False):
    origin = request.headers.get("origin", "").strip()
    if origin not in _OAUTH_CORS_ORIGINS:
        return None
    headers = {
        "Access-Control-Allow-Origin": origin,
        "Vary": "Origin, Access-Control-Request-Method, Access-Control-Request-Headers"
        if preflight else "Origin",
    }
    if preflight:
        requested_method = request.headers.get("access-control-request-method", "").upper()
        requested_headers = {
            value.strip().lower()
            for value in request.headers.get("access-control-request-headers", "").split(",")
            if value.strip()
        }
        if requested_method not in methods or not requested_headers <= _OAUTH_CORS_HEADERS:
            return None
        headers["Access-Control-Allow-Methods"] = ", ".join((*sorted(methods), "OPTIONS"))
        if requested_headers:
            headers["Access-Control-Allow-Headers"] = ", ".join(sorted(requested_headers))
    return headers


def _cors_endpoint(handler, *, methods):
    async def endpoint(request):
        if request.method == "OPTIONS":
            headers = _cors_origin_header(request, methods=methods, preflight=True)
            if headers is None:
                return Response(status_code=403, headers=_NO_STORE)
            return Response(status_code=204, headers={**_NO_STORE, **headers})
        response = await handler(request)
        headers = _cors_origin_header(request, methods=methods)
        if headers is not None:
            response.headers.update(headers)
        return response
    return endpoint


def _json(body, status=200, headers=None):
    return JSONResponse(body, status_code=status, headers={**_NO_STORE, **(headers or {})})


def _oauth_error(status, code, description=None, headers=None):
    body = {"error": code}
    if description:
        body["error_description"] = description
    return _json(body, status, headers)


def _settings(request):
    return getattr(request.app.state, "settings", None)


def _store(request):
    return getattr(request.app.state, "mcp_gateway_store", None)


def _origin_ok(request):
    expected = expected_browser_origin(_settings(request))
    if expected is None:
        return False
    return request.headers.get("origin", "").strip() == expected


async def _read_json(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return None
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def _read_form(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
        return None
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        return None
    try:
        pairs = parse_qsl(raw.decode("utf-8"), keep_blank_values=True, strict_parsing=False)
    except (UnicodeDecodeError, ValueError):
        return None
    result = {}
    for key, value in pairs:
        if key in result:
            return None
        result[key] = value
    return result


def _safe_client_name(value):
    if value is None:
        return "MCP OAuth Client"
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (not value or len(value) > _MAX_CLIENT_NAME
            or any(ord(char) < 32 for char in value)
            or any(0x202A <= ord(char) <= 0x202E or 0x2066 <= ord(char) <= 0x2069
                   or ord(char) in {0x200B, 0x200C, 0x200D, 0xFEFF} for char in value)):
        return None
    return value


def _valid_redirect_uri(value):
    if not isinstance(value, str) or not value or len(value) > _MAX_REDIRECT_URI:
        return False
    if any(ord(char) < 32 for char in value):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.fragment or parsed.username is not None or parsed.password is not None:
        return False
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.hostname:
        return False
    if parsed.scheme.lower() == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return False
    try:
        _ = parsed.port
    except ValueError:
        return False
    return True


def _normalize_scope(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return MCP_OAUTH_SCOPE, None
    if not isinstance(value, str) or len(value) > 200 or any(ord(char) < 32 for char in value):
        return None, _oauth_error(400, "invalid_scope")
    parts = list(dict.fromkeys(value.split()))
    if not parts or any(part != MCP_OAUTH_SCOPE for part in parts):
        return None, _oauth_error(400, "invalid_scope")
    return " ".join(parts), None


def _normalize_state(value):
    if value is None or value == "":
        return ""
    if (not isinstance(value, str) or len(value) > _MAX_STATE
            or any(ord(char) < 32 for char in value)):
        return None
    return value


def _register_error(code):
    return _oauth_error(400, "invalid_client_metadata", code)


async def _client_auth(request, form):
    """Authenticate a registered OAuth client from Basic or form credentials."""
    client_id = form.get("client_id")
    client_secret = form.get("client_secret")
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None, _oauth_error(401, "invalid_client")
        basic_id, separator, basic_secret = decoded.partition(":")
        if not separator:
            return None, _oauth_error(401, "invalid_client")
        basic_id, basic_secret = unquote_plus(basic_id), unquote_plus(basic_secret)
        if client_id and client_id != basic_id:
            return None, _oauth_error(401, "invalid_client")
        client_id, client_secret = basic_id, basic_secret
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        return None, _oauth_error(401, "invalid_client")
    store = _store(request)
    if store is None:
        return None, _oauth_error(503, "temporarily_unavailable")
    client = await store.get_oauth_client(client_id)
    if client is None:
        return None, _oauth_error(401, "invalid_client")
    method = client.get("token_endpoint_auth_method")
    if method not in _ALLOWED_AUTH_METHODS:
        return None, _oauth_error(401, "invalid_client")
    if method != "none":
        expected = client.get("client_secret_sha256")
        if (not isinstance(client_secret, str) or not client_secret
                or not isinstance(expected, str)
                or not hmac.compare_digest(expected, hashlib.sha256(client_secret.encode()).hexdigest())):
            return None, _oauth_error(401, "invalid_client")
    try:
        await store.touch_oauth_client(client_id)
    except Exception:
        pass
    return client, None


async def _authorize_request(request, values):
    """Validate one authorization request before any redirect is trusted."""
    settings = _settings(request)
    if (issuer(settings) is None or canonical_resource(settings) is None):
        return None, _oauth_error(503, "temporarily_unavailable")
    client_id = values.get("client_id")
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        return None, _oauth_error(400, "invalid_request", "client_id is invalid")
    store = _store(request)
    if store is None:
        return None, _oauth_error(503, "temporarily_unavailable")
    client = await store.get_oauth_client(client_id)
    if client is None:
        return None, _oauth_error(400, "invalid_client", "unknown client")
    if values.get("response_type") != "code":
        return None, _oauth_error(400, "unsupported_response_type")
    redirect_uri = values.get("redirect_uri")
    if not isinstance(redirect_uri, str) or redirect_uri not in client["redirect_uris"]:
        return None, _oauth_error(400, "invalid_request", "redirect_uri is not registered")
    challenge = values.get("code_challenge")
    if (not isinstance(challenge, str) or not _PKCE_CHALLENGE.fullmatch(challenge)
            or values.get("code_challenge_method") != "S256"):
        return None, _oauth_error(400, "invalid_request", "PKCE S256 is required")
    resource = normalize_resource(values.get("resource"), settings)
    if resource is None:
        return None, _oauth_error(400, "invalid_target", "resource is invalid")
    scope, scope_error = _normalize_scope(values.get("scope"))
    if scope_error is not None:
        return None, scope_error
    state = _normalize_state(values.get("state"))
    if state is None:
        return None, _oauth_error(400, "invalid_request", "state is invalid")
    return {
        "client": client, "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "resource": resource, "scope": scope, "state": state,
    }, None


def _redirect_with(redirect_uri, **params):
    parsed = urlsplit(redirect_uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, str(value)) for key, value in params.items() if value is not None)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _authorize_url(request):
    path = AUTHORIZE_PATH if request.url.path == AUTHORIZE_INFO_PATH else request.url.path
    query = request.url.query
    return path + (("?" + query) if query else "")


def _consent_page():
    return FileResponse(str(_CONSENT_FILE), media_type="text/html; charset=utf-8", headers=_NO_STORE)


async def protected_resource_metadata(request):
    settings = _settings(request)
    document = _prm_document(settings)
    if not document.get("resource") or not document.get("authorization_servers"):
        return _oauth_error(503, "temporarily_unavailable")
    return _json(document)


async def authorization_server_metadata(request):
    settings = _settings(request)
    document = _as_metadata_document(settings)
    if not document.get("issuer"):
        return _oauth_error(503, "temporarily_unavailable")
    return _json(document)


async def authorize_get(request):
    values = {key: request.query_params.get(key) for key in (
        "response_type", "client_id", "redirect_uri", "code_challenge",
        "code_challenge_method", "resource", "scope", "state",
    )}
    validated, error = await _authorize_request(request, values)
    if error is not None:
        return error
    user_id = current_user_id(request)
    if not user_id:
        if getattr(request.app.state, "shared_login_flow", None) is not None:
            from .shared_login_flow import set_login_return_cookie
            response = RedirectResponse("/auth/shared/start", status_code=302, headers=_NO_STORE)
            set_login_return_cookie(response, _authorize_url(request))
            return response
    return _consent_page()


async def authorize_info(request):
    values = {key: request.query_params.get(key) for key in (
        "response_type", "client_id", "redirect_uri", "code_challenge",
        "code_challenge_method", "resource", "scope", "state",
    )}
    validated, error = await _authorize_request(request, values)
    if error is not None:
        return error
    user_id = current_user_id(request)
    if not user_id:
        return _oauth_error(401, "login_required", headers={
            "X-MCP-Login-Url": _authorize_url(request) if getattr(
                request.app.state, "shared_login_flow", None) is not None else "/",
        })
    # The list is the MCP device directory itself, answered by the same
    # function ``pc_devices`` uses, for the owner id the MCP lanes resolve from
    # this session. A directory that cannot be read is an error, never an empty
    # list: "no PC connected" has to mean that.
    try:
        _owner_id, devices = await _link_directory(request, user_id)
    except McpDeviceRefusal as refusal:
        _LOG.warning("mcp_oauth_device_directory_unavailable reason=%s owner=%s",
                     refusal.code, hashlib.sha256(user_id.encode()).hexdigest()[:8])
        return _json({"error": refusal.code, "error_description": refusal.message}, 503)
    return _json({
        "client_name": validated["client"]["client_name"],
        "account": await _account_summary(request, user_id),
        "switch_account_url": _switch_account_url(request),
        "redirect_uri": validated["redirect_uri"],
        "scope": validated["scope"], "resource": validated["resource"],
        "issuer": issuer(_settings(request)),
        "pcs": [{
            "device_id": item["device_id"],
            "label": item["name"] or item["id6"],
            "name": item["name"],
            "id6": item["id6"],
            "online": item["online"],
        } for item in devices],
    })


async def authorize_post(request):
    if not _origin_ok(request):
        return _oauth_error(403, "origin_rejected")
    values = await _read_json(request)
    if values is None:
        return _oauth_error(400, "invalid_request")
    validated, error = await _authorize_request(request, values)
    if error is not None:
        return error
    user_id = current_user_id(request)
    if not user_id:
        return _oauth_error(401, "login_required")
    decision = values.get("decision")
    if decision not in {"approve", "deny"}:
        return _oauth_error(400, "invalid_request", "decision is invalid")
    settings = _settings(request)
    if decision == "deny":
        return _json({"redirect_url": _redirect_with(
            validated["redirect_uri"], error="access_denied",
            state=validated["state"] or None, iss=issuer(settings))})
    device_id = values.get("device_id")
    if not is_pc_device_id(device_id):
        return _oauth_error(403, "pc_device_unavailable")
    try:
        owner_id, linked_ids = await _link_ids(request, user_id)
    except McpDeviceRefusal:
        return _oauth_error(503, "temporarily_unavailable")
    if device_id not in linked_ids:
        return _oauth_error(403, "pc_device_unavailable")
    # 2026-11-04: the consent chooses the token's device scope. Default is
    # "all my PCs"; "selected" narrows the token to the PCs checked here. The
    # default PC must always be inside the chosen set so a device-less call
    # keeps working. Absent payload fields read as the default.
    device_scope = values.get("device_scope")
    if device_scope is None:
        device_scope = "all"
    if device_scope not in {"all", "selected"}:
        return _oauth_error(400, "invalid_request", "device_scope is invalid")
    device_scope_json = None
    if device_scope == "selected":
        chosen = values.get("device_ids")
        if (not isinstance(chosen, list) or not chosen
                or len(chosen) > 20
                or any(item not in linked_ids for item in chosen)):
            return _oauth_error(403, "pc_device_unavailable")
        if device_id not in chosen:
            chosen.append(device_id)
        seen: list[str] = []
        for item in chosen:
            if item not in seen:
                seen.append(item)
        device_scope_json = json.dumps(seen)
    store = _store(request)
    try:
        code = await store.create_oauth_code(
            client_id=validated["client_id"], user_id=owner_id, device_id=device_id,
            redirect_uri=validated["redirect_uri"], code_challenge=validated["code_challenge"],
            scope=validated["scope"], resource=validated["resource"],
            device_scope=device_scope, device_scope_json=device_scope_json)
    except McpGatewayStoreError:
        return _oauth_error(400, "invalid_request")
    except Exception:
        return _oauth_error(503, "temporarily_unavailable")
    return _json({"redirect_url": _redirect_with(
        validated["redirect_uri"], code=code,
        state=validated["state"] or None, iss=issuer(settings))})


async def register_client(request):
    values = await _read_json(request)
    if values is None:
        return _oauth_error(400, "invalid_client_metadata")
    redirect_uris = values.get("redirect_uris")
    if (not isinstance(redirect_uris, list) or not 1 <= len(redirect_uris) <= 10
            or not all(_valid_redirect_uri(uri) for uri in redirect_uris)):
        return _register_error("redirect_uris are invalid")
    client_name = _safe_client_name(values.get("client_name"))
    if client_name is None:
        return _register_error("client_name is invalid")
    method = values.get("token_endpoint_auth_method", "none")
    if method not in _ALLOWED_AUTH_METHODS:
        return _register_error("token_endpoint_auth_method is unsupported")
    grant_types = values.get("grant_types", ["authorization_code", "refresh_token"])
    if (not isinstance(grant_types, list) or not grant_types
            or not set(grant_types) <= _ALLOWED_GRANTS
            or "authorization_code" not in grant_types):
        return _register_error("grant_types are unsupported")
    response_types = values.get("response_types", ["code"])
    if not isinstance(response_types, list) or response_types != ["code"]:
        return _register_error("response_types are unsupported")
    scope, scope_error = _normalize_scope(values.get("scope"))
    if scope_error is not None:
        return _register_error("scope is unsupported")
    store = _store(request)
    if store is None:
        return _oauth_error(503, "temporarily_unavailable")
    try:
        registered = await store.register_oauth_client(
            client_name=client_name, redirect_uris=redirect_uris,
            token_endpoint_auth_method=method)
    except McpGatewayStoreError:
        return _register_error("client metadata is invalid")
    except Exception:
        return _oauth_error(503, "temporarily_unavailable")
    response = {
        "client_id": registered["client_id"],
        "client_name": registered["client_name"],
        "redirect_uris": registered["redirect_uris"],
        "token_endpoint_auth_method": registered["token_endpoint_auth_method"],
        "grant_types": grant_types,
        "response_types": response_types,
        "scope": scope,
        "client_id_issued_at": int(time.time()),
    }
    if registered.get("client_secret") is not None:
        response["client_secret"] = registered["client_secret"]
        response["client_secret_expires_at"] = 0
    return _json(response, 201)


SWITCH_ACCOUNT_PATH = "/oauth/switch-account"


def _hash8(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:8]


def _masked_email(email: str) -> str:
    """Enough of the address to recognise the account, never the whole one."""
    local, _, domain = email.partition("@")
    if not domain or not local:
        return ""
    return (local[:2] if len(local) > 2 else local[:1]) + "***@" + domain


async def _account_summary(request, user_id: str) -> dict:
    """The signed-in browser account, as the consent header may show it."""
    store = getattr(request.app.state, "history_store", None)
    get_user = getattr(store, "get_user", None)
    profile = None
    if callable(get_user):
        try:
            profile = await get_user(user_id)
        except Exception:
            profile = None
    name = str(getattr(profile, "display_name", "") or "").strip()
    email = _masked_email(str(getattr(profile, "email", "") or "").strip())
    return {"name": name, "email": email, "display": name or email}


def _switch_account_url(request) -> str:
    query = request.url.query
    target = AUTHORIZE_PATH + (("?" + query) if query else "")
    return SWITCH_ACCOUNT_PATH + "?" + urlencode({"next": target})


async def switch_account(request):
    """Sign out on this browser and come back to the same OAuth request.

    The consent screen offers this beside the account it names. Only a relative
    path under the authorize endpoint may be returned to, so the link cannot
    aim the browser anywhere else, and the OAuth request values (client, PKCE,
    state, scope) travel with it untouched.
    """
    target = request.query_params.get("next") or ""
    if (not isinstance(target, str) or not target.startswith(AUTHORIZE_PATH)
            or "\\" in target or target.startswith("//")):
        target = AUTHORIZE_PATH
    from .auth_routes import _revoke_canonical_session

    try:
        await _revoke_canonical_session(request)
    except Exception:
        pass
    response = RedirectResponse(target, status_code=302, headers=_NO_STORE)
    from .auth import SESSION_COOKIE

    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    try:
        from .shared_login_flow import clear_shared_cookies

        clear_shared_cookies(response)
    except Exception:
        pass
    return response


async def _converted_owner_id(request, user_id: str) -> str:
    """The owner id this session's PC links are keyed by.

    The MCP lanes already make this conversion: the canonical session is
    resolved the way ``chat_pc_drive._resolve_chat_owner`` does and the
    identity authority answers ``owner_subject_id`` for it. The consent screen
    reuses exactly that, so the PC a tool can reach and the PC the owner may
    approve are looked up for the same owner. When the conversion is
    unavailable the signed-in product id stands, which is what the screen used
    before this conversion existed.
    """
    from . import chat_pc_drive

    resolver = getattr(chat_pc_drive, "_resolve_chat_owner", None)
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(resolver) or not callable(getattr(identity, "resolve_connector_owner_scope", None)):
        return user_id
    try:
        session, _subject_id, _workspace_id = await resolver(request, user_id)
    except Exception:
        return user_id
    session_id = getattr(session, "session_id", None)
    if not isinstance(session_id, str) or not session_id:
        return user_id
    try:
        scope = await identity.resolve_connector_owner_scope(session_id=session_id)
    except Exception:
        return user_id
    owner_subject_id = scope.get("owner_subject_id") if isinstance(scope, dict) else None
    if not isinstance(owner_subject_id, str) or not owner_subject_id:
        return user_id
    if owner_subject_id == user_id:
        return owner_subject_id
    # 2026-11-04: the conversion must name *this* person. The owner axis and the
    # browser's product-user axis are different vocabularies, so comparing the
    # two strings would refuse every real conversion; the authority's own
    # reverse lookup answers which product user the resolved owner subject
    # belongs to. Anything but the signed-in user — including an answer we
    # cannot get — stays on the session's own id, so another account's PCs are
    # never listed or approved.
    from .auth_routes import PADIEM_CHAT_PRODUCT_ID

    resolve_product_user = getattr(identity, "resolve_product_user_for_subject", None)
    if not callable(resolve_product_user):
        _LOG.warning("mcp_oauth_owner_scope_unverified reason=lookup_unavailable owner=%s session_user=%s",
                     _hash8(owner_subject_id), _hash8(user_id))
        return user_id
    try:
        resolved_user = await resolve_product_user(
            product_id=PADIEM_CHAT_PRODUCT_ID, canonical_subject_id=owner_subject_id)
    except Exception:
        _LOG.warning("mcp_oauth_owner_scope_unverified reason=lookup_failed owner=%s session_user=%s",
                     _hash8(owner_subject_id), _hash8(user_id))
        return user_id
    if resolved_user != user_id:
        _LOG.warning("mcp_oauth_owner_scope_mismatch owner=%s session_user=%s",
                     _hash8(owner_subject_id), _hash8(user_id))
        return user_id
    return owner_subject_id


async def _link_directory(request, user_id: str):
    """(owner id, devices) for the consent list, on the links' own owner id."""
    owner_id = await _converted_owner_id(request, user_id)
    devices = await owner_devices(request, owner_id=owner_id)
    if not devices and owner_id != user_id:
        # A conversion that names an axis with no link rows must not turn a
        # linked account into "no PC": the session's own product id is the one
        # fallback, never a second owner.
        devices = await owner_devices(request, owner_id=user_id)
        if devices:
            return user_id, devices
    return owner_id, devices


async def _link_ids(request, user_id: str):
    """(owner id, active PC ids) for the consent choice, same owner id."""
    owner_id = await _converted_owner_id(request, user_id)
    ids = await owner_linked_ids(request, owner_id=owner_id)
    if not ids and owner_id != user_id:
        ids = await owner_linked_ids(request, owner_id=user_id)
        if ids:
            return user_id, ids
    return owner_id, ids


def _pkce_matches(verifier, challenge):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(computed, challenge)


async def token(request):
    form = await _read_form(request)
    if form is None:
        return _oauth_error(400, "invalid_request")
    client, error = await _client_auth(request, form)
    if error is not None:
        return error
    grant_type = form.get("grant_type")
    store = _store(request)
    if store is None:
        return _oauth_error(503, "temporarily_unavailable")
    if grant_type == "authorization_code":
        code = form.get("code")
        redirect_uri = form.get("redirect_uri")
        verifier = form.get("code_verifier")
        if (not isinstance(code, str) or not code
                or not isinstance(redirect_uri, str) or not redirect_uri
                or not isinstance(verifier, str) or not _PKCE_VERIFIER.fullmatch(verifier)):
            return _oauth_error(400, "invalid_request")
        try:
            consumed = await store.consume_oauth_code(
                code=code, client_id=client["client_id"], redirect_uri=redirect_uri)
        except Exception:
            return _oauth_error(503, "temporarily_unavailable")
        if consumed is None:
            return _oauth_error(400, "invalid_grant")
        if (consumed.get("code_challenge_method") != "S256"
                or not _pkce_matches(verifier, consumed.get("code_challenge") or "")):
            return _oauth_error(400, "invalid_grant")
        requested_resource = form.get("resource")
        if requested_resource:
            normalized = normalize_resource(requested_resource, _settings(request))
            if normalized is None or normalized != consumed.get("resource"):
                return _oauth_error(400, "invalid_target")
        try:
            issued = await store.issue_oauth_tokens(
                client_name=client["client_name"], client_id=client["client_id"],
                user_id=consumed["user_id"], device_id=consumed["device_id"],
                scope=consumed["scope"], resource=consumed["resource"],
                device_scope=consumed.get("device_scope"),
                device_scope_json=consumed.get("device_scope_json"))
        except Exception:
            return _oauth_error(503, "temporarily_unavailable")
        return _json(issued)
    if grant_type == "refresh_token":
        refresh_token = form.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            return _oauth_error(400, "invalid_request")
        try:
            issued = await store.refresh_oauth_tokens(
                refresh_token=refresh_token, client_id=client["client_id"])
        except Exception:
            return _oauth_error(503, "temporarily_unavailable")
        if issued is None:
            return _oauth_error(400, "invalid_grant")
        return _json(issued)
    return _oauth_error(400, "unsupported_grant_type")


async def revoke(request):
    form = await _read_form(request)
    if form is None:
        return _oauth_error(400, "invalid_request")
    client, error = await _client_auth(request, form)
    if error is not None:
        return error
    token_value = form.get("token")
    if not isinstance(token_value, str) or not token_value:
        return _oauth_error(400, "invalid_request")
    store = _store(request)
    if store is None:
        return _oauth_error(503, "temporarily_unavailable")
    try:
        await store.revoke_oauth_token(token=token_value, client_id=client["client_id"])
    except Exception:
        return _oauth_error(503, "temporarily_unavailable")
    return _json({})


def mcp_oauth_routes():
    metadata = _cors_endpoint(protected_resource_metadata, methods={"GET"})
    server_metadata = _cors_endpoint(authorization_server_metadata, methods={"GET"})
    token_endpoint = _cors_endpoint(token, methods={"POST"})
    register_endpoint = _cors_endpoint(register_client, methods={"POST"})
    revoke_endpoint = _cors_endpoint(revoke, methods={"POST"})
    return [
        Route(PROTECTED_RESOURCE_METADATA_PATH, metadata, methods=["GET", "OPTIONS"]),
        Route(PROTECTED_RESOURCE_METADATA_PATH + "/api/mcp", metadata, methods=["GET", "OPTIONS"]),
        Route(AUTHORIZATION_SERVER_METADATA_PATH, server_metadata, methods=["GET", "OPTIONS"]),
        Route(AUTHORIZE_INFO_PATH, authorize_info, methods=["GET"]),
        Route(SWITCH_ACCOUNT_PATH, switch_account, methods=["GET"]),
        Route(AUTHORIZE_PATH, authorize_get, methods=["GET"]),
        Route(AUTHORIZE_PATH, authorize_post, methods=["POST"]),
        Route(TOKEN_PATH, token_endpoint, methods=["POST", "OPTIONS"]),
        Route(REGISTER_PATH, register_endpoint, methods=["POST", "OPTIONS"]),
        Route(REVOKE_PATH, revoke_endpoint, methods=["POST", "OPTIONS"]),
    ]


__all__ = [
    "AUTHORIZATION_SERVER_METADATA_PATH", "AUTHORIZE_INFO_PATH", "AUTHORIZE_PATH",
    "PROTECTED_RESOURCE_METADATA_PATH", "REGISTER_PATH", "REVOKE_PATH", "TOKEN_PATH",
    "SWITCH_ACCOUNT_PATH", "authorize_get", "authorize_info", "authorize_post",
    "mcp_oauth_routes", "switch_account",
    "protected_resource_metadata", "register_client", "revoke", "token",
]
