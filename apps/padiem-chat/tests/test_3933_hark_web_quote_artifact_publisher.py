"""#3933 tests: actual approved WEB-FIRST XLSX output -> existing Claw index."""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app.claw_web_quote_artifact_publisher import register_completed_web_quote_revision
from app.workspace_storage import XLSX_MEDIA_TYPE

OWNER = "usr_0123456789abcdef0123456789abcdef"
WORKSPACE = "ws_auth_scope_1"
RUN = "claw_0123456789abcdef0123456789abcdef"
CHAT = "chat_0123456789abcdef0123456789abcdef"
SOURCE = "doc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
COPY = "doc_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
REVISED = "doc_cccccccccccccccccccccccccccccccc"
BODY = b"trusted-synthetic-xlsx-output-for-test"


@dataclass
class Metadata:
    document_id: str
    tenant_id: str
    object_key: str
    media_type: str
    byte_length: int
    expires_at: datetime


def revision_fixture():
    sha = hashlib.sha256(BODY).hexdigest()
    revision = {
        "source_document_id": SOURCE,
        "workcopy_document_id": COPY,
        "revision_document_id": REVISED,
        "revision_sha256": sha,
        "revised_xlsx_created": True,
        "original_overwritten": False,
    }
    key = (f"workspaces/{WORKSPACE}/claw/web-office-revisions/"
           f"{OWNER}/{WORKSPACE}/{RUN}/{SOURCE}/{COPY}/{REVISED}/{sha}")
    metadata = Metadata(
        document_id=REVISED, tenant_id=WORKSPACE, object_key=key,
        media_type=XLSX_MEDIA_TYPE, byte_length=len(BODY),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    return revision, metadata


class FakeDocuments:
    def __init__(self, metadata, blob=BODY):
        self.metadata = metadata
        self.blob = blob
        self.calls = []

    async def get_for_tenant(self, **kwargs):
        self.calls.append(kwargs)
        return self.metadata, self.blob


class FakeHistory:
    def __init__(self):
        self.run = {
            "run_id": RUN, "workspace_id": WORKSPACE,
            "conversation_id": CHAT, "status": "running",
        }
        self.owner_ok = True
        self.updated = []
        self.registered = []
        self.registration_works = True

    async def get_claw_run(self, owner_id, run_id):
        if owner_id != OWNER or run_id != RUN:
            return None
        return self.run

    async def verify_owner_conversation_artifacts(self, user_id, conversation_id):
        return self.owner_ok and user_id == OWNER and conversation_id == CHAT

    async def update_claw_run_status(self, owner_id, run_id, status, summary):
        self.updated.append((owner_id, run_id, status, summary))
        self.run["status"] = status
        return True

    async def register_owner_conversation_artifact(self, **kwargs):
        self.registered.append(kwargs)
        return self.registration_works


async def publish(history=None, documents=None, revision=None, body=BODY,
                  owner=OWNER, workspace=WORKSPACE):
    if revision is None:
        revision, metadata = revision_fixture()
    else:
        _, metadata = revision_fixture()
    return await register_completed_web_quote_revision(
        history=history if history is not None else FakeHistory(),
        documents=documents if documents is not None else FakeDocuments(metadata),
        owner_id=owner, workspace_id=workspace, run_id=RUN,
        revision=revision, trusted_revised_bytes=body,
    )


def test_real_canonical_artifact_reference_after_one_verified_write():
    history = FakeHistory()
    revision, metadata = revision_fixture()
    docs = FakeDocuments(metadata)
    assert asyncio.run(publish(history=history, documents=docs)) is True
    assert len(history.updated) == 1
    assert history.run["status"] == "completed"
    assert len(history.registered) == 1
    item = history.registered[0]
    assert (item["user_id"], item["conversation_id"], item["workspace_ref"]) == (
        OWNER, CHAT, WORKSPACE,
    )
    record = item["artifact"]
    assert record.artifact_id == REVISED
    assert record.integrity_ref == revision["revision_sha256"]
    assert record.size_bytes == len(BODY)
    assert record.lifecycle.value == "durable"
    assert record.run_ref == RUN
    assert record.workspace_ref == WORKSPACE
    assert record.durable_location.location_kind == "r2_bucket"
    assert record.durable_location.location_ref == metadata.object_key
    assert "location_ref" not in record.public_projection()["durable_location"]
    assert docs.calls == [{"tenant_id": WORKSPACE, "document_id": REVISED}]
    assert asyncio.run(publish(history=history, documents=docs)) is False
    assert len(history.registered) == 1


@pytest.mark.parametrize("defect", [
    "foreign_owner", "bad_workspace", "not_running", "bad_conversation",
    "unowned_conversation", "bad_sha", "bad_bytes", "bad_object_key",
    "bad_media_type", "expired", "missing_receipt", "index_unavailable",
])
def test_no_forged_completed_artifact_or_foreign_owner_index(defect):
    history = FakeHistory()
    revision, metadata = revision_fixture()
    documents = FakeDocuments(metadata)
    owner = OWNER
    workspace = WORKSPACE
    body = BODY
    if defect == "foreign_owner":
        owner = "usr_foreign"
    elif defect == "bad_workspace":
        workspace = "ws_foreign"
    elif defect == "not_running":
        history.run["status"] = "denied"
    elif defect == "bad_conversation":
        history.run["conversation_id"] = ""
    elif defect == "unowned_conversation":
        history.owner_ok = False
    elif defect == "bad_sha":
        revision["revision_sha256"] = "0" * 64
    elif defect == "bad_bytes":
        body = b"another-document"
    elif defect == "bad_object_key":
        documents.metadata.object_key = "workspaces/other/forged"
    elif defect == "bad_media_type":
        documents.metadata.media_type = "application/pdf"
    elif defect == "expired":
        documents.metadata.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    elif defect == "missing_receipt":
        revision["revised_xlsx_created"] = False
    elif defect == "index_unavailable":
        history.register_owner_conversation_artifact = None

    assert asyncio.run(publish(
        history=history, documents=documents, revision=revision,
        body=body, owner=owner, workspace=workspace,
    )) is False
    assert history.updated == []
    assert history.registered == []


def test_successful_edit_with_failed_d1_index_reports_not_indexed_no_retry():
    history = FakeHistory()
    history.registration_works = False
    assert asyncio.run(publish(history=history)) is False
    assert history.run["status"] == "completed"
    assert len(history.updated) == 1
    assert len(history.registered) == 1
    # A later caller cannot replay/redo the already-approved WRITE.
    assert asyncio.run(publish(history=history)) is False
    assert len(history.updated) == 1
