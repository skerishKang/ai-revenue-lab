"""#3782: Engine ACTIVE pause -> independent owner P01 D1 pending ticket.

SOURCE-ONLY, NOT AN APPROVAL. Does not issue a browser command, call Broker,
start a browser, or authorize execution. The canonical user session must come
from a server-side CURRENT first-party authentication authority; the tool
request, model and frontend must NEVER construct that authority.

In particular, a typed identity object or an arbitrary session callback is
NOT proof of real human authentication. Product Worker supplies NEITHER the
session resolver nor the independent ticket writer, so this is disabled.
"""
from __future__ import annotations

import inspect
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.browser_control_pause_identity import TrustedBrowserControlPauseIdentity
from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore

TICKET_OWNER_ISSUER_WIRED = False
_TICKET_TABLE = "padiem_browser_control_owner_p01_tickets"
_MAX_ISSUE_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class CurrentCanonicalHumanSession:
    """Snapshot only from independently authenticated Control Plane session.

    The session ref must be resolved against LIVE first-party auth/session state
    on EVERY issuance. This frozen type is not a bearer grant or proof by itself.
    """

    product_user_id: str
    canonical_subject_id: str
    workspace_ref: str
    auth_session_ref: str


class FirstPartyCurrentSessionAuthority(Protocol):
    async def resolve_active(
        self, *, product_user_id: str, auth_session_ref: str,
    ) -> CurrentCanonicalHumanSession | None: ...


def _safe(value: object) -> bool:
    import re

    return type(value) is str and bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}", value)
    )


class AuthenticatedEngineBrowserP01TicketIssuer:
    """Issues a pending owner-ticket from real active Engine D1 continuation.

    No approval or execution authority is granted: an independent human click,
    immutable current ticket CAS, Engine verified resume, admitted Broker
    command mapping and local Windows permission are STILL required.
    """

    def __init__(
        self, *, engine_store: CloudflareD1IdentityBoundContinuationStore,
        owner_binding: Any, session_authority: FirstPartyCurrentSessionAuthority,
    ) -> None:
        if (
            type(engine_store) is not CloudflareD1IdentityBoundContinuationStore
            or owner_binding is None
            or owner_binding is engine_store._binding
            or not callable(getattr(owner_binding, "prepare", None))
            or not callable(getattr(session_authority, "resolve_active", None))
        ):
            raise ValueError("Engine ticket issuance requires separate D1 and current session")
        self._engine = engine_store
        self._owner = owner_binding
        self._sessions = session_authority

    async def issue(
        self, *, app_id: str, continuation_ref: str,
        product_user_id: str, auth_session_ref: str,
    ) -> str:
        # Caller cannot supply ticket contents, approval scope, user identity,
        # expiry, browser action, original run fingerprint or decision evidence.
        if not all(_safe(x) for x in (
            app_id, continuation_ref, product_user_id, auth_session_ref,
        )):
            raise ValueError("invalid bounded ticket request")
        try:
            session = self._sessions.resolve_active(
                product_user_id=product_user_id, auth_session_ref=auth_session_ref,
            )
            if inspect.isawaitable(session):
                session = await session
            if type(session) is not CurrentCanonicalHumanSession or not all(
                _safe(x) for x in (
                    session.product_user_id, session.canonical_subject_id,
                    session.workspace_ref, session.auth_session_ref,
                )
            ) or session.product_user_id != product_user_id or session.auth_session_ref != auth_session_ref:
                raise ValueError("independently authenticated current session unavailable")

            record = await self._engine.resolve(
                app_id=app_id, continuation_ref=continuation_ref,
            )
            pause, identity, admission = (
                record.pause, record.execution_identity, record.original_admission,
            )
            if (
                record.state != "active"
                or pause.tool_id != "browser.control"
                or pause.approval_scope != ("browser.control",)
                or pause.requirement.value != "user_confirmation"
                or not identity
                or not admission
                or session.canonical_subject_id != identity.subject_id
            ):
                raise ValueError("not a matching live admitted browser P01")
            TrustedBrowserControlPauseIdentity(
                execution_identity=identity, original_admission=admission,
            ).assert_matches(app_id)

            now = datetime.now(timezone.utc)
            end = min(pause.expires_at.astimezone(timezone.utc), now + _MAX_ISSUE_TTL)
            if end <= now or pause.created_at > now:
                raise ValueError("Engine browser P01 expired or future")

            # The separate D1 table has a UNIQUE(app_id, continuation_ref)
            # + ticket_ref PK. No INSERT OR REPLACE, never overwrite tickets.
            ticket_ref = "ticket_" + secrets.token_hex(24)
            sql = (
                f"INSERT INTO {_TICKET_TABLE} "
                "(ticket_ref,session_user_id,workspace_ref,engine_owner_subject_id,"
                "app_id,continuation_ref,pause_id,engine_run_id,tool_id,approval_scope,"
                "invocation_sha256,original_request_fingerprint,"
                "original_admission_decision_id,expires_at,revoked_at,"
                "server_issued_at,server_issuer_ref) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            )
            issuer_ref = "engine_" + secrets.token_hex(16)
            payload = (
                ticket_ref, product_user_id, session.workspace_ref,
                identity.subject_id, app_id, continuation_ref, pause.pause_id,
                pause.run_id, "browser.control", "browser.control",
                pause.invocation_sha256, admission.request_fingerprint,
                admission.decision_id, end.isoformat(), None, now.isoformat(),
                issuer_ref,
            )
            res = self._owner.prepare(sql).bind(*payload).run()
            if inspect.isawaitable(res):
                res = await res
            if (
                not isinstance(res, dict)
                or res.get("success") is not True
                or not isinstance(res.get("meta"), dict)
                or res["meta"].get("changes") != 1
            ):
                raise ValueError("independent current browser ticket was not inserted")
            return ticket_ref
        except Exception as exc:
            raise ValueError("authenticated browser ticket issuance unavailable") from exc
