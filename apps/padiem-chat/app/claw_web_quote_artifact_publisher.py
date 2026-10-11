"""#3933 Hark WEB-FIRST: register a *completed* approved XLSX edit in Claw history.

This is the missing narrow composition between the independent P01 WRITE
receipt and the existing durable owner/conversation artifact index. It is not
a Google Drive uploader, a Telegram sender, a new authorization mechanism,
or a shortcut to read the resulting file without a separate P01 grant.

The edit/owner-decision D1 commits are the authority to call this function.
On an uncertain index result we return False (not a fake successful follow-up)
and NEVER repeat the approved WRITE or re-create a revision.
"""
from __future__ import annotations

import hashlib
import inspect
import re
from datetime import datetime, timezone

from kagent.artifact_registration import (
    ArtifactLifecycle, ArtifactLocation, register_canonical_artifact,
)
from .workspace_storage import XLSX_MEDIA_TYPE

_DOC = re.compile(r"doc_[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


async def _await(result):
    return await result if inspect.isawaitable(result) else result


async def register_completed_web_quote_revision(
    *, history: object, documents: object,
    owner_id: str, workspace_id: str, run_id: str,
    revision: dict, trusted_revised_bytes: bytes,
) -> bool:
    """Post-commit indexing only, from trusted server context; never browser JSON.

    A valid D1 receipt, matching actual private R2 bytes, owner-conversation
    membership and an existing live run are all required. A completed run
    enables the pre-existing canonical D1 index's INSERT..SELECT constraint.
    No external connector, additional grant, paid call or unbounded retry.
    """
    required_history = (
        "get_claw_run", "verify_owner_conversation_artifacts",
        "update_claw_run_status", "register_owner_conversation_artifact",
    )
    if (any(not callable(getattr(history, name, None)) for name in required_history)
            or not callable(getattr(documents, "get_for_tenant", None))
            or not isinstance(revision, dict)
            or type(trusted_revised_bytes) is not bytes
            or not isinstance(owner_id, str) or not owner_id
            or not isinstance(workspace_id, str) or not workspace_id
            or not isinstance(run_id, str) or not run_id):
        return False
    doc_id = revision.get("revision_document_id")
    sha = revision.get("revision_sha256")
    if (not isinstance(doc_id, str) or not _DOC.fullmatch(doc_id)
            or not isinstance(sha, str) or not _SHA.fullmatch(sha)
            or hashlib.sha256(trusted_revised_bytes).hexdigest() != sha
            or revision.get("revised_xlsx_created") is not True
            or revision.get("original_overwritten") is not False):
        return False

    try:
        run = await _await(history.get_claw_run(owner_id, run_id))
        if (not isinstance(run, dict)
                or run.get("run_id") != run_id
                or run.get("workspace_id") != workspace_id
                or run.get("status") != "running"
                or not isinstance(run.get("conversation_id"), str)
                or not run["conversation_id"]):
            return False
        conversation_id = run["conversation_id"]
        if await _await(history.verify_owner_conversation_artifacts(
                owner_id, conversation_id)) is not True:
            return False

        item = await _await(documents.get_for_tenant(
            tenant_id=workspace_id, document_id=doc_id))
        if not isinstance(item, tuple) or len(item) != 2:
            return False
        metadata, persisted = item
        expected_key = (
            f"workspaces/{workspace_id}/claw/web-office-revisions/"
            f"{owner_id}/{workspace_id}/{run_id}/"
            f"{revision['source_document_id']}/"
            f"{revision['workcopy_document_id']}/"
            f"{doc_id}/{sha}"
        )
        if (type(persisted) is not bytes
                or persisted != trusted_revised_bytes
                or getattr(metadata, "document_id", None) != doc_id
                or getattr(metadata, "tenant_id", None) != workspace_id
                or getattr(metadata, "object_key", None) != expected_key
                or getattr(metadata, "media_type", None) != XLSX_MEDIA_TYPE
                or getattr(metadata, "byte_length", None) != len(persisted)
                or getattr(metadata, "expires_at", datetime.min.replace(
                    tzinfo=timezone.utc)) <= datetime.now(timezone.utc)):
            return False

        record = register_canonical_artifact(
            artifact_id=doc_id,
            artifact_kind="output.xlsx",
            filename="hark-revised-quote.xlsx",
            media_type=XLSX_MEDIA_TYPE,
            size_bytes=len(persisted),
            integrity_ref=sha,
            lifecycle=ArtifactLifecycle.DURABLE,
            workspace_ref=workspace_id,
            run_ref=run_id,
            durable_location=ArtifactLocation(
                location_kind="r2_bucket", location_ref=expected_key),
        )
        # The work is complete ONLY after the approved write was durably
        # committed by the caller. This status transition is not a new grant.
        if await _await(history.update_claw_run_status(
                owner_id, run_id, "completed",
                "승인된 XLSX 수정본 저장 완료")) is not True:
            return False
        return (await _await(history.register_owner_conversation_artifact(
            user_id=owner_id, conversation_id=conversation_id,
            workspace_ref=workspace_id, artifact=record))) is True
    except Exception:
        # Any unavailable D1 index/metadata/race is NOT an approved artifact
        # reference. Keep the already-authorized revision accessible through
        # the original selection-scoped download path; never re-execute WRITE.
        return False
