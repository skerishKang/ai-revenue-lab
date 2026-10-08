"""#3782: read-only D1 ticket owner for separately issued browser P01 work.

This does NOT issue a ticket. The signed-in user's canonical workspace and
ticket reference are supplied by B54, and the separate D1 row must have been
written by an independently authenticated server/Engine admission owner.
No route/Worker binding is composed in Production.
"""
from __future__ import annotations

import inspect
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .browser_control_owner_p01_decision import (
    SAFE,
    ServerAdmittedBrowserControlOwnerTicket,
)

TABLE = "padiem_browser_control_owner_p01_tickets"
BROWSER_CONTROL_OWNER_TICKET_SOURCE_WIRED = False


class D1BrowserControlOwnerTicketLoader:
    """Retrieve exact current original-admission metadata, never client JSON."""

    def __init__(self, *, owner_binding: Any, engine_continuation_binding: Any):
        if (
            owner_binding is None
            or owner_binding is engine_continuation_binding
            or engine_continuation_binding is None
            or not callable(getattr(owner_binding, "prepare", None))
        ):
            raise ValueError("browser ticket needs independent trusted owner D1")
        self._owner = owner_binding

    async def __call__(
        self, *, user_id: str, workspace_ref: str, ticket_ref: str,
    ) -> ServerAdmittedBrowserControlOwnerTicket | None:
        if any(
            type(ref) is not str or SAFE.fullmatch(ref) is None
            for ref in (user_id, workspace_ref, ticket_ref)
        ):
            return None
        now = datetime.now(timezone.utc)
        sql = (
            "SELECT ticket_ref,session_user_id,workspace_ref,"
            "engine_owner_subject_id,app_id,continuation_ref,pause_id,"
            "engine_run_id,tool_id,approval_scope,invocation_sha256,"
            "original_request_fingerprint,original_admission_decision_id,"
            "expires_at,server_issued_at,revoked_at,server_issuer_ref "
            f"FROM {TABLE} "
            "WHERE ticket_ref=? AND session_user_id=? AND workspace_ref=? "
            "AND tool_id='browser.control' AND approval_scope='browser.control' "
            "AND revoked_at IS NULL AND server_issued_at<=? AND expires_at>? LIMIT 1"
        )
        try:
            row = self._owner.prepare(sql).bind(
                ticket_ref, user_id, workspace_ref,
                now.isoformat(), now.isoformat(),
            ).first()
            if inspect.isawaitable(row):
                row = await row
            if not isinstance(row, Mapping):
                return None
            if (
                row.get("session_user_id") != user_id
                or row.get("workspace_ref") != workspace_ref
                or row.get("ticket_ref") != ticket_ref
                or row.get("revoked_at") is not None
                or type(row.get("server_issuer_ref")) is not str
                or SAFE.fullmatch(row["server_issuer_ref"]) is None
            ):
                return None
            expires = datetime.fromisoformat(row["expires_at"])
            issued = datetime.fromisoformat(row["server_issued_at"])
            if (
                expires.tzinfo is None or expires.utcoffset() is None
                or issued.tzinfo is None or issued.utcoffset() is None
                or not issued <= now < expires
            ):
                return None
            return ServerAdmittedBrowserControlOwnerTicket(
                ticket_ref=row["ticket_ref"],
                session_user_id=row["session_user_id"],
                workspace_ref=row["workspace_ref"],
                engine_owner_subject_id=row["engine_owner_subject_id"],
                app_id=row["app_id"],
                continuation_ref=row["continuation_ref"],
                pause_id=row["pause_id"],
                engine_run_id=row["engine_run_id"],
                tool_id=row["tool_id"],
                approval_scope=(row["approval_scope"],),
                invocation_sha256=row["invocation_sha256"],
                original_request_fingerprint=row["original_request_fingerprint"],
                original_admission_decision_id=row["original_admission_decision_id"],
                expires_at=expires,
            )
        except (TypeError, ValueError, KeyError):
            return None
        except Exception:  # noqa: BLE001 - D1 owner outage is NEVER approval
            return None
