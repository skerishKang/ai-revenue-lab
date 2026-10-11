"""#3580 Telegram artifact delivery consumer route.

The existing connector-owned delivery adapter (#3666) and its host injection
boundary (#4333/#4342) had no consumer. This route is that consumer, and it is
deliberately thin — it creates **no** WRITE/SEND authority:

```text
1. the signed-in owner and the canonical workspace are proved server-side;
2. only an already-completed, owner-scoped canonical artifact of the existing
   D1 conversation index can be selected;
3. the artifact's digest and media type are checked against the index row;
4. the delivery request is built by the host from the *current* trusted channel
   context plus an approval handle taken from the existing approval authority —
   the route never mints one, and the destination is never a request value;
5. the existing adapter performs at most one provider call;
6. the canonical receipt is recorded in the existing owner-scoped store;
7. one attempt per artifact: a second request returns the recorded receipt and
   never sends again;
8. the response states the actual terminal status.
```

When any of the three trusted host seams is absent — the adapter, the receipt
store or the request builder — the route answers ``403`` and **no external
Telegram call is possible**, because the adapter itself is never reached.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse

from kagent.artifact_delivery_execution_receipt import (
    ArtifactDeliveryExecutionRequest, DeliveryTerminalStatus, build_delivery_receipt,
)
from kagent.artifact_lineage import LineageArtifactRef
from kagent.connector_trust import ConnectorProviderError, ConnectorProviderErrorKind

from .auth_routes import auth_ready, current_user_id
from .claw_artifact_delivery_receipt_store import (
    PENDING_STATUS, RESERVATION_EXISTING, RESERVATION_NEW, RESERVATION_REFUSED,
    ArtifactDeliveryReceiptError, receipt_public_projection,
)
from .claw_routes import _resolve_canonical_tenant
from .history import validate_conversation_id

TELEGRAM_DELIVERY_PATH = (
    "/api/claw/conversations/{conversation_id}/artifacts/{artifact_id}/telegram"
)

_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{5,127}$")
_PDF = "application/pdf"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DELIVERABLE_MEDIA_TYPES = (_PDF, _XLSX)

_HEADERS = {
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Vary": "Cookie",
}

CONSUMER_ROUTE_IMPLEMENTED = True
NEW_WRITE_SEND_AUTHORITY = False
DESTINATION_FROM_REQUEST = False
APPROVAL_MINTED_BY_ROUTE = False


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"ok": False, "error": {"code": code}}, status_code=status, headers=_HEADERS,
    )


def _receipt_response(
    status: int, *, ok: bool, delivered: bool, reason: str | None,
    row: dict, extra_code: str | None = None,
) -> JSONResponse:
    body: dict[str, object] = {
        "ok": ok,
        "delivered": delivered,
        "receipt": receipt_public_projection(row),
    }
    if reason is not None:
        body["reason"] = reason
    if extra_code is not None:
        body["error"] = {"code": extra_code}
    return JSONResponse(body, status_code=status, headers=_HEADERS)


def _failure_receipt(
    request: ArtifactDeliveryExecutionRequest, *,
    started_at: datetime, completed_at: datetime, exc: BaseException,
):
    """Truthful terminal failure when the adapter raised before a receipt.

    The exception *class name* is the only thing that reaches the receipt; a
    transport can echo a provider body (and a token-bearing URL) inside its
    message, so the message is dropped. One attempt per artifact is enforced by
    the reservation, not by the retryable flag, so nothing here can re-send.
    """
    digest = hashlib.sha256(exc.__class__.__name__.encode("utf-8")).hexdigest()
    return build_delivery_receipt(
        receipt_ref="tgdlverr" + digest[:24],
        request=request,
        terminal_status=DeliveryTerminalStatus.FAILED_TERMINAL,
        started_at=started_at,
        completed_at=completed_at,
        provider_error=ConnectorProviderError(
            kind=ConnectorProviderErrorKind.UNKNOWN,
            error_ref="tgdlverr-" + digest[:16],
            retryable=False,
        ),
    )


async def claw_telegram_artifact_delivery(request: Request) -> JSONResponse:
    """Deliver one owner-scoped completed artifact to the current Telegram chat."""
    owner = current_user_id(request) if auth_ready(request) else None
    if not owner:
        return _error(401, "unauthorized")
    try:
        conversation = validate_conversation_id(
            request.path_params.get("conversation_id")
        )
    except (TypeError, ValueError):
        return _error(400, "invalid_conversation_id")
    if conversation is None:
        return _error(400, "invalid_conversation_id")
    artifact_id = request.path_params.get("artifact_id")
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
        return _error(400, "invalid_artifact_id")

    workspace = await _resolve_canonical_tenant(request)
    if not isinstance(workspace, str) or not workspace:
        return _error(403, "workspace_scope_unavailable")

    state = request.app.state
    adapter = getattr(state, "claw_telegram_artifact_delivery", None)
    store = getattr(state, "claw_artifact_delivery_receipt_store", None)
    builder = getattr(state, "claw_telegram_delivery_request_builder", None)
    history = getattr(state, "history_store", None)
    if (
        not callable(getattr(adapter, "deliver", None))
        or not callable(getattr(store, "reserve", None))
        or not callable(getattr(store, "complete", None))
        or not callable(builder)
        or not callable(getattr(history, "get_owner_conversation_artifact", None))
    ):
        # No trusted seam: refuse before any provider path exists.
        return _error(403, "delivery_unavailable")

    try:
        row = await history.get_owner_conversation_artifact(
            user_id=owner, conversation_id=conversation,
            workspace_ref=workspace, artifact_id=artifact_id,
        )
    except Exception:
        return _error(403, "artifact_scope_unavailable")
    if not isinstance(row, dict):
        return _error(404, "artifact_not_found")
    media_type = row.get("media_type")
    integrity_ref = row.get("integrity_ref")
    source_run_ref = row.get("source_run_ref")
    if (
        media_type not in _DELIVERABLE_MEDIA_TYPES
        or not isinstance(integrity_ref, str) or not integrity_ref
        or not isinstance(source_run_ref, str) or not source_run_ref
    ):
        return _error(415, "artifact_not_deliverable")

    now = datetime.now(timezone.utc)
    artifact_ref = LineageArtifactRef(
        artifact_id=artifact_id, integrity_ref=integrity_ref
    )

    # The delivery request — and therefore the approval handle — comes from the
    # trusted host. The route never mints an approval and never names a
    # destination.
    try:
        delivery_request = builder(
            workspace_ref=workspace, run_ref=source_run_ref,
            artifact_ref=artifact_ref, now=now,
        )
    except Exception:
        return _error(403, "send_approval_unavailable")
    if not isinstance(delivery_request, ArtifactDeliveryExecutionRequest):
        return _error(403, "send_approval_unavailable")

    try:
        reservation = await store.reserve(
            owner_id=owner, conversation_id=conversation, workspace_ref=workspace,
            source_run_ref=source_run_ref, artifact_id=artifact_id,
            artifact_integrity_ref=integrity_ref,
            delivery_kind=delivery_request.delivery_kind.value,
            connector_id="telegram",
            delivery_intent_id=delivery_request.delivery_intent_id,
            attempt_ref=delivery_request.attempt_ref, now=now,
        )
    except ArtifactDeliveryReceiptError:
        return _error(403, "delivery_unavailable")
    except Exception:
        return _error(503, "delivery_receipt_store_unavailable")

    if reservation.disposition == RESERVATION_REFUSED:
        return _error(403, "artifact_scope_unavailable")
    if reservation.disposition == RESERVATION_EXISTING:
        existing = reservation.receipt or {}
        if existing.get("terminal_status") == PENDING_STATUS:
            return _error(409, "delivery_in_progress")
        # One attempt per artifact: a recorded attempt is never re-sent, and a
        # possibly-delivered failure needs a separately authorized reconciler.
        return _receipt_response(
            200, ok=existing.get("terminal_status") == "succeeded",
            delivered=False, reason="already_delivered", row=existing,
        )

    started_at = datetime.now(timezone.utc)
    try:
        receipt = adapter.deliver(delivery_request, now=started_at)
    except Exception as exc:  # noqa: BLE001 - the receipt records the outcome
        completed_at = datetime.now(timezone.utc)
        receipt = _failure_receipt(
            delivery_request, started_at=started_at, completed_at=completed_at,
            exc=exc,
        )

    completed_at = datetime.now(timezone.utc)
    try:
        recorded = await store.complete(
            owner_id=owner, conversation_id=conversation, workspace_ref=workspace,
            artifact_id=artifact_id, artifact_integrity_ref=integrity_ref,
            receipt=receipt, now=completed_at,
        )
        stored = await store.load(
            owner_id=owner, conversation_id=conversation, workspace_ref=workspace,
            artifact_id=artifact_id, artifact_integrity_ref=integrity_ref,
        )
    except Exception:
        recorded, stored = False, None
    if recorded is not True or not isinstance(stored, dict):
        # The provider outcome is unknown to the caller; never claim success.
        return _error(503, "delivery_receipt_unverified")

    if receipt.terminal_status is DeliveryTerminalStatus.SUCCEEDED:
        return _receipt_response(
            200, ok=True, delivered=True, reason=None, row=stored,
        )
    if receipt.terminal_status is DeliveryTerminalStatus.REFUSED:
        return _receipt_response(
            403, ok=False, delivered=False, reason="refused", row=stored,
            extra_code="delivery_refused",
        )
    return _receipt_response(
        502, ok=False, delivered=False, reason="not_confirmed", row=stored,
        extra_code="delivery_not_completed",
    )


# A reservation is deliberately never released: an attempt whose provider
# outcome is unknown must be reconciled, not retried from the browser.
RESERVATION_RELEASE_SUPPORTED = False


__all__ = [
    "APPROVAL_MINTED_BY_ROUTE",
    "CONSUMER_ROUTE_IMPLEMENTED",
    "DESTINATION_FROM_REQUEST",
    "NEW_WRITE_SEND_AUTHORITY",
    "RESERVATION_RELEASE_SUPPORTED",
    "TELEGRAM_DELIVERY_PATH",
    "claw_telegram_artifact_delivery",
]
