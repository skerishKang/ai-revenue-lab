"""#5034 — Web Push opt-in for the EXISTING user web-alert inbox.

This module adds no inbox, no alert record, and no second notification
authority.  The user inbox stays exactly where it is: the existing
:class:`~app.claw_task_alert_store.D1ClawTaskAlertStore` and the existing
``/api/claw/inbox/{tasks,alerts}`` HTTP surface.  What is added here is the
*opt-in device subscription* and the delivery seam that distinguishes
"the web inbox persisted the record" from "the browser actually received a
push".

Reused, never recreated
-----------------------
* the signed-in owner authority (:func:`app.claw_memory_routes._require_owner`)
  and the server-owned workspace authority
  (:func:`app.claw_memory_routes._resolve_memory_workspace`) — the browser can
  name neither;
* the existing ``PADIEM_CHAT_DB`` D1 binding and the existing
  ``claw_task_alert`` inbox authority for the records themselves;
* the existing alert/task records: this module never writes, edits, completes
  or re-opens one.

Invariants
----------
* ``NO_SECOND_INBOX`` — no notification record is stored here, and the inbox
  read surface is untouched.
* ``INBOX_STATE_NEVER_CHANGED_BY_PUSH`` — a push failure (or a missing push
  authority) never changes the status of the underlying task or alert, and
  never re-executes the job that produced it.
* ``WEB_INBOX_SURVIVES_PUSH_DENIAL`` — a denied, unsupported or unconfigured
  push leaves the web inbox exactly as it was.
* ``SERVER_DERIVED_OWNER`` — workspace and member come from the session only.
* ``NO_ENDPOINT_IN_RESPONSE`` — the browser never receives an endpoint, a key
  or a secret back; only the subscription id, the scope and the timestamps.
* ``NO_ENDPOINT_IN_LOG`` — the endpoint is never written to a log or an error
  message.
* ``PUSH_AUTHORITY_OPTIONAL`` — with no push authority configured the seam
  reports ``not_configured`` instead of pretending a device was reached.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_memory_routes import _require_owner, _resolve_memory_workspace
from .workspace_storage import (
    WorkspaceStorageError,
    _row_to_dict,
    _utcnow,
)

PUSH_SUBSCRIPTION_PATH = "/api/claw/inbox/push/subscription"

MAX_PUSH_BODY_BYTES = 4096
MAX_ENDPOINT_CHARS = 2048
MAX_KEY_CHARS = 256
MAX_SCOPE_CHARS = 256
MAX_SUBSCRIPTIONS_PER_ACCOUNT = 20

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


class PushSubscriptionError(RuntimeError):
    """Fail-closed refusal for a push subscription request."""


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


def _bounded(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PushSubscriptionError("field must be a non-empty string")
    text = value.strip()
    if len(text) > limit:
        raise PushSubscriptionError("field is too long")
    return text


def subscription_id(endpoint: str) -> str:
    """A stable, non-reversible id for one device endpoint."""

    return "push_" + hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class PushSubscription:
    """One opted-in device endpoint. The endpoint itself never leaves the server."""

    subscription_id: str
    workspace_id: str
    member_id: str
    endpoint: str
    p256dh: str
    auth: str
    scope: str
    created_at: str
    updated_at: str

    def safe_dict(self) -> dict[str, str]:
        """The browser-facing projection. No endpoint, no key, no secret."""

        return {
            "subscription_id": self.subscription_id,
            "scope": self.scope,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class D1ClawPushSubscriptionStore:
    """Durable, owner-scoped Web Push subscriptions over the existing D1.

    The store holds device endpoints only.  It is not an alert database: the
    inbox records stay in the existing ``claw_task_alert`` authority.
    """

    def __init__(self, db: Any | None) -> None:
        if db is None:
            raise ValueError("D1 binding (PADIEM_CHAT_DB) is required")
        self.db = db

    def _stmt(self, sql: str, *values: Any) -> Any:
        stmt = self.db.prepare(sql)
        if values:
            stmt = stmt.bind(*values)
        return stmt

    async def _run(self, sql: str, *values: Any) -> Any:
        try:
            return await self._stmt(sql, *values).run()
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 write failed: {exc}") from exc

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        try:
            raw = await self._stmt(sql, *values).all()
        except Exception as exc:
            raise WorkspaceStorageError(f"D1 read failed: {exc}") from exc
        rows = raw if isinstance(raw, list) else list(raw)
        return [_row_to_dict(r) for r in rows]

    @staticmethod
    def _to_record(row: dict[str, Any]) -> PushSubscription:
        return PushSubscription(
            subscription_id=str(row.get("id") or ""),
            workspace_id=str(row.get("workspace_id") or ""),
            member_id=str(row.get("member_id") or ""),
            endpoint=str(row.get("endpoint") or ""),
            p256dh=str(row.get("p256dh") or ""),
            auth=str(row.get("auth") or ""),
            scope=str(row.get("scope") or ""),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )

    async def register(
        self,
        *,
        workspace_id: str,
        member_id: str,
        endpoint: str,
        p256dh: str,
        auth: str,
        scope: str,
        now: str,
    ) -> PushSubscription:
        """Register or update one device endpoint for this account.

        The same endpoint re-subscribed updates the existing row, so a retried
        subscribe never creates a second subscription.
        """

        now_text = now.isoformat() if hasattr(now, "isoformat") else str(now)
        existing = await self._all(
            "SELECT id, workspace_id, member_id, endpoint, p256dh, auth, scope, "
            "created_at, updated_at FROM claw_push_subscription "
            "WHERE workspace_id = ? AND member_id = ? AND endpoint = ?",
            workspace_id,
            member_id,
            endpoint,
        )
        if existing:
            row = existing[0]
            await self._run(
                "UPDATE claw_push_subscription SET p256dh = ?, auth = ?, scope = ?, "
                "updated_at = ? WHERE id = ?",
                p256dh,
                auth,
                scope,
                now_text,
                str(row.get("id")),
            )
            record = self._to_record({**row, "p256dh": p256dh, "auth": auth,
                                       "scope": scope, "updated_at": now_text})
            return record
        count = await self._all(
            "SELECT id FROM claw_push_subscription WHERE workspace_id = ? AND member_id = ?",
            workspace_id,
            member_id,
        )
        if len(count) >= MAX_SUBSCRIPTIONS_PER_ACCOUNT:
            raise PushSubscriptionError("too_many_subscriptions")
        new_id = subscription_id(endpoint)
        await self._run(
            "INSERT INTO claw_push_subscription "
            "(id, workspace_id, member_id, endpoint, p256dh, auth, scope, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            new_id,
            workspace_id,
            member_id,
            endpoint,
            p256dh,
            auth,
            scope,
            now_text,
            now_text,
        )
        return PushSubscription(
            subscription_id=new_id,
            workspace_id=workspace_id,
            member_id=member_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            scope=scope,
            created_at=now_text,
            updated_at=now_text,
        )

    async def unregister(
        self, *, workspace_id: str, member_id: str, subscription_id: str
    ) -> bool:
        """Remove one subscription of this account. Unknown ids are a no-op."""

        rows = await self._all(
            "SELECT id FROM claw_push_subscription "
            "WHERE workspace_id = ? AND member_id = ? AND id = ?",
            workspace_id,
            member_id,
            subscription_id,
        )
        if not rows:
            return False
        await self._run(
            "DELETE FROM claw_push_subscription WHERE id = ? AND workspace_id = ? AND member_id = ?",
            subscription_id,
            workspace_id,
            member_id,
        )
        return True

    async def list_for(
        self, *, workspace_id: str, member_id: str, scope: str | None = None
    ) -> list[PushSubscription]:
        if scope is None:
            rows = await self._all(
                "SELECT id, workspace_id, member_id, endpoint, p256dh, auth, scope, "
                "created_at, updated_at FROM claw_push_subscription "
                "WHERE workspace_id = ? AND member_id = ?",
                workspace_id,
                member_id,
            )
        else:
            rows = await self._all(
                "SELECT id, workspace_id, member_id, endpoint, p256dh, auth, scope, "
                "created_at, updated_at FROM claw_push_subscription "
                "WHERE workspace_id = ? AND member_id = ? AND scope = ?",
                workspace_id,
                member_id,
                scope,
            )
        return [self._to_record(row) for row in rows]


@dataclass(frozen=True, slots=True)
class PushDeliveryOutcome:
    """The result of one push attempt for one inbox record.

    ``state`` is one of ``delivered`` / ``failed`` / ``not_configured`` /
    ``no_subscription``.  It never describes the inbox record: the record's own
    status is owned by the existing inbox authority and is not changed here.
    """

    state: str
    attempted: int = 0
    delivered: int = 0
    failed: int = 0

    @property
    def inbox_state_changed(self) -> bool:
        """Always false: a push never changes the underlying record."""

        return False


async def deliver_inbox_push(
    *,
    store: D1ClawPushSubscriptionStore,
    sender: Any | None,
    workspace_id: str,
    member_id: str,
    scope: str,
    title: str,
    body: str,
    url: str | None = None,
) -> PushDeliveryOutcome:
    """Attempt a browser push for one inbox record.

    The web inbox is the source of truth: this function only *additionally*
    tries to reach a device.  A missing push authority, a missing
    subscription, or a failing delivery leaves the inbox record exactly as it
    is, and the caller never learns a false success from it.
    """

    if sender is None or not callable(getattr(sender, "send", None)):
        return PushDeliveryOutcome(state="not_configured")
    try:
        subscriptions = await store.list_for(
            workspace_id=workspace_id, member_id=member_id, scope=scope
        )
    except WorkspaceStorageError:
        return PushDeliveryOutcome(state="failed")
    if not subscriptions:
        return PushDeliveryOutcome(state="no_subscription")
    attempted = 0
    delivered = 0
    failed = 0
    for subscription in subscriptions:
        attempted += 1
        try:
            result = sender.send(
                subscription=subscription,
                title=title,
                body=body,
                url=url,
            )
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            failed += 1
            continue
        if result is True:
            delivered += 1
        else:
            failed += 1
    if delivered:
        return PushDeliveryOutcome(
            state="delivered", attempted=attempted, delivered=delivered, failed=failed
        )
    return PushDeliveryOutcome(
        state="failed", attempted=attempted, delivered=0, failed=failed
    )


def _store(request: Request) -> D1ClawPushSubscriptionStore | None:
    return getattr(request.app.state, "claw_push_subscription_store", None)


async def _read_payload(request: Request) -> dict[str, Any] | JSONResponse:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type", "JSON request required.")
    try:
        raw = await read_bounded_request_body(request, max_bytes=MAX_PUSH_BODY_BYTES)
    except RequestBodyTooLarge:
        return _error(400, "invalid_payload", "Invalid request payload.")
    if not raw:
        return _error(400, "invalid_payload", "Invalid request payload.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "Invalid JSON.")
    if not isinstance(data, dict) or set(data) != {"endpoint", "keys", "scope"}:
        return _error(400, "invalid_payload", "Invalid request payload.")
    keys = data.get("keys")
    if not isinstance(keys, dict) or set(keys) != {"p256dh", "auth"}:
        return _error(400, "invalid_payload", "Invalid request payload.")
    return data


async def claw_push_capability(request: Request) -> JSONResponse:
    """Report whether browser push is available for this deployment.

    The VAPID public key is the public half of the pair, so it is safe to
    expose; the private key never leaves the server.  With no push authority
    configured the honest answer is ``enabled=false``: the web inbox stays
    fully usable and the browser is told not to offer a push toggle.
    """

    public_key = getattr(request.app.state, "claw_push_public_key", None)
    enabled = isinstance(public_key, str) and bool(public_key.strip())
    return JSONResponse(
        {
            "ok": True,
            "enabled": enabled,
            "public_key": public_key.strip() if enabled else None,
            "scope": str(request.base_url).rstrip("/") + "/",
        },
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_push_subscription_register(request: Request) -> JSONResponse:
    """Register or update this account's device subscription."""

    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "Authentication is required.")
    payload = await _read_payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    store = _store(request)
    if store is None:
        return _error(503, "push_unavailable", "Push subscriptions are unavailable.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    if not workspace_id:
        return _error(503, "workspace_unavailable", "Workspace authority is unavailable.")
    try:
        endpoint = _bounded(payload["endpoint"], MAX_ENDPOINT_CHARS)
        p256dh = _bounded(payload["keys"]["p256dh"], MAX_KEY_CHARS)
        auth = _bounded(payload["keys"]["auth"], MAX_KEY_CHARS)
        scope = _bounded(payload["scope"], MAX_SCOPE_CHARS)
    except PushSubscriptionError:
        return _error(400, "invalid_payload", "Invalid request payload.")
    try:
        record = await store.register(
            workspace_id=workspace_id,
            member_id=uid,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            scope=scope,
            now=_utcnow(),
        )
    except PushSubscriptionError:
        return _error(429, "too_many_subscriptions", "Too many push subscriptions.")
    except WorkspaceStorageError:
        return _error(503, "push_write_failed", "Push subscription could not be saved.")
    return JSONResponse(
        {"ok": True, "subscription": record.safe_dict()},
        status_code=200,
        headers=_NO_STORE_HEADERS,
    )


async def claw_push_subscription_unregister(request: Request) -> JSONResponse:
    """Remove one of this account's device subscriptions."""

    uid = _require_owner(request)
    if uid is None:
        return _error(401, "unauthorized", "Authentication is required.")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type", "JSON request required.")
    try:
        raw = await read_bounded_request_body(request, max_bytes=MAX_PUSH_BODY_BYTES)
    except RequestBodyTooLarge:
        return _error(400, "invalid_payload", "Invalid request payload.")
    if not raw:
        return _error(400, "invalid_payload", "Invalid request payload.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json", "Invalid JSON.")
    if not isinstance(data, dict) or set(data) != {"subscription_id"}:
        return _error(400, "invalid_payload", "Invalid request payload.")
    target = data.get("subscription_id")
    if not isinstance(target, str) or not target.strip():
        return _error(400, "invalid_payload", "Invalid request payload.")
    store = _store(request)
    if store is None:
        return _error(503, "push_unavailable", "Push subscriptions are unavailable.")
    workspace_id = await _resolve_memory_workspace(request, uid)
    if not workspace_id:
        return _error(503, "workspace_unavailable", "Workspace authority is unavailable.")
    try:
        removed = await store.unregister(
            workspace_id=workspace_id, member_id=uid, subscription_id=target.strip()
        )
    except WorkspaceStorageError:
        return _error(503, "push_write_failed", "Push subscription could not be removed.")
    if not removed:
        # An unknown or foreign subscription is the same bounded answer as a
        # missing inbox item: the caller learns nothing about another account.
        return _error(404, "push_subscription_not_found", "Push subscription not found.")
    return JSONResponse(
        {"ok": True, "removed": True}, status_code=200, headers=_NO_STORE_HEADERS
    )


__all__ = [
    "MAX_SUBSCRIPTIONS_PER_ACCOUNT",
    "PUSH_SUBSCRIPTION_PATH",
    "D1ClawPushSubscriptionStore",
    "PushDeliveryOutcome",
    "PushSubscription",
    "PushSubscriptionError",
    "claw_push_subscription_register",
    "claw_push_subscription_unregister",
    "deliver_inbox_push",
    "subscription_id",
]