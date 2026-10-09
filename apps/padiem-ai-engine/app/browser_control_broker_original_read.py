"""#3782 Broker-only independently verified Engine ORIGINAL browser admission.

A read-only projection from canonical Engine D1: original admission + CONSUMED
browser P01 pause + independently revalidated current approved receipt.
Caller authentication and exclusive Broker audience live in worker_identity,
before optional service composition. This does not associate any arbitrary
Broker command; the separate Broker original-command mapping owner must do so.
No browser command, approval issuance or execution is performed.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from app.browser_control_p01_receipt import (
    AdmittedBrowserControlP01ReceiptQuery,
    CloudflareD1BrowserControlP01ReceiptStore,
)
from app.browser_control_pause_identity import TrustedBrowserControlPauseIdentity
from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore
from app.service import ServiceResponse

BROWSER_CONTROL_BROKER_ORIGINAL_READ_PATH = "/internal/v1/browser-control/broker/original-admission/read"
BROWSER_CONTROL_BROKER_ORIGINAL_READ_WIRED = False
MAX_BROKER_ORIGINAL_QUERY_BYTES = 512
_CONT = re.compile(r"^cont_[A-Za-z0-9_-]{8,123}$")
_APP = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")


def _unavailable() -> ServiceResponse:
    return ServiceResponse(
        status_code=404,
        body={"ok": False, "error": {"code": "browser_original_admission_unavailable"}},
    )


class AuthenticatedEngineBrowserOriginalRead:
    """Closed, current Engine-owned proof; never a standalone Broker authority."""

    def __init__(
        self, *, engine_store: CloudflareD1IdentityBoundContinuationStore,
        receipts: CloudflareD1BrowserControlP01ReceiptStore,
    ) -> None:
        if (
            type(engine_store) is not CloudflareD1IdentityBoundContinuationStore
            or type(receipts) is not CloudflareD1BrowserControlP01ReceiptStore
            or engine_store._binding is not receipts._binding
        ):
            raise ValueError("same canonical Engine D1 continuation and receipt required")
        self._engine = engine_store
        self._receipts = receipts

    async def handle(
        self, *, method: str, path: str, content_type: str | None, body: bytes,
    ) -> ServiceResponse:
        if method != "POST" or path != BROWSER_CONTROL_BROKER_ORIGINAL_READ_PATH:
            return ServiceResponse(
                status_code=405,
                body={"ok": False, "error": {"code": "method_not_allowed"}},
            )
        if (
            type(content_type) is not str
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
            or type(body) is not bytes or not body
            or len(body) > MAX_BROKER_ORIGINAL_QUERY_BYTES
        ):
            return _unavailable()
        try:
            query = json.loads(body.decode("utf-8"))
            if (
                type(query) is not dict
                or set(query) != {"app_id", "continuation_ref"}
                or type(query["app_id"]) is not str
                or type(query["continuation_ref"]) is not str
                or _APP.fullmatch(query["app_id"]) is None
                or _CONT.fullmatch(query["continuation_ref"]) is None
            ):
                return _unavailable()
            app_id = query["app_id"]
            continuation_ref = query["continuation_ref"]
            current = datetime.now(UTC)
            raw = await self._engine._raw(
                app_id=app_id, continuation_ref=continuation_ref,
            )
            if raw is None:
                return _unavailable()
            record = self._engine._record(raw)
            pause = record.pause
            original = record.original_admission
            identity = record.execution_identity
            if (
                record.state != "consumed"
                or original is None or identity is None
                or pause.tool_id != "browser.control"
                or pause.approval_scope != ("browser.control",)
                or pause.requirement.value != "user_confirmation"
                or pause.created_at > current or pause.expires_at <= current
            ):
                return _unavailable()
            TrustedBrowserControlPauseIdentity(
                execution_identity=identity, original_admission=original,
            ).assert_matches(app_id)
            receipt = await self._receipts.resolve_active(
                app_id=app_id, continuation_ref=continuation_ref, now=current,
            )
            if receipt is None:
                return _unavailable()
            # Recheck the *actual* original identity in the Engine receipt D1
            # predicate, not just an arbitrary copy of an approval object.
            admitted = AdmittedBrowserControlP01ReceiptQuery(
                app_id=app_id, continuation_ref=continuation_ref,
                user_subject_id=identity.subject_id,
                original_request_fingerprint=original.request_fingerprint,
                original_admission_decision_id=original.decision_id,
                run_id=pause.run_id,
                invocation_sha256=pause.invocation_sha256,
                user_approval_evidence_ref=receipt.evidence_ref,
            )
            verified = await self._receipts.resolve_admitted(query=admitted, now=current)
            if verified is None or verified != receipt:
                return _unavailable()
            return ServiceResponse(status_code=200, body={
                "ok": True,
                "original": {
                    "app_id": app_id,
                    "continuation_ref": continuation_ref,
                    "user_subject_id": identity.subject_id,
                    "original_request_fingerprint": original.request_fingerprint,
                    "original_admission_decision_id": original.decision_id,
                    "run_id": pause.run_id,
                    "invocation_sha256": pause.invocation_sha256,
                    "user_approval_evidence_ref": verified.evidence_ref,
                },
                "browser_action_executed": False,
                "broker_command_dispatched": False,
            })
        except Exception:  # noqa: BLE001 - unavailable or malformed D1 never grants
            return _unavailable()
