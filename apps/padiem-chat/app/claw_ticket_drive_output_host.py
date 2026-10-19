"""#3330: host junction — verified Work Ticket → existing Drive output pipeline.

Host-only composition. An existing authorized host supplies the ephemeral
Work Ticket, fresh canonical Drive metadata via its READ port, and trusted
execution context. This module never creates Drive authority, OAuth grants,
P01 approvals, or execution backends. It is the minimal junction that lets an
existing host actually call the verified ticket composition (#4669/#4670).

No Production activation by import: PRODUCTION_TICKET_DRIVE_OUTPUT_HOST_ACTIVE = False.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from padiem_ai_core.drive_capability import DriveFileProjection
from padiem_ai_core.ephemeral_work_ticket import EphemeralExecutionWorkTicket

from app.claw_drive_ticket_output_composition import (
    TicketOutputCompositionError,
    upload_completed_output_with_verified_ticket,
)
from app.claw_durable_drive_output_pipeline import (
    ClawDurableDriveOutputPipeline,
    DurableArtifactRegistration,
    OwnerRunArtifactHistory,
)

from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import CanonicalArtifactRecord
from kagent.connector_trust import ConnectorWriteIntent


class ClawTicketDriveOutputHost:
    """Host-side junction: verified ticket + fresh Drive evidence → existing pipeline.

    The caller (trusted host, not browser/model) supplies the ticket and fresh
    DriveFileProjection metadata obtained through its existing authorized READ
    port. This module only forwards to the existing verified composition and
    existing uploader/D1 pipeline; it creates no grant, approval, or transport.
    """

    def __init__(
        self,
        *,
        pipeline: ClawDurableDriveOutputPipeline,
        history: OwnerRunArtifactHistory,
        drive_reader: Any = None,
    ) -> None:
        if not isinstance(pipeline, ClawDurableDriveOutputPipeline):
            raise TicketOutputCompositionError("approved Drive/D1 pipeline required")
        if not callable(getattr(history, "verify_owner_conversation_artifacts", None)):
            raise TicketOutputCompositionError("trusted owner history required")
        self._pipeline = pipeline
        self._history = history
        self._drive_reader = drive_reader

    async def complete_ticketed_output(
        self,
        *,
        ticket: EphemeralExecutionWorkTicket,
        current_sources: Sequence[DriveFileProjection],
        owner_id: str,
        conversation_id: str,
        workspace_ref: str,
        run_ref: str,
        artifact_ref: LineageArtifactRef,
        source_record: CanonicalArtifactRecord,
        intent: ConnectorWriteIntent,
        now: datetime,
    ) -> DurableArtifactRegistration:
        """Validate the ticket against fresh Drive evidence and run the pipeline.

        All authorization (owner, workspace, run, Drive READ grant, WRITE
        intent, ticket lifetime, input version freshness) is rechecked by the
        existing verified composition before any provider call.
        """
        if not isinstance(ticket, EphemeralExecutionWorkTicket):
            raise TicketOutputCompositionError("trusted work ticket required")
        if not isinstance(current_sources, (list, tuple)):
            raise TicketOutputCompositionError("fresh Drive input evidence required")
        if not all(isinstance(s, DriveFileProjection) for s in current_sources):
            raise TicketOutputCompositionError("fresh canonical Drive metadata required")
        return await upload_completed_output_with_verified_ticket(
            pipeline=self._pipeline,
            ticket=ticket,
            current_sources=current_sources,
            owner_id=owner_id,
            conversation_id=conversation_id,
            workspace_ref=workspace_ref,
            run_ref=run_ref,
            artifact_ref=artifact_ref,
            source_record=source_record,
            intent=intent,
            now=now,
        )


# No Production activation by import. The trusted production Worker composes
# and enables this host only after explicit review.
PRODUCTION_TICKET_DRIVE_OUTPUT_HOST_ACTIVE = False
