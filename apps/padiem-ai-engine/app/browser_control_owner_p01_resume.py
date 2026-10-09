"""#3782 independent HUMAN approved D1 -> canonical Engine browser P01 resume.

Internal source bridge only; no public route or Product Worker composition.
No submitted approval/decision/subject/action is accepted. All authority is
read from an original Engine D1 continuation and DIFFERENT user-owned D1.
Existing Engine resume independently revalidates human evidence, then performs
the canonical one-shot CAS/receipt, with ZERO Browser Input or Broker dispatch.
"""
from __future__ import annotations

import json
import re

from app.browser_control_owner_p01_d1_read import IndependentOwnerP01D1Reader
from app.continuation_binding import IdentityBoundContinuationRecord
from app.continuation_d1 import CloudflareD1IdentityBoundContinuationStore
from app.service import ServiceResponse
from app.tool_execution_service import ToolExecutionEngineService

BROWSER_CONTROL_OWNER_P01_ENGINE_RESUME_WIRED = False
BROWSER_CONTROL_OWNER_P01_RESUME_PATH = "/internal/v1/browser-control/owner-p01/resume"
MAX_OWNER_RESUME_BODY_BYTES = 512
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")


def _unavailable() -> ServiceResponse:
    return ServiceResponse(
        status_code=503,
        body={"ok": False, "error": {"code": "browser_control_owner_resume_unavailable"}},
    )


class IndependentlyApprovedBrowserControlEngineResume:
    """Resume only the exact current human-approved original browser pause."""

    def __init__(
        self, *, engine_service: ToolExecutionEngineService,
        engine_store: CloudflareD1IdentityBoundContinuationStore,
        owner_reader: IndependentOwnerP01D1Reader,
    ) -> None:
        if (
            type(engine_service) is not ToolExecutionEngineService
            or type(engine_store) is not CloudflareD1IdentityBoundContinuationStore
            or type(owner_reader) is not IndependentOwnerP01D1Reader
            or engine_service._continuation_store is not engine_store
            or engine_service._browser_control_human_p01_resolver is not owner_reader
            or engine_service._browser_control_p01_receipts is None
            or engine_service._browser_control_p01_receipts._binding is not engine_store._binding
            or owner_reader._owner is engine_store._binding
        ):
            raise ValueError("independent current human P01 and exact Engine receipt required")
        self._service = engine_service
        self._engine = engine_store
        self._owner = owner_reader

    async def handle(
        self, *, method: str, path: str, content_type: str | None, body: bytes,
    ) -> ServiceResponse:
        """Exact private Engine caller wire; no caller decision or action data."""
        if method != "POST" or path != BROWSER_CONTROL_OWNER_P01_RESUME_PATH:
            return ServiceResponse(
                status_code=405,
                body={"ok": False, "error": {"code": "browser_owner_resume_method_invalid"}},
            )
        if (
            type(content_type) is not str
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
            or type(body) is not bytes or len(body) > MAX_OWNER_RESUME_BODY_BYTES
        ):
            return _unavailable()
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _unavailable()
        if (
            type(data) is not dict or set(data) != {"app_id", "continuation_ref"}
            or any(type(data[k]) is not str for k in data)
        ):
            return _unavailable()
        return await self.resume(
            app_id=data["app_id"], continuation_ref=data["continuation_ref"],
        )

    async def resume(self, *, app_id: str, continuation_ref: str) -> ServiceResponse:
        # Service-only entrypoint: caller cannot submit approval evidence,
        # browser input, owner subject or agent tool authorization.
        if (
            type(app_id) is not str or _REF.fullmatch(app_id) is None
            or type(continuation_ref) is not str
            or not continuation_ref.startswith("cont_")
            or _REF.fullmatch(continuation_ref) is None
        ):
            return _unavailable()
        try:
            record = await self._engine.resolve(
                app_id=app_id, continuation_ref=continuation_ref,
            )
            if (
                type(record) is not IdentityBoundContinuationRecord
                or record.state != "active"
                or record.pause.tool_id != "browser.control"
                or record.pause.approval_scope != ("browser.control",)
            ):
                return _unavailable()
            proof = await self._owner.approved_original(record)
            if proof is None:
                return _unavailable()
            decision = proof.decision
            # The EXISTING Engine resume path independently validates the
            # current original ToolInvocation, owner D1 evidence and CAS state.
            # This bridge never writes a receipt, grants a tool or executes Input.
            return await self._service.resume_payload({
                "app_id": app_id,
                "continuation_ref": continuation_ref,
                "decision": {
                    "decision_id": decision.decision_id,
                    "pause_id": decision.pause_id,
                    "outcome": decision.outcome.value,
                    "authority_ref": decision.authority_ref,
                    "evidence_ref": decision.evidence_ref,
                    "decided_at": decision.decided_at.isoformat(),
                },
            })
        except Exception:  # noqa: BLE001 - D1/Engine faults must never grant browser control
            return _unavailable()
