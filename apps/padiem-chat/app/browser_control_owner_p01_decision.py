"""#3782 authenticated first-party HUMAN click record for ONE browser.control ticket.

Uses the EXISTING B54 signed-in session and canonical #2961 decision-submission
vocabulary; no second Engine verifier/approval authority. Engine still MUST
independently verify and consume its identity-bound continuation. The owner
evidence is written to an independently bound owner D1; it cannot be fabricated
by Engine service identity, browser JSON, or a synthetic #3140 acceptance.
SOURCE-ONLY: route is NOT registered in the app factory, no production binding.
"""
from __future__ import annotations

import inspect
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from kagent.p01_approval_continuation import (
    P01AdapterError,
    build_first_party_decision_submission,
)
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_routes import auth_ready, current_user_id
from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_memory_routes import _resolve_memory_workspace

SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
BROWSER_CONTROL_OWNER_DECISION_ROUTE_WIRED = False
TABLE = "padiem_browser_control_owner_p01_decisions"
MAX_BODY_BYTES = 1024
NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _safe(value: object, name: str) -> str:
    if type(value) is not str or SAFE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical reference")
    return value


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("owner P01 timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ServerAdmittedBrowserControlOwnerTicket:
    """Verified server-owned ticket from the current canonical work-ticket owner.

    This immutable value is NOT a bearer approval. It MUST be loaded through
    the authenticated B54 workspace and independently checked against the
    still-active Engine pause/original admission BEFORE recording a human click.
    """

    ticket_ref: str
    session_user_id: str
    workspace_ref: str
    engine_owner_subject_id: str
    app_id: str
    continuation_ref: str
    pause_id: str
    engine_run_id: str
    tool_id: str
    approval_scope: tuple[str, ...]
    invocation_sha256: str
    original_request_fingerprint: str
    original_admission_decision_id: str
    expires_at: datetime

    def __post_init__(self) -> None:
        for key in (
            "ticket_ref", "session_user_id", "workspace_ref",
            "engine_owner_subject_id", "app_id", "continuation_ref", "pause_id",
            "engine_run_id", "original_admission_decision_id",
        ):
            _safe(getattr(self, key), key)
        if self.tool_id != "browser.control" or self.approval_scope != ("browser.control",):
            raise ValueError("owner ticket must belong to exact browser.control P01")
        for key in ("invocation_sha256", "original_request_fingerprint"):
            value = getattr(self, key)
            if type(value) is not str or SHA.fullmatch(value) is None:
                raise ValueError(f"{key} requires lowercase SHA256")
        _utc(self.expires_at)


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status, headers=NO_STORE,
    )


async def record_first_party_browser_control_approval(
    *,
    ticket: ServerAdmittedBrowserControlOwnerTicket,
    authenticated_user_id: str,
    authenticated_workspace_ref: str,
    owner_binding: Any,
    engine_continuation_binding: Any,
    now: datetime,
) -> dict[str, str]:
    """Record human APPROVE evidence, NOT issue canonical Engine permission.

    Strictly only an independently authenticated user's affirmative click can
    store a row. No DENIED -> APPROVED elevation, overwrite, or retry. The
    ticket load itself belongs to the existing B54 work-ticket authority.
    """
    if type(ticket) is not ServerAdmittedBrowserControlOwnerTicket:
        raise ValueError("canonical server-owned browser P01 ticket required")
    if (
        ticket.session_user_id != authenticated_user_id
        or ticket.workspace_ref != authenticated_workspace_ref
        or _utc(now) >= _utc(ticket.expires_at)
        or owner_binding is None
        or owner_binding is engine_continuation_binding
        or not callable(getattr(owner_binding, "prepare", None))
        or engine_continuation_binding is None
    ):
        raise ValueError("current independent authenticated owner P01 unavailable")
    stamp = _utc(now)
    # Reuse the exact first-party decision vocabulary from the canonical
    # owner-click path. Its IDs alone do NOT establish a human approval.
    submission = build_first_party_decision_submission(
        pause_id=ticket.pause_id,
        decision="approve",
        owner_id=authenticated_user_id,
        now=lambda: stamp,
    )
    decided = datetime.fromisoformat(
        submission["decided_at"].replace("Z", "+00:00")
    ).isoformat()
    expiry = _utc(ticket.expires_at).isoformat()
    if decided >= expiry:
        raise ValueError("expired owner decision")
    # A server-generated opaque reference attests that the user click went
    # through the signed-in owner route, not a client-supplied session cookie.
    confirmation = "owner_confirmation_" + secrets.token_hex(16)
    sql = (
        f"INSERT INTO {TABLE} "
        "(app_id,continuation_ref,pause_id,owner_subject_id,run_id,"
        "invocation_sha256,original_request_fingerprint,"
        "original_admission_decision_id,decision_id,authority_ref,evidence_ref,"
        "decided_at,expires_at,revoked_at,outcome,authenticated_owner_session_ref)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    params = (
        ticket.app_id, ticket.continuation_ref, ticket.pause_id,
        ticket.engine_owner_subject_id, ticket.engine_run_id,
        ticket.invocation_sha256, ticket.original_request_fingerprint,
        ticket.original_admission_decision_id, submission["decision_id"],
        submission["authority_ref"], submission["evidence_ref"], decided,
        expiry, None, "approved", confirmation,
    )
    try:
        outcome = owner_binding.prepare(sql).bind(*params).run()
        if inspect.isawaitable(outcome):
            outcome = await outcome
    except Exception as exc:
        raise ValueError("owner P01 persistence unavailable") from exc
    # D1 returns success + meta.changes; don't convert a zero-row result into
    # evidence. Existing primary key/decision ID uniqueness gives one-shot.
    if not isinstance(outcome, dict) or outcome.get("success") is not True:
        raise ValueError("owner P01 persistence not confirmed")
    meta = outcome.get("meta")
    if not isinstance(meta, dict) or meta.get("changes") != 1:
        raise ValueError("owner P01 exactly-once write not confirmed")
    return {"decision_id": submission["decision_id"], "evidence_ref": submission["evidence_ref"]}


