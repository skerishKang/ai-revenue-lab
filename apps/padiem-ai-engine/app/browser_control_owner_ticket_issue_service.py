"""#3782: Engine private request entrypoint for ORIGINAL pending browser ticket.

Only the existing authenticated Engine Service Binding caller may reach this
service. The response is a PENDING owner ticket reference, not approval or
authority to execute browser actions.

The Worker does NOT compose the issuer; the default service is absent and its
route fails closed 503. Do not activate before independent owner-D1 provision,
the B54 canonical signed-session owner, and P01 continuation/Broker gates.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.browser_control_owner_p01_ticket_issuer import (
    AuthenticatedEngineBrowserP01TicketIssuer,
)
from app.service import ServiceResponse

BROWSER_P01_TICKET_ISSUE_PATH = "/internal/v1/browser-control/owner-ticket/issue"
BROWSER_P01_TICKET_ISSUE_ROUTE_WIRED = False
MAX_TICKET_ISSUE_BODY_BYTES = 2_048
_FIELDS = frozenset({
    "app_id", "continuation_ref", "product_user_id", "auth_session_ref",
})
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")


def _failure(status: int, code: str) -> ServiceResponse:
    return ServiceResponse(
        status_code=status, body={"ok": False, "error": {"code": code}},
    )


class BrowserControlOwnerTicketIssueEngineService:
    """Private body-authenticated, exact-shape ticket-issue service."""

    def __init__(self, *, issuer: AuthenticatedEngineBrowserP01TicketIssuer):
        if type(issuer) is not AuthenticatedEngineBrowserP01TicketIssuer:
            raise TypeError("canonical Engine pending-browser-ticket issuer required")
        self._issuer = issuer

    async def handle(
        self, *, method: str, path: str, content_type: str | None, body: bytes,
    ) -> ServiceResponse:
        if path != BROWSER_P01_TICKET_ISSUE_PATH or method != "POST":
            return _failure(405, "browser_ticket_method_not_allowed")
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _failure(415, "browser_ticket_json_required")
        if type(body) is not bytes or len(body) > MAX_TICKET_ISSUE_BODY_BYTES:
            return _failure(413, "browser_ticket_request_too_large")
        try:
            data: Any = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _failure(400, "browser_ticket_invalid_json")
        if (
            type(data) is not dict or set(data) != _FIELDS
            or any(type(data[k]) is not str or not _SAFE.fullmatch(data[k])
                   for k in _FIELDS)
        ):
            return _failure(422, "browser_ticket_invalid_request")
        try:
            ref = await self._issuer.issue(
                app_id=data["app_id"],
                continuation_ref=data["continuation_ref"],
                product_user_id=data["product_user_id"],
                auth_session_ref=data["auth_session_ref"],
            )
        except Exception:  # noqa: BLE001 - no fallback approval or provenance leaks
            return _failure(503, "browser_ticket_issuer_unavailable")
        if type(ref) is not str or not _SAFE.fullmatch(ref):
            return _failure(503, "browser_ticket_issuer_unavailable")
        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "ticket_ref": ref,
                "owner_approval_recorded": False,
                "browser_action_executed": False,
            },
        )
