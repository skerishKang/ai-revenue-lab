"""Internal password verification/registration RPC for padiem-auth.

The shared login (auth.padiem.net) email signup/login screens verify the
credential against THIS service. padiem-auth is the caller and signs each call
with the same v2 service-proof envelope the account-delete receiver verifies
(fresh UUID bound into the signature, ±300s clock window, JSON body, and the
receiver keeps every id for the window) over its own dedicated secret
``PADIEM_CHAT_PASSWORD_RPC_SECRET``:

    x-padiem-service-at:     <unix seconds>
    x-padiem-service-id:     <fresh random id, one per attempt>
    x-padiem-service-proof:  v2=<hex(hmac_sha256(secret,
        "v2\\nPOST\\n" + path + "\\n" + at + "\\n" + service_id + "\\n" + body))>

Verification reuses the one password authority — ``password_credentials`` via
``password_auth`` (PBKDF2-SHA512) — and applies the same server-owned lock
rules as ``/api/auth/password/login`` (5 failures → 15 minutes, escalated and
capped windows, lock state never disclosed). A successful response carries
nothing beyond the password account's product user id. Registration reuses
``register_password_user`` (the #5424 email-as-identifier contract); no second
credential store is created here.

The replay table is added through the normal D1/host migration path and holds
only bounded window-lifetime rows.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import (
    _PASSWORD_FAILURE_LIMIT,
    _decoy_failure_window,
    _display_name_fallback,
    _has_expired_lock,
    _identifier_failure_window,
    _is_locked,
    _password_lock_minutes,
)
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .history import HistoryConflict
from .password_auth import (
    PasswordAuthError,
    hash_password_async,
    normalize_display_name,
    normalize_login_identifier,
    normalize_email,
    normalize_username,
    validate_password,
    verify_password_async,
)

_LOG = logging.getLogger(__name__)

PASSWORD_VERIFY_PATH = "/internal/password-verify"
PASSWORD_REGISTER_PATH = "/internal/password-register"

_PROOF_AT_HEADER = "x-padiem-service-at"
_PROOF_ID_HEADER = "x-padiem-service-id"
_PROOF_HEADER = "x-padiem-service-proof"
_AT_RE = re.compile(r"(?:0|[1-9][0-9]{0,10})")
# The same shape bounds the account-delete receiver in padiem-auth worker.mjs.
_SERVICE_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_PROOF_RE = re.compile(r"v2=[a-f0-9]{64}")
_RPC_BODY_LIMIT = 512


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _verify_service_proof(*, headers, path: str, body: bytes, secret: str, now_epoch: int,
                          max_body_bytes: int | None = None) -> dict | None:
    """The exact receiver contract of padiem-auth's verifyAccountDeletionRpc.

    ``max_body_bytes`` lets a receiver with a larger payload contract (the
    voice STT RPC carries base64 audio) reuse this exact proof check without
    loosening the password RPC's own 512-byte bound. Default stays 512.
    """
    content_type = (headers.get("content-type") or "").split(";")[0].strip().lower()
    at_text = headers.get(_PROOF_AT_HEADER) or ""
    service_id = headers.get(_PROOF_ID_HEADER) or ""
    presented = headers.get(_PROOF_HEADER) or ""
    if content_type != "application/json" or not _AT_RE.fullmatch(at_text) or \
            not _SERVICE_ID_RE.fullmatch(service_id) or not _PROOF_RE.fullmatch(presented):
        return None
    at = int(at_text)
    if abs(now_epoch - at) > 300:
        return None
    if not body or len(body) > (_RPC_BODY_LIMIT if max_body_bytes is None else max_body_bytes):
        return None
    signed = b"\n".join((b"v2", b"POST", path.encode("utf-8"), at_text.encode("ascii"), service_id.encode("utf-8"), body))
    expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest("v2=" + expected, presented):
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return {"service_id": service_id, "payload": payload, "at": at}


async def _consume_service_id(store, service_id: str, at: int) -> bool:
    """Claim the caller's fresh id once — the receiver-side half of #6417.

    A v2 proof is only meaningful against a target that keeps every id for the
    clock window, so this receiver consumes ids durably too. The rows live at
    most one window past their ``at`` and are pruned on every claim. Storage
    access stays behind the history store's public interface.
    """
    expiry = datetime.fromtimestamp(at + 600, tz=timezone.utc).isoformat()
    return await store.consume_service_id(service_id, expiry)


async def password_verify_rpc(request: Request) -> JSONResponse:
    """POST /internal/password-verify — credential check, product user id only."""
    return await _password_rpc(request, path=PASSWORD_VERIFY_PATH, process=_verify_credentials)


async def password_register_rpc(request: Request) -> JSONResponse:
    """POST /internal/password-register — #5424 email signup, user id only."""
    return await _password_rpc(request, path=PASSWORD_REGISTER_PATH, process=_register_credentials)


