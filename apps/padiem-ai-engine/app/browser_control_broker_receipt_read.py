"""#3782 authenticated Broker -> original Engine browser approval receipt READ.

No approval issuer, P01 decision parser, browser action, or broker registration.
The caller must be an already authenticated first-party Engine service; this
source-only handler additionally requires exact ORIGINAL admitted Engine
execution identity in the same durable D1 SELECT. A typed query is not a grant.
Production composition intentionally does not inject this handler.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from app.browser_control_p01_receipt import (
    AdmittedBrowserControlP01ReceiptQuery,
    CloudflareD1BrowserControlP01ReceiptStore,
)
from app.service import ServiceResponse

BROWSER_CONTROL_BROKER_RECEIPT_READ_PATH = "/internal/v1/browser-control/broker/approved-receipt/read"
BROWSER_CONTROL_BROKER_RECEIPT_READ_WIRED = False
MAX_BROWSER_RECEIPT_QUERY_BYTES = 2048

_FIELDS = frozenset({
    "app_id", "continuation_ref", "user_subject_id",
    "original_request_fingerprint", "original_admission_decision_id",
    "run_id", "invocation_sha256", "user_approval_evidence_ref",
})


def _unavailable() -> ServiceResponse:
    # Indistinguishable whether unknown, revoked, expired, or wrong original.
    return ServiceResponse(
        status_code=404,
        body={"ok": False, "error": {"code": "browser_p01_receipt_unavailable"}},
    )


class AuthenticatedBrowserP01ReceiptReadEngineService:
    """Single internal, read-only original Engine P01 receipt projection."""

    def __init__(self, *, receipts: CloudflareD1BrowserControlP01ReceiptStore):
        if type(receipts) is not CloudflareD1BrowserControlP01ReceiptStore:
            raise ValueError("canonical Engine receipt owner required")
        self._receipts = receipts

    async def handle(
        self, *, method: str, path: str, content_type: str | None, body: bytes,
    ) -> ServiceResponse:
        if method != "POST" or path != BROWSER_CONTROL_BROKER_RECEIPT_READ_PATH:
            return ServiceResponse(
                status_code=405,
                body={"ok": False, "error": {"code": "method_not_allowed"}},
            )
        if (
            type(content_type) is not str
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
            or type(body) is not bytes
            or len(body) == 0
            or len(body) > MAX_BROWSER_RECEIPT_QUERY_BYTES
        ):
            return _unavailable()
        try:
            wire = json.loads(body.decode("utf-8"))
            if (
                type(wire) is not dict
                or set(wire) != _FIELDS
                or any(type(v) is not str for v in wire.values())
            ):
                return _unavailable()
            query = AdmittedBrowserControlP01ReceiptQuery(**wire)
            now = datetime.now(UTC)
            receipt = await self._receipts.resolve_admitted(query=query, now=now)
            if receipt is None:
                return _unavailable()
            # The store has already performed a single original-run joined
            # D1 SELECT over CONSUMED continuation and unrevoked P01 receipt.
            return ServiceResponse(
                status_code=200,
                body={
                    "ok": True,
                    "receipt": {
                        "app_id": receipt.app_id,
                        "continuation_ref": receipt.continuation_ref,
                        "pause_id": receipt.pause_id,
                        "decision_id": receipt.decision_id,
                        "evidence_ref": receipt.evidence_ref,
                        "authority_ref": receipt.authority_ref,
                        "run_id": receipt.run_id,
                        "invocation_sha256": receipt.invocation_sha256,
                        "approved_at": receipt.approved_at.isoformat(),
                        "expires_at": receipt.expires_at.isoformat(),
                    },
                    "browser_action_executed": False,
                    "broker_command_dispatched": False,
                },
            )
        except Exception:  # noqa: BLE001 - failures never release approval material
            return _unavailable()
