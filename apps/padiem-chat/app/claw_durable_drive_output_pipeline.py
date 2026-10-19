"""#3929/#3580: approved Drive upload receipt -> D1 durable Claw artifact.

This is an INTERNAL host compositor, not an HTTP endpoint. The trusted Claw
or Desktop producer supplies only canonical context and an existing
GoogleDriveArtifactUploadAdapter. That adapter independently enforces CP
connector grant, folder proof, exact original bytes and one-shot WRITE
approval. Never mint or infer such a grant here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import ArtifactLifecycle, CanonicalArtifactRecord
from kagent.connector_trust import ConnectorWriteIntent
from kagent.google_drive_artifact_upload import (
    DriveUploadResult, GoogleDriveArtifactUploadAdapter,
)


class DurableArtifactCompletionError(ValueError):
    """No sensitive provider response/receipt is ever exposed in exceptions."""


class OwnerRunArtifactHistory(Protocol):
    async def verify_owner_conversation_artifacts(
        self, user_id: str, conversation_id: str
    ) -> bool: ...

    async def get_claw_run(self, user_id: str, run_id: str) -> dict | None: ...

    async def register_owner_conversation_artifact(
        self, *, user_id: str, conversation_id: str,
        workspace_ref: str, artifact: object
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class DurableArtifactRegistration:
    """Sanitized, owner-scoped proof; only the actual verified D1 write is PASS."""

    artifact_id: str
    integrity_ref: str
    source_run_ref: str
    stored_in_conversation_index: bool

    def public_projection(self) -> dict[str, object]:
        return {
            "contract_version": "claw-drive-to-conversation-index.v1",
            "artifact_id": self.artifact_id,
            "integrity_ref": self.integrity_ref,
            "source_run_ref": self.source_run_ref,
            "stored_in_conversation_index": self.stored_in_conversation_index,
            "read_permission_issued": False,
            "provider_file_id_present": False,
            "drive_write_enabled_by_this_service": False,
        }


class ClawDurableDriveOutputPipeline:
    """Compose one *existing* authorized Drive uploader with live D1 history.

    A completed canonical Claw run is a PRECONDITION to any provider operation.
    If the provider upload succeeds but D1 registration fails, the file may
    exist at Google Drive: fail closed and DO NOT RETRY OR UPLOAD AGAIN.
    A separately authorized reconciler would be needed to recover it.
    """

    def __init__(self, *, history: OwnerRunArtifactHistory,
                 uploader: GoogleDriveArtifactUploadAdapter) -> None:
        if (not callable(getattr(history, "verify_owner_conversation_artifacts", None))
                or not callable(getattr(history, "get_claw_run", None))
                or not callable(getattr(history, "register_owner_conversation_artifact", None))
                or not isinstance(uploader, GoogleDriveArtifactUploadAdapter)):
            raise DurableArtifactCompletionError("trusted history and Drive adapter required")
        self._history = history
        self._uploader = uploader

    async def upload_completed_run_output(
        self, *, owner_id: str, conversation_id: str, workspace_ref: str,
        run_ref: str, artifact_ref: LineageArtifactRef,
        source_record: CanonicalArtifactRecord,
        intent: ConnectorWriteIntent, now: datetime,
    ) -> DurableArtifactRegistration:
        """One authorized upload and owner-scoped D1 registration; no retries."""
        if (not all(isinstance(s, str) and s for s in (
                    owner_id, conversation_id, workspace_ref, run_ref))
                or not isinstance(artifact_ref, LineageArtifactRef)
                or not isinstance(source_record, CanonicalArtifactRecord)
                or not isinstance(intent, ConnectorWriteIntent)
                or not isinstance(now, datetime) or now.tzinfo is None):
            raise DurableArtifactCompletionError("trusted output operation context required")
        if (source_record.artifact_id != artifact_ref.artifact_id
                or source_record.integrity_ref != artifact_ref.integrity_ref
                or source_record.workspace_ref != workspace_ref
                or source_record.run_ref != run_ref
                or source_record.lifecycle is ArtifactLifecycle.DURABLE
                or source_record.media_type not in (
                    "application/pdf",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                or not source_record.filename.lower().endswith(
                    ".pdf" if source_record.media_type == "application/pdf" else ".xlsx"
                )):
            raise DurableArtifactCompletionError(
                "source artifact is not an approved XLSX/PDF canonical output"
            )
        try:
            owner_ok = await self._history.verify_owner_conversation_artifacts(
                owner_id, conversation_id
            )
            run = await self._history.get_claw_run(owner_id, run_ref)
        except Exception:
            raise DurableArtifactCompletionError("completed owner run unavailable") from None
        if (owner_ok is not True or not isinstance(run, dict)
                or run.get("run_id") != run_ref
                or run.get("conversation_id") != conversation_id
                or run.get("workspace_id") != workspace_ref
                or run.get("status") != "completed"):
            raise DurableArtifactCompletionError("completed owner run unavailable")

        # Existing adapter is the ONLY upload gate. An unknown provider result
        # is NOT accepted as a durable artifact just because it has a file ID.
        output = self._uploader.create_output(
            artifact_ref=artifact_ref, intent=intent,
            workspace_ref=workspace_ref, run_ref=run_ref, now=now,
        )
        if not isinstance(output, DriveUploadResult):
            raise DurableArtifactCompletionError("approved Drive upload receipt unavailable")
        artifact, receipt = output.artifact, output.receipt
        location = artifact.durable_location
        if (artifact.lifecycle is not ArtifactLifecycle.DURABLE
                or location is None or location.location_kind != "google_drive"
                or artifact.artifact_id != artifact_ref.artifact_id
                or artifact.integrity_ref != artifact_ref.integrity_ref
                or artifact.run_ref != run_ref
                or artifact.workspace_ref != workspace_ref
                or artifact.filename != source_record.filename
                or artifact.media_type != source_record.media_type
                or artifact.size_bytes != source_record.size_bytes
                or artifact.media_type not in (
                    "application/pdf",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                or receipt.connector_id != "google-drive"
                or receipt.binding_ref != intent.binding_ref
                or receipt.idempotency_key != intent.idempotency_key
                or receipt.target_ref != intent.target_ref
                or receipt.provider_operation_ref != location.location_ref):
            raise DurableArtifactCompletionError(
                "provider upload receipt and canonical artifact mismatch"
            )
        # Recheck current owner/run after external side effect. A revoked grant
        # or completed run changing state can never write to a foreign thread.
        try:
            still_owned = await self._history.verify_owner_conversation_artifacts(
                owner_id, conversation_id
            )
            recent = await self._history.get_claw_run(owner_id, run_ref)
            if (still_owned is not True or not isinstance(recent, dict)
                    or recent.get("conversation_id") != conversation_id
                    or recent.get("workspace_id") != workspace_ref
                    or recent.get("status") != "completed"):
                raise DurableArtifactCompletionError("owner scope changed after upload")
            registered = await self._history.register_owner_conversation_artifact(
                user_id=owner_id, conversation_id=conversation_id,
                workspace_ref=workspace_ref, artifact=artifact,
            )
        except Exception:
            raise DurableArtifactCompletionError(
                "upload may have succeeded but durable index registration unverified; no retry"
            ) from None
        if registered is not True:
            raise DurableArtifactCompletionError(
                "upload may have succeeded but durable index registration refused; no retry"
            )
        return DurableArtifactRegistration(
            artifact_id=artifact.artifact_id,
            integrity_ref=artifact.integrity_ref,
            source_run_ref=run_ref,
            stored_in_conversation_index=True,
        )


# Neither a provider nor a grant is created or activated by importing this.
PRODUCTION_DRIVE_OUTPUT_PIPELINE_ACTIVATED = False
