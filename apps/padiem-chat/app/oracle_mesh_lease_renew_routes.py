"""#5997 — the executor keeps its claim while a long PC command is still running.

The claim lease (#5895) fixed a lost poll response: a claim whose answer never reached
the executor is handed out again after the lease. It also opened a hole the other way
round. A command that takes longer than the lease is re-delivered to a poll with a
*new* nonce, and the original executor's late submission carries the old one — which
the existing nonce comparison refuses, so a PC command of a few minutes lost its
result (dprod evidence: 379,943 ms, `submit_refused` repeated, quarantined).

This module is the renewal half. While the executor is still running the command it
posts the same dispatch id and the same nonce here, on the authenticated channel the
poll and the submission already use, and the server pushes `claimed_until` forward.
The renewal condition is the submission's own proof — pending, same nonce — so a
renewal can never resurrect a claim the lane has already given to someone else, and an
executor that dies simply stops renewing: the lease expires and the work is
re-delivered exactly as #5895 designed. No time ceiling is added anywhere.
"""
from __future__ import annotations

import hashlib
import re

from starlette.requests import Request
from starlette.responses import JSONResponse

from .oracle_mesh_read_return_routes import (
    _channel_proof,
    _channel_source,
    _error,
    _read_body,
    _response,
)

ORACLE_MESH_READ_RENEW_PATH = "/api/claw/connector/mesh-reads/renew"
_DISPATCH = re.compile(r"\Adsp_[0-9a-f]{32}\Z")
_NONCE = re.compile(r"\A[0-9a-f]{16,128}\Z")


async def oracle_mesh_read_renew(request: Request) -> JSONResponse:
    """Extend one live claim; an expired or reassigned claim is told, never revived."""

    mesh_source = _channel_source(request)
    if mesh_source is None:
        return _error(503, "oracle_mesh_unconfigured")
    if not _channel_proof(request, mesh_source):
        return _error(403, "oracle_mesh_channel_rejected")
    history_store = getattr(request.app.state, "history_store", None)
    renew = getattr(history_store, "renew_oracle_mesh_claim", None)
    if not callable(renew):
        return _error(503, "oracle_mesh_unconfigured")
    body = await _read_body(request, frozenset({"dispatch_id", "nonce"}))
    if body is None:
        return _error(400, "oracle_mesh_renew_invalid")
    dispatch_id = body.get("dispatch_id")
    nonce = body.get("nonce")
    if (
        not isinstance(dispatch_id, str) or _DISPATCH.fullmatch(dispatch_id) is None
        or not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None
    ):
        return _error(400, "oracle_mesh_renew_invalid")
    try:
        claimed_until = await renew(
            dispatch_id=dispatch_id,
            nonce_sha256=hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
        )
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if claimed_until is None:
        # The claim is no longer this executor's: it expired and another poll won it,
        # or the command already ended. Renewing must not take it back.
        return _error(409, "oracle_mesh_claim_lost")
    return _response({"ok": True, "claimed_until": claimed_until})
