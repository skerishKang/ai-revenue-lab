"""#3580/#3933: canonical broker terminal fact gates Office XLSX/PDF handoff.

Trusted server-side source bridge, not an HTTP endpoint. The caller must supply
actual canonical Office output material from an independently authorized local
runner and two Control Plane-approved Drive intents. Broker terminal status is
NOT evidence of file bytes or Drive authority; both are validated separately.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from kagent.connector_trust import ConnectorWriteIntent
from kagent.local_xlsx_revision_pdf import LocalRevisedXlsxPdf

from .claw_local_task_result_projection import LocalRunnerTerminalObservation
from .claw_office_drive_completion import (
    ClawOfficeDriveCompletion, CompletedOfficeDriveDelivery,
)
from .claw_durable_drive_output_pipeline import DurableArtifactCompletionError
from .history import validate_conversation_id

_CORRELATION_FIELDS = (
    "command_id", "tool_request_ref", "request_id",
    "revision_ref", "evidence_ref", "request_fingerprint",
)


class LocalOfficeOriginBridge:
    """Match stored owner/run/correlation with a successful canonical broker ack.

    Never derive identity from a filename, provider response, model completion,
    or a client-provided conversation reference. The existing Drive completion
    independently checks exact bytes, approval, owner and current run AGAIN
    immediately before each external upload.
    """

    def __init__(self, *, history: Any, terminal_port: Any,
                 completion: ClawOfficeDriveCompletion) -> None:
        if (not callable(getattr(history, "get_claw_run", None))
                or not callable(getattr(history, "get_local_task_correlation", None))
                or not callable(getattr(history, "verify_owner_conversation_artifacts", None))
                or not callable(getattr(terminal_port, "command_result", None))
                or not isinstance(completion, ClawOfficeDriveCompletion)):
            raise DurableArtifactCompletionError(
                "trusted owner history, broker terminal and Drive completion required"
            )
        self._history = history
        self._terminal_port = terminal_port
        self._completion = completion

    async def complete_approved_office_run(
        self, *, owner_id: str, run_ref: str,
        outputs: LocalRevisedXlsxPdf,
        xlsx_intent: ConnectorWriteIntent,
        pdf_intent: ConnectorWriteIntent,
        now: datetime,
    ) -> CompletedOfficeDriveDelivery:
        if (not all(isinstance(x, str) and x for x in (owner_id, run_ref))
                or not isinstance(outputs, LocalRevisedXlsxPdf)
                or not isinstance(xlsx_intent, ConnectorWriteIntent)
                or not isinstance(pdf_intent, ConnectorWriteIntent)
                or not isinstance(now, datetime)
                or now.tzinfo is None or now.utcoffset() is None):
            raise DurableArtifactCompletionError("trusted local Office output required")

        # Only an existing server-owned completed run supplies the destination.
        try:
            row = await self._history.get_claw_run(owner_id, run_ref)
            if not isinstance(row, dict) or row.get("run_id") != run_ref:
                raise ValueError("not found")
            conversation_id = validate_conversation_id(row.get("conversation_id"))
            workspace_ref = row.get("workspace_id")
            if (conversation_id is None or not isinstance(workspace_ref, str)
                    or not workspace_ref or row.get("status") != "completed"):
                raise ValueError("not completed")
            if await self._history.verify_owner_conversation_artifacts(
                owner_id, conversation_id
            ) is not True:
                raise ValueError("foreign conversation")
            bound = await self._history.get_local_task_correlation(owner_id, run_ref)
            if not isinstance(bound, dict) or any(
                name not in bound for name in _CORRELATION_FIELDS
            ):
                raise ValueError("unbound command")
            if not isinstance(bound["command_id"], str) or not bound["command_id"]:
                raise ValueError("invalid command")
        except Exception:
            raise DurableArtifactCompletionError(
                "completed owner-bound local run unavailable"
            ) from None

        # A broker ACK with clean exit is necessary, never sufficient to prove
        # artifact bytes; OfficeDriveCompletion checks canonical material.
        try:
            fact = await self._terminal_port.command_result(
                command_id=bound["command_id"], run_id=run_ref,
                owner_id=owner_id, workspace_id=workspace_ref,
            )
        except Exception:
            raise DurableArtifactCompletionError(
                "canonical local terminal proof unavailable"
            ) from None
        if (not isinstance(fact, LocalRunnerTerminalObservation)
                or fact.run_id != run_ref
                or fact.state != "acknowledged"
                or fact.termination != "exited"
                or fact.exit_code != 0
                or any(
                    getattr(fact, name) != bound[name]
                    for name in _CORRELATION_FIELDS
                )):
            raise DurableArtifactCompletionError(
                "successful exact local command correlation unverified"
            )
        if (outputs.source.record.run_ref != run_ref
                or outputs.source.record.workspace_ref != workspace_ref):
            raise DurableArtifactCompletionError(
                "Office artifact origin does not belong to the broker run"
            )

        return await self._completion.upload_completed_revision(
            owner_id=owner_id, conversation_id=conversation_id,
            workspace_ref=workspace_ref, run_ref=run_ref,
            outputs=outputs, xlsx_intent=xlsx_intent,
            pdf_intent=pdf_intent, now=now,
        )


# No public device/browser endpoint or implicit production binding.
PRODUCTION_LOCAL_OFFICE_BRIDGE_COMPOSED = False
