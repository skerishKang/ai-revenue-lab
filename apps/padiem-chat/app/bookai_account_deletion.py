"""BookAI's signed entry into the existing all-service withdrawal engine."""
from __future__ import annotations

import json
import re
import time

from starlette.responses import JSONResponse
from starlette.routing import Route

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .com2_hmac import signature_matches, signature_time_error
from .password_rpc import _consume_service_id

DELETE_PATH = "/api/bookai/account/shared-delete"
_SUBJECT = re.compile(r"sub_[A-Za-z0-9_-]{1,128}")
_REQUEST_ID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}")


def _error(status, code):
    return JSONResponse({"error": code}, status_code=status,
                        headers={"cache-control": "private, no-store"})


async def resolve_bookai_user(request, subject):
    """Use authority links, never a BookAI id as a Chat user id."""
    from .account_deletion import (
        _CHAT_PRODUCTS, _active_product_links, _account_link_subjects,
        _shadow_canonical_subject, bookai_subjects,
    )
    links = await _active_product_links(request, subject)
    if not links:
        raise ValueError("account_delete_unavailable")
    ids = {link["product_user_id"] for link in links if link["product_id"] in _CHAT_PRODUCTS}
    if len(ids) > 1:
        raise ValueError("account_delete_unavailable")
    if not ids:
        return None, None
    user_id = ids.pop()
    db = request.app.state.account_data_db
    row = await db.prepare("SELECT email, provider_subject FROM users WHERE id = ?").bind(user_id).first()
    from .history import _row_to_dict
    row = _row_to_dict(row)
    if not row or not isinstance(row.get("email"), str) or not row["email"]:
        raise ValueError("account_delete_unavailable")
    shadow = await _shadow_canonical_subject(db, user_id)
    subjects = bookai_subjects(row.get("provider_subject"),
                              [*((shadow,) if shadow else ()), *await _account_link_subjects(db, user_id)])
    if subject not in subjects or any(candidate != subject for candidate in subjects):
        raise ValueError("account_delete_unavailable")
    return user_id, row


async def validate_removal(request, links, subject):
    """Old authorities reject the extra field before mutating any link."""
    authority = request.app.state.control_plane_identity_authority
    for link in links:
        result = await authority.remove_product_link(
            product_id=link["product_id"], product_user_id=link["product_user_id"],
            canonical_subject_id=subject, account_deletion_operation_id=None,
            validate_only=True,
        )
        if not isinstance(result, dict) or set(result) != {"ok", "removable"} or result.get("ok") is not True or result.get("removable") is not True:
            raise ValueError("account_delete_unavailable")


def install_bookai_account_deletion_route(app, *, env, clock=time.time):
    secret = env.get("BOOKAI_COM2_SYNC_SECRET", "")

    async def handle(request):
        if not isinstance(secret, str) or not secret:
            return _error(503, "account_delete_unavailable")
        if request.url.path != DELETE_PATH or request.scope.get("query_string"):
            return _error(400, "invalid_request")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return _error(415, "invalid_request")
        subject = request.headers.get("x-bookai-subject", "")
        timestamp = request.headers.get("x-bookai-timestamp", "")
        signature = request.headers.get("x-bookai-signature", "")
        now = clock()
        if not _SUBJECT.fullmatch(subject) or signature_time_error(timestamp, signature, now=now):
            return _error(401, "authentication_required")
        try:
            body = await read_bounded_request_body(request, max_bytes=2048)
        except RequestBodyTooLarge:
            return _error(413, "invalid_request")
        now = clock()
        if signature_time_error(timestamp, signature, now=now):
            return _error(401, "authentication_required")
        if not signature_matches(secret=secret, method="POST", path=DELETE_PATH,
                                 timestamp=timestamp, subject=subject, body=body, signature=signature):
            return _error(401, "authentication_required")
        try:
            data = json.loads(body)
            if not isinstance(data, dict) or set(data) != {"confirm", "session_id", "expires_at", "request_id"}:
                return _error(400, "invalid_request")
            if (data["confirm"] is not True or not isinstance(data["session_id"], str)
                    or not 1 <= len(data["session_id"]) <= 128
                    or type(data["expires_at"]) is not int or not now < data["expires_at"] <= now + 960
                    or not isinstance(data["request_id"], str) or not _REQUEST_ID.fullmatch(data["request_id"])):
                return _error(401, "authentication_required")
        except (ValueError, UnicodeError):
            return _error(400, "invalid_request")
        try:
            store = request.app.state.history_store
            if not await _consume_service_id(store, "bookai-delete:" + data["request_id"], int(timestamp)):
                return _error(409, "request_replayed")
            from .account_deletion import _account_delete
            response = await _account_delete(request, delete_all_services=True, bookai_subject_id=subject)
            if response.status_code != 200:
                code = "account_delete_admin_blocked" if response.status_code == 403 else "account_delete_unavailable"
                return _error(response.status_code if response.status_code in {401, 403} else 503, code)
            return response
        except Exception:
            # Never include upstream exceptions, signed bodies or identifiers.
            return _error(503, "account_delete_unavailable")

    app.router.routes.insert(0, Route(DELETE_PATH, handle, methods=["POST"]))
