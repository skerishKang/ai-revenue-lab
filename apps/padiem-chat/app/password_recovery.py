"""Signed Chat storage/mail ports for common-login email recovery (#7606).

Only padiem-auth decides whether a surviving common account is recoverable.
Chat reports local absence, owns the mailed proof and atomically restores its
credential. Ordinary registration and password verification stay unchanged.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import time
import uuid
from datetime import datetime, timezone

from starlette.responses import JSONResponse

from .auth_validation_cache import DENYLIST_TTL_SECONDS, _REVOKED_MARKER
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .history import _batch_returned_row, _password_user_id, _row_to_dict
from .password_auth import PasswordAuthError, hash_password_async, normalize_email, validate_password
from .password_reset import (
    PASSWORD_RESET_DAILY_REQUEST_LIMIT,
    PASSWORD_RESET_GLOBAL_DAILY_LIMIT,
    PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS,
    PASSWORD_RESET_TOKEN_BYTES,
    PASSWORD_RESET_TOKEN_TTL_SECONDS,
)
from .password_reset_delivery import RESET_MAIL_SUBJECT, build_reset_mail_text
from .password_rpc import _consume_service_id, _verify_service_proof

PREFIX = "/internal/password-recovery/"
RECOVERY_PATHS = tuple(PREFIX + action for action in ("status", "request", "inspect", "complete"))
_BODY_LIMIT = 4096
_ACCOUNT = re.compile(r"sub_[A-Za-z0-9_-]{1,128}")
_EPOCH = re.compile(r"[0-9][0-9T:.+\-Z]{9,39}")
_SOURCE = re.compile(r"(?:[A-Za-z0-9_-]{43}|[a-f0-9]{64})")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_RETENTION_SECONDS = 30 * 86400
_LOG = logging.getLogger(__name__)
_ABSENT = (
    "NOT EXISTS (SELECT 1 FROM users WHERE lower(email)=lower(?)) "
    "AND NOT EXISTS (SELECT 1 FROM password_credentials WHERE username=? COLLATE NOCASE) "
    "AND NOT EXISTS (SELECT 1 FROM users WHERE id=?) "
    "AND NOT EXISTS (SELECT 1 FROM password_credentials WHERE user_id=?)"
)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status,
                        headers={"cache-control": "no-store"})


def _invalid() -> JSONResponse:
    return _error(400, "password_recovery_invalid", "복구 링크가 올바르지 않거나 더 이상 유효하지 않습니다.")


def _answer(value: dict) -> JSONResponse:
    return JSONResponse(value, headers={"cache-control": "no-store"})


def _digest(pepper: str, domain: str, value: str) -> str:
    return hmac.new(pepper.encode(), ("padiem-email-recovery:" + domain + ":v1\0" + value).encode(), hashlib.sha256).hexdigest()


def _target(account, epoch) -> bool:
    if not isinstance(account, str) or not _ACCOUNT.fullmatch(account):
        return False
    if not isinstance(epoch, str) or not _EPOCH.fullmatch(epoch):
        return False
    try:
        return datetime.fromisoformat(epoch.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _clock(request) -> int:
    # Injection stays on app state, never in an HTTP request.
    clock = getattr(request.app.state, "password_recovery_clock", time.time)
    return int(clock())


async def _available(db, email: str) -> bool:
    user_id = _password_user_id(email)
    return await db.prepare("SELECT 1 AS available WHERE " + _ABSENT).bind(
        email, email, user_id, user_id,
    ).first() is not None


async def is_recovered_password_user(db, user_id: str, *, account_id: str | None = None) -> bool:
    """Read durable consumed-proof provenance of this exact live credential.

    This identifies a restored local account; it grants no role or session.
    The proof survives token expiry but is removed when that user is deleted.
    A pre-114 database has no such provenance and retains the old refusal.
    """
    if not isinstance(user_id, str) or not re.fullmatch(r"usr_[0-9a-f]{32}", user_id):
        return False
    if account_id is not None and (not isinstance(account_id, str) or not _ACCOUNT.fullmatch(account_id)):
        return False
    sql = (
        "SELECT r.user_id FROM password_recovery_tokens r "
        "JOIN password_credentials c ON c.user_id=r.user_id JOIN users u ON u.id=r.user_id "
        "WHERE r.user_id=? AND r.email=c.username AND lower(r.email)=lower(u.email) "
        "AND r.credential_epoch=c.created_at AND r.consumed_at IS NOT NULL"
    )
    values = [user_id]
    if account_id is not None:
        sql += " AND r.account_id=?"
        values.append(account_id)
    try:
        return await db.prepare(sql + " LIMIT 1").bind(*values).first() is not None
    except Exception as exc:
        if "no such table" in str(exc).lower():
            return False
        raise


async def _request(request, db, pepper: str, payload: dict) -> JSONResponse:
    if set(payload) != {"email", "source_digest", "account_id", "credential_epoch"}:
        return _error(400, "invalid_request", "invalid request body")
    email = normalize_email(payload["email"])
    source = payload["source_digest"]
    if not isinstance(source, str) or not _SOURCE.fullmatch(source):
        return _error(400, "invalid_request", "invalid request body")
    account, epoch = payload["account_id"], payload["credential_epoch"]
    eligible = _target(account, epoch)
    if not eligible and (account is not None or epoch is not None):
        return _error(400, "invalid_request", "invalid request body")
    current = _clock(request)
    day_start = current // 86400 * 86400
    request_id = str(uuid.uuid4())
    email_digest = _digest(pepper, "email", email)
    raw_token = secrets.token_urlsafe(PASSWORD_RESET_TOKEN_BYTES)
    token_digest = _digest(pepper, "token", raw_token)
    # The common account survives; the withdrawn Chat identity does not.
    # A fresh local id prevents old sidless Chat cookies from becoming valid
    # again when this email's user row is restored, even if the switch is off.
    user_id = "usr_" + secrets.token_hex(16)
    # Admission and issuance share the same writer transaction. Unknown
    # identifiers spend the same budget. Refusals do not extend the cooldown.
    statements = [
        db.prepare("DELETE FROM password_recovery_requests WHERE issued_at<?").bind(current - _RETENTION_SECONDS),
        # A consumed row is the durable provenance of the fresh local identity,
        # not a usable token. Account deletion removes it with the user.
        db.prepare("DELETE FROM password_recovery_tokens WHERE consumed_at IS NULL AND expires_at<?").bind(current - _RETENTION_SECONDS),
        db.prepare(
            "INSERT INTO password_recovery_requests(request_id,identifier_digest,source_digest,issued_at) "
            "SELECT ?,?,?,? WHERE "
            "NOT EXISTS (SELECT 1 FROM password_recovery_requests WHERE identifier_digest=? AND issued_at>?) "
            "AND NOT EXISTS (SELECT 1 FROM password_recovery_requests WHERE source_digest=? AND issued_at>?) "
            "AND (SELECT COUNT(*) FROM password_recovery_requests WHERE identifier_digest=? AND issued_at>=?)<? "
            "AND (SELECT COUNT(*) FROM password_recovery_requests WHERE source_digest=? AND issued_at>=?)<? "
            "AND (SELECT COUNT(*) FROM password_recovery_requests WHERE issued_at>=?)<? RETURNING request_id"
        ).bind(request_id, email_digest, source, current,
               email_digest, current - PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS,
               source, current - PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS,
               email_digest, day_start, PASSWORD_RESET_DAILY_REQUEST_LIMIT,
               source, day_start, PASSWORD_RESET_DAILY_REQUEST_LIMIT,
               day_start, PASSWORD_RESET_GLOBAL_DAILY_LIMIT),
    ]
    if eligible:
        statements.append(db.prepare(
            "INSERT INTO password_recovery_tokens "
            "(token_digest,user_id,email,account_id,credential_epoch,issued_at,expires_at) "
            "SELECT ?,?,?,?,?,?,? WHERE EXISTS "
            "(SELECT 1 FROM password_recovery_requests WHERE request_id=?) AND " + _ABSENT + " RETURNING token_digest"
        ).bind(token_digest, user_id, email, account, epoch, current,
               current + PASSWORD_RESET_TOKEN_TTL_SECONDS, request_id, email, email, user_id, user_id))
    try:
        results = await db.batch(statements)
        issued = eligible and _batch_returned_row(results, 3) is not None
    except Exception:
        _LOG.warning("password_recovery reason=request_storage_failed")
        return _answer({"ok": True})
    if issued:
        delivery = getattr(request.app.state, "password_reset_delivery", None)
        try:
            link = "https://auth.padiem.net/password/recovery/confirm#token=" + raw_token
            sent = delivery is not None and await delivery.send(
                to=email, subject=RESET_MAIL_SUBJECT, text=build_reset_mail_text(link),
            )
            if not sent:
                _LOG.warning("password_recovery reason=delivery_failed")
        except Exception:
            _LOG.warning("password_recovery reason=delivery_failed")
    # Neither existence, admission, storage nor delivery changes this answer.
    return _answer({"ok": True})


async def _open(db, pepper: str, raw_token, current: int):
    if not isinstance(raw_token, str) or not _TOKEN.fullmatch(raw_token):
        return None
    return _row_to_dict(await db.prepare(
        "SELECT email,user_id,account_id,credential_epoch FROM password_recovery_tokens "
        "WHERE token_digest=? AND consumed_at IS NULL AND expires_at>?"
    ).bind(_digest(pepper, "token", raw_token), current).first())


def _restored_session_statements(db, *, token_digest: str, operation: str,
                                 user_id: str, account_id: str, current: int):
    """Restore access for a future fresh session without reviving old access.

    Withdrawal's hard delete marker overrides even a new session's allow row.
    Mail proof replaces it with ordinary credential-change markers, retaining
    its full deadline, and removes cached positive account decisions. Old
    user/session allow rows cannot authorize this fresh local user id.
    The same token-claim fence makes all these writes part of one completion.
    """
    claimed = "EXISTS (SELECT 1 FROM password_recovery_tokens WHERE token_digest=? AND consumed_by=?)"
    fence = (token_digest, operation)
    statements = [db.prepare(
        "DELETE FROM auth_validation_cache WHERE kind='shared' AND "
        "((owner_id='allow:sid' AND product_user_id=?) OR "
        "(owner_id NOT LIKE 'deny:%' AND owner_id NOT LIKE 'allow:%' "
        "AND (product_user_id=? OR owner_id=?))) AND " + claimed
    ).bind(user_id, user_id, account_id, *fence)]
    hashes = []
    for tag, identity in (("deny:usr", user_id), ("deny:acc", account_id)):
        digest = hashlib.sha256(identity.encode()).hexdigest()
        hashes.append(digest)
        statements.append(db.prepare(
            "INSERT INTO auth_validation_cache(kind,owner_id,session_hash,product_user_id,valid_until) "
            "SELECT 'shared',?,?,?,MAX(?,COALESCE((SELECT MAX(valid_until) FROM auth_validation_cache "
            "WHERE kind='shared' AND owner_id='deny:del' AND session_hash=?),0)) WHERE " + claimed +
            " ON CONFLICT(kind,owner_id,session_hash) DO UPDATE SET "
            "valid_until=MAX(auth_validation_cache.valid_until,excluded.valid_until),product_user_id=excluded.product_user_id"
        ).bind(tag, digest, _REVOKED_MARKER, current + DENYLIST_TTL_SECONDS, digest, *fence))
    statements.extend([
        db.prepare("DELETE FROM auth_validation_cache WHERE kind='shared' AND owner_id='deny:del' "
                   "AND session_hash IN (?,?) AND " + claimed).bind(*hashes, *fence),
        db.prepare("UPDATE auth_validation_cache_revision SET revision=revision+1 WHERE id=1 AND " + claimed).bind(*fence),
    ])
    return statements


async def _complete(request, db, pepper: str, payload: dict) -> JSONResponse:
    if set(payload) != {"token", "new_password", "account_id", "credential_epoch"}:
        return _invalid()
    current = _clock(request)
    row = await _open(db, pepper, payload["token"], current)
    if row is None or not _target(payload["account_id"], payload["credential_epoch"]) or (
        row["account_id"], row["credential_epoch"]
    ) != (payload["account_id"], payload["credential_epoch"]):
        return _invalid()
    password = validate_password(payload["new_password"], identifier=row["email"])
    encoded = await hash_password_async(password)
    current = _clock(request)  # hashing must not extend the token's deadline
    operation = str(uuid.uuid4())
    digest = _digest(pepper, "token", payload["token"])
    email, user_id = row["email"], row["user_id"]
    updated_at = datetime.fromtimestamp(current, timezone.utc).isoformat()
    display_name = email.partition("@")[0][:160]
    # This proof restores the SAME logical credential generation that auth
    # already binds. Only verified recovery preserves created_at; ordinary
    # registration still mints a new epoch and cannot rebind an old account.
    # Actual restoration time is consumed_at/updated_at. No auth epoch write
    # follows this commit, so a lost RPC answer cannot strand a new credential.
    results = await db.batch([
        db.prepare(
            "UPDATE password_recovery_tokens SET consumed_at=?,consumed_by=? "
            "WHERE token_digest=? AND consumed_at IS NULL AND expires_at>? "
            "AND account_id=? AND credential_epoch=? AND " + _ABSENT + " RETURNING user_id"
        ).bind(current, operation, digest, current, row["account_id"], row["credential_epoch"],
               email, email, user_id, user_id),
        db.prepare(
            "INSERT INTO users(id,auth_provider,provider_subject,email,display_name,picture_url,created_at,updated_at) "
            "SELECT ?,'google',?,?,?,'',?,? WHERE EXISTS "
            "(SELECT 1 FROM password_recovery_tokens WHERE token_digest=? AND consumed_by=?)"
        ).bind(user_id, "password:" + email, email, display_name, updated_at, updated_at, digest, operation),
        db.prepare(
            "INSERT INTO password_credentials(user_id,username,password_hash,failed_attempts,locked_until,created_at,updated_at) "
            "SELECT ?,?,?,0,NULL,?,? WHERE EXISTS "
            "(SELECT 1 FROM password_recovery_tokens WHERE token_digest=? AND consumed_by=?)"
        ).bind(user_id, email, encoded, row["credential_epoch"], updated_at, digest, operation),
        *_restored_session_statements(db, token_digest=digest, operation=operation,
                                      user_id=user_id, account_id=row["account_id"], current=current),
    ])
    if _batch_returned_row(results, 0) is None:
        return _invalid()
    return _answer({"ok": True, "product_user_id": user_id, "account_id": row["account_id"],
                    "credential_epoch": row["credential_epoch"]})


async def password_recovery_rpc(request) -> JSONResponse:
    settings = getattr(request.app.state, "settings", None)
    secret = getattr(settings, "password_rpc_secret", None)
    pepper = getattr(settings, "session_secret", None)
    store = getattr(request.app.state, "history_store", None)
    db = getattr(request.app.state, "account_data_db", None)
    if (getattr(settings, "email_recovery_enabled", False) is not True
            or request.url.path not in RECOVERY_PATHS or not isinstance(secret, str) or len(secret) < 32
            or not isinstance(pepper, str) or not pepper or store is None or db is None):
        return _error(404, "not_found", "not found")
    if request.method != "POST":
        return _error(405, "method_not_allowed", "method not allowed")
    try:
        body = await read_bounded_request_body(request, max_bytes=_BODY_LIMIT)
    except RequestBodyTooLarge:
        return _error(401, "unauthorized", "unauthorized")
    verified = _verify_service_proof(headers=request.headers, path=request.url.path, body=body,
                                     secret=secret, now_epoch=int(time.time()), max_body_bytes=_BODY_LIMIT)
    if verified is None:
        return _error(401, "unauthorized", "unauthorized")
    try:
        if not await _consume_service_id(store, verified["service_id"], verified["at"]):
            return _error(409, "rpc_replay_detected", "replayed service id")
        payload = verified["payload"]
        if not isinstance(payload, dict):
            return _error(400, "invalid_request", "invalid request body")
        action = request.url.path.removeprefix(PREFIX)
        if action == "request":
            return await _request(request, db, pepper, payload)
        if action == "status":
            if set(payload) != {"email"}:
                return _error(400, "invalid_request", "invalid request body")
            return _answer({"ok": True, "available": await _available(db, normalize_email(payload["email"]))})
        if action == "inspect":
            row = await _open(db, pepper, payload.get("token"), _clock(request)) if set(payload) in (
                {"token"}, {"token", "new_password"},
            ) else None
            # Auth checks policy before revoking sessions. Completion repeats
            # it before hashing; no password hash is created by this read port.
            if row is not None and "new_password" in payload:
                validate_password(payload["new_password"], identifier=row["email"])
            return _answer({"ok": True, "email": row["email"], "account_id": row["account_id"],
                            "credential_epoch": row["credential_epoch"]} if row else {"ok": False})
        return await _complete(request, db, pepper, payload)
    except PasswordAuthError as exc:
        return _error(400, exc.code, exc.message)
    except Exception:
        _LOG.warning("password_recovery reason=storage_failed")
        return _error(503, "password_recovery_unavailable", "지금은 복구를 완료할 수 없습니다. 잠시 후 다시 시도해 주세요.")