async def _password_rpc(request: Request, *, path: str, process) -> JSONResponse:
    settings = getattr(request.app.state, "settings", None)
    secret = getattr(settings, "password_rpc_secret", None)
    store = getattr(request.app.state, "history_store", None)
    if not isinstance(secret, str) or len(secret) < 32 or store is None or \
            not callable(getattr(store, "find_password_credential", None)):
        return _error(404, "not_found", "not found")
    if request.url.path != path:
        return _error(404, "not_found", "not found")
    try:
        body = await read_bounded_request_body(request, max_bytes=_RPC_BODY_LIMIT)
    except RequestBodyTooLarge:
        return _error(401, "unauthorized", "unauthorized")
    verified = _verify_service_proof(
        headers=request.headers, path=path, body=body, secret=secret, now_epoch=int(time.time()),
    )
    if verified is None:
        return _error(401, "unauthorized", "unauthorized")
    try:
        if not await _consume_service_id(store, verified["service_id"], verified["at"]):
            return _error(409, "rpc_replay_detected", "replayed service id")
    except Exception as exc:
        _LOG.warning("password_rpc_store_error exception_type=%s", type(exc).__name__)
        return _error(503, "auth_storage_error", "verification store unavailable")
    payload = verified["payload"]
    if not isinstance(payload, dict):
        return _error(400, "invalid_request", "invalid request body")
    return await process(request, store, payload)


async def _verify_credentials(request: Request, store, payload: dict) -> JSONResponse:
    """The /api/auth/password/login core with identical lock accounting.

    Kept call-for-call parallel to ``password_login`` (both sides call the same
    primitives) so a change to the product lock rules cannot leave the shared
    login path behind.
    """
    if set(payload) != {"email", "password"}:
        return _error(400, "invalid_request", "invalid request body")
    identifier_raw = payload.get("email")
    password = payload.get("password")
    try:
        if not isinstance(identifier_raw, str):
            raise PasswordAuthError("invalid_credentials", "invalid")
        identifier = (
            normalize_email(identifier_raw)
            if "@" in identifier_raw
            else normalize_username(identifier_raw)
        )
    except PasswordAuthError:
        identifier = ""
    if not isinstance(password, str) or len(password) > 128:
        password = ""

    try:
        credential = await store.find_password_credential(identifier) if identifier else None
    except Exception as exc:
        _LOG.warning("password_verify_store_error exception_type=%s", type(exc).__name__)
        return _error(503, "auth_storage_error", "로그인 정보를 확인하지 못했습니다.")

    # Always execute the verifier, including for a missing identifier.
    password_ok = await verify_password_async(password, credential.password_hash if credential else None)
    now = datetime.now(timezone.utc)
    locked = credential is not None and _is_locked(credential, now)

    if credential is None or not password_ok or locked:
        if credential is not None and not locked:
            window = await _identifier_failure_window(request, identifier)
            # #7556: counted in the store, so concurrent failures are not lost.
            from .password_failure_count import record_failed_password_attempt

            lock_minutes = _password_lock_minutes(window.identifier_failures)
            try:
                await record_failed_password_attempt(
                    store,
                    credential,
                    limit=_PASSWORD_FAILURE_LIMIT,
                    lock_until_for=lambda: (now + timedelta(minutes=lock_minutes)).isoformat(),
                    lock_has_lapsed=_has_expired_lock(credential, now),
                )
            except Exception:
                pass
        else:
            await _decoy_failure_window(request)
        # The lock is server-owned and never disclosed, exactly like the
        # product login route: every failure class shares this projection.
        return _error(401, "invalid_credentials", "이메일 또는 비밀번호가 올바르지 않습니다.")

    try:
        await store.reset_password_failures(credential.user.id)
    except Exception:
        return _error(503, "auth_storage_error", "로그인 정보를 갱신하지 못했습니다.")
    return JSONResponse({"ok": True, "product_user_id": credential.user.id})


async def _register_credentials(request: Request, store, payload: dict) -> JSONResponse:
    if set(payload) != {"email", "password", "name"}:
        return _error(400, "invalid_request", "invalid request body")
    try:
        # The email address is the single login identifier (#5424); the stored
        # username column keeps holding it, unchanged from product signup.
        login_identifier = normalize_login_identifier(payload.get("email"))
        display_name = normalize_display_name(
            payload.get("name"), fallback=_display_name_fallback(login_identifier)
        )
        password = validate_password(payload.get("password"), identifier=login_identifier)
        encoded = await hash_password_async(password)
    except PasswordAuthError as exc:
        return _error(400, exc.code, exc.message)

    try:
        profile = await store.register_password_user(
            login_identifier, login_identifier, display_name, encoded,
        )
    except HistoryConflict:
        return _error(409, "account_exists", "이미 사용 중인 이메일입니다.")
    except Exception:
        return _error(503, "auth_storage_error", "회원가입 정보를 저장하지 못했습니다.")
    # No Chat session and no identity shadow here: the caller (padiem-auth)
    # resolves the canonical product link itself right after this response.
    return JSONResponse({"ok": True, "product_user_id": profile.id})
