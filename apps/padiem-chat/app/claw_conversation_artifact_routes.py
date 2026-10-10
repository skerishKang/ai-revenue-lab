"""#3929 live Claw auth/conversation/D1 bridge for durable artifact REFERENCES.

Owner identity and workspace never come from query fields, only the existing
session + canonical Control Plane tenant. GET only, no model or file access.
This route does not register artifacts, mint read grants, or accept a path.
"""
from __future__ import annotations

import inspect

from starlette.requests import Request
from starlette.responses import JSONResponse

from kagent.artifact_registration import (
    ArtifactLifecycle, ArtifactLocation, register_canonical_artifact,
)
from kagent.conversation_artifact_followup import (
    AuthorizedConversationArtifact, FollowupSelection,
    resolve_followup_artifact,
)
from .auth_routes import auth_ready, current_user_id
from .claw_routes import _resolve_canonical_tenant
from .history import validate_conversation_id

_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Vary": "Cookie"}


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}},
        status_code=status, headers=_NO_STORE,
    )


class _VerifiedIndex:
    """In-memory verified snapshot from ONE genuine owner-scoped D1 query."""

    def __init__(self, *, owner: str, conversation: str, workspace: str,
                 rows: tuple[AuthorizedConversationArtifact, ...]):
        self.owner, self.conversation, self.workspace = owner, conversation, workspace
        self.rows = rows

    def verify_conversation_access(self, *, owner_id: str,
                                   conversation_id: str, workspace_ref: str) -> bool:
        return (owner_id == self.owner and conversation_id == self.conversation
                and workspace_ref == self.workspace)

    def list_authorized_artifacts(self, *, owner_id: str,
                                  conversation_id: str, workspace_ref: str,
                                  limit: int) -> tuple[AuthorizedConversationArtifact, ...]:
        if not self.verify_conversation_access(
            owner_id=owner_id, conversation_id=conversation_id,
            workspace_ref=workspace_ref
        ) or limit != 31:
            raise ValueError("trusted source selection scope or bound unavailable")
        return self.rows


def _bounded_rows(rows: object) -> tuple[AuthorizedConversationArtifact, ...]:
    """Convert only canonical D1-proven rows; no raw refs leave this function."""
    if type(rows) is not list or len(rows) > 31:
        raise ValueError("bounded D1 record set required")
    result: list[AuthorizedConversationArtifact] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("malformed durable row")
        record = register_canonical_artifact(
            artifact_id=row["artifact_id"],
            artifact_kind=("working.xlsx" if row["media_type"]
                           == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                           else "output.pdf"),
            filename=row["filename"],
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            integrity_ref=row["integrity_ref"],
            lifecycle=ArtifactLifecycle.DURABLE,
            workspace_ref=row["workspace_ref"],
            run_ref=row["source_run_ref"],
            durable_location=ArtifactLocation(
                row["location_kind"], row["location_ref"],
            ),
        )
        result.append(AuthorizedConversationArtifact(
            owner_id=row["user_id"],
            conversation_id=row["conversation_id"],
            workspace_ref=row["workspace_ref"],
            source_run_ref=row["source_run_ref"],
            ordinal=row["ordinal"],
            record=record,
        ))
    return tuple(result)


async def claw_conversation_artifact_followup(request: Request) -> JSONResponse:
    """Owner-authenticated GET /api/claw/conversations/:id/artifact-followup.

    A resolved response supplies an ID+hash REFERENCE only; a separate
    explicitly authorized P01 file READ must independently revalidate bytes.
    """
    owner = current_user_id(request) if auth_ready(request) else None
    if not owner:
        return _error(401, "unauthorized")
    try:
        cid = validate_conversation_id(request.path_params.get("conversation_id"))
    except ValueError:
        return _error(400, "invalid_conversation_id")
    if cid is None:
        return _error(400, "invalid_conversation_id")
    # Existing CP refreshed session is the sole workspace authority.
    workspace = await _resolve_canonical_tenant(request)
    if workspace is None:
        return _error(403, "workspace_scope_unavailable")
    history = getattr(request.app.state, "history_store", None)
    verify = getattr(history, "verify_owner_conversation_artifacts", None)
    listing = getattr(history, "list_owner_conversation_artifacts", None)
    if not callable(verify) or not callable(listing):
        return _error(503, "artifact_index_unavailable")
    try:
        selection = FollowupSelection(
            owner_id=owner, conversation_id=cid, workspace_ref=workspace,
            output_kind=request.query_params.get("kind", "xlsx"),
            selector=request.query_params.get("selector", "latest"),
            filename=request.query_params.get("filename"),
            artifact_id=request.query_params.get("artifact_id"),
            integrity_ref=request.query_params.get("integrity_ref"),
        )
    except (TypeError, ValueError):
        return _error(400, "invalid_artifact_selector")
    try:
        current_owner = verify(owner, cid)
        if inspect.isawaitable(current_owner):
            current_owner = await current_owner
        if current_owner is not True:
            return _error(404, "conversation_not_found")
        items = listing(
            user_id=owner, conversation_id=cid,
            workspace_ref=workspace, limit=31,
        )
        if inspect.isawaitable(items):
            items = await items
        index = _VerifiedIndex(
            owner=owner, conversation=cid,
            workspace=workspace, rows=_bounded_rows(items),
        )
        result = resolve_followup_artifact(selection=selection, index=index)
    except Exception:
        # Schema not yet applied, current DB unavailable, malformed private
        # source, tampered record or overflow must never become an unsafe hit.
        return _error(503, "artifact_index_read_failed")
    return JSONResponse({"ok": True, "followup": result.public_projection()},
                        status_code=200, headers=_NO_STORE)


# Registration must happen only after a real approved durable P01 artifact
# is generated; neither GET nor generic plain-text Claw run history writes it.
PRODUCTION_ARTIFACT_REGISTRATION_COMPOSED = False