async def browser_control_owner_p01_decision(request: Request) -> JSONResponse:
    """Bounded genuine B54 login/owner click; UNREGISTERED in production.

    Client authority: exactly ticket_ref and decision='approve'. Every other
    dimension is retrieved from the server-owned current work ticket. The
    source cannot be activated until a canonical ticket loader + separate
    owner D1 writer and Engine same-binding identity are composed.
    """
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    uid = current_user_id(request) if auth_ready(request) else None
    if uid is None:
        return _error(401, "unauthorized")
    try:
        body = await read_bounded_request_body(request, max_bytes=MAX_BODY_BYTES)
        wire = json.loads(body.decode("utf-8"))
    except RequestBodyTooLarge:
        return _error(413, "request_too_large")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "invalid_json")
    if (
        type(wire) is not dict or set(wire) != {"ticket_ref", "decision"}
        or wire.get("decision") != "approve"
        or type(wire.get("ticket_ref")) is not str
        or SAFE.fullmatch(wire["ticket_ref"]) is None
    ):
        return _error(422, "invalid_browser_p01_request")
    loader = getattr(request.app.state, "browser_control_owner_ticket_loader", None)
    binding = getattr(request.app.state, "browser_control_owner_p01_d1", None)
    engine_binding = getattr(request.app.state, "browser_control_engine_d1", None)
    if (
        not callable(loader) or binding is None or engine_binding is None
        or binding is engine_binding
    ):
        return _error(503, "browser_p01_owner_unavailable")
    try:
        workspace = await _resolve_memory_workspace(request, uid)
        ticket = loader(
            user_id=uid, workspace_ref=workspace, ticket_ref=wire["ticket_ref"]
        )
        if inspect.isawaitable(ticket):
            ticket = await ticket
        if (
            type(ticket) is not ServerAdmittedBrowserControlOwnerTicket
            or ticket.ticket_ref != wire["ticket_ref"]
        ):
            return _error(404, "browser_p01_ticket_unavailable")
        await record_first_party_browser_control_approval(
            ticket=ticket,
            authenticated_user_id=uid,
            authenticated_workspace_ref=workspace,
            owner_binding=binding,
            engine_continuation_binding=engine_binding,
            now=datetime.now(timezone.utc),
        )
    except (P01AdapterError, ValueError):
        return _error(404, "browser_p01_ticket_unavailable")
    except Exception:  # noqa: BLE001 - auth/ticket store outage fail closed
        return _error(503, "browser_p01_owner_unavailable")
    return JSONResponse(
        {"ok": True, "status": "owner_approval_evidence_recorded",
         "browser_action_executed": False,
         "engine_approval_completed": False},
        headers=NO_STORE,
    )
