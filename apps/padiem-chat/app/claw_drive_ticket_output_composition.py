"""#3330/#3580: validate an ephemeral ticket against trusted Drive evidence.

Host-only, no HTTP entrypoint, no Drive request or new execution authority.
A ticket is only a bound *plan*. Fresh current Drive metadata is supplied by
the existing authorized READ port; the same canonical P01 owner-run history
and canonical WRITE approval/uploader remain mandatory and independent.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from padiem_ai_core.drive_capability import DriveFileProjection
from padiem_ai_core.drive_index_freshness import DriveIndexFreshness, drive_index_freshness
from padiem_ai_core.ephemeral_work_ticket import EphemeralExecutionWorkTicket
from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import CanonicalArtifactRecord
from kagent.connector_trust import ConnectorWriteIntent

from .claw_durable_drive_output_pipeline import (
    ClawDurableDriveOutputPipeline,
    DurableArtifactRegistration,
)


class TicketOutputCompositionError(ValueError):
    """Refuse without emitting owner, file IDs, OAuth values or provider body."""


async def upload_completed_output_with_verified_ticket(
    *,
    pipeline: ClawDurableDriveOutputPipeline,
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
    """Narrow integration with existing Drive approval, receipt and D1 pipeline.

    The authenticated host, NOT model/browser ticket JSON, must supply owner_id,
    run_ref, workspace_ref and fresh canonical metadata via its existing
    authorized Drive READ port. Merely passing this validator never authorizes
    a provider read/write or guarantees freshness against a later mutation.
    The canonical WRITE adapter still verifies independent consent and scope.
    """
    if (
        not isinstance(pipeline, ClawDurableDriveOutputPipeline)
        or not isinstance(ticket, EphemeralExecutionWorkTicket)
        or not isinstance(intent, ConnectorWriteIntent)
        or not isinstance(now, datetime)
        or now.tzinfo is None or now.utcoffset() is None
    ):
        raise TicketOutputCompositionError("trusted output ticket context unavailable")
    if (
        ticket.mode != "produce_artifact"
        or not ticket.is_within_time_window(now)
        or ticket.owner_ref != owner_id
        or ticket.workspace_ref != workspace_ref
        or ticket.run_ref != run_ref
        or ticket.output_folder_ref != intent.target_ref
    ):
        raise TicketOutputCompositionError("output ticket scope or lifetime mismatch")
    if (
        not isinstance(current_sources, (list, tuple))
        or len(current_sources) != len(ticket.inputs)
    ):
        raise TicketOutputCompositionError("fresh Drive input evidence missing")
    for original, current in zip(ticket.inputs, current_sources):
        if not isinstance(current, DriveFileProjection):
            raise TicketOutputCompositionError("fresh canonical Drive metadata required")
        if drive_index_freshness(original, current) is not DriveIndexFreshness.CURRENT:
            raise TicketOutputCompositionError("Drive input version not current")

    # This existing pipeline independently revalidates the live completed
    # owner-run before and after the external WRITE, and performs the only
    # canonical provider upload + receipt/D1 registration. Never retry here.
    return await pipeline.upload_completed_run_output(
        owner_id=owner_id,
        conversation_id=conversation_id,
        workspace_ref=workspace_ref,
        run_ref=run_ref,
        artifact_ref=artifact_ref,
        source_record=source_record,
        intent=intent,
        now=now,
    )


# No Production composition, Drive READ/WRITE activation, or grant installation.
PRODUCTION_TICKET_OUTPUT_COMPOSITION_ACTIVE = False
