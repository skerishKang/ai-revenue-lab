"""#3580 fail-closed backend workcopy source boundary, no public route or provider calls."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
from zipfile import ZipFile

import pytest

from app.workspace_storage import (
    WorkspaceDocumentStore, WorkspaceStorageAccessError, WorkspaceStorageError,
)
from test_workspace_storage import MemoryMetadata, MemoryR2


OWNER = "usr_web_xlsx_owner"
WORKSPACE = "ws_web_xlsx_one"
RUN = "run_web_xlsx_1"
OTHER = "usr_web_xlsx_foreign"


def _workbook() -> bytes:
    out = BytesIO()
    with ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/workbook.xml", '<?xmlxml version="1.0"?><workbook/>'.replace("<?xmlxml", "<?xml"))
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet><sheetData/></worksheet>')
    return out.getvalue()


async def setup():
    metadata, r2 = MemoryMetadata(), MemoryR2()
    store = WorkspaceDocumentStore(metadata, r2)
    body = _workbook()
    original = await store.put_web_xlsx(
        tenant_id=WORKSPACE, owner_id=OWNER, workspace_id=WORKSPACE,
        filename="synthetic.xlsx", body=body,
    )
    return store, metadata, r2, original, body


def kwargs(original, **overrides):
    return {
        "tenant_id": WORKSPACE, "owner_id": OWNER,
        "workspace_id": WORKSPACE, "source_document_id": original["document_id"],
        "expected_source_sha256": original["source_sha256"],
        "run_id": RUN, **overrides,
    }


@pytest.mark.asyncio
async def test_authorized_workcopy_is_distinct_r2_object_and_original_unchanged():
    store, metadata, r2, original, payload = await setup()
    seen = []
    async def verified_grant(**scope):
        seen.append(scope)
        return scope == dict(
            owner_id=OWNER, workspace_id=WORKSPACE, run_id=RUN,
            document_id=original["document_id"],
            source_sha256=original["source_sha256"],
            operation="read_for_workcopy",
        )
    original_key = metadata.rows[original["document_id"]].object_key
    result = await store.create_approved_web_xlsx_workcopy(
        **kwargs(original), grant_verifier=verified_grant,
    )
    assert len(seen) == 1
    assert result["workcopy_created"] is True
    assert result["source_document_id"] == original["document_id"]
    assert result["source_sha256"] == result["workcopy_sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["workcopy_document_id"] != original["document_id"]
    copy_row = metadata.rows[result["workcopy_document_id"]]
    assert "/web-office-workcopies/" in copy_row.object_key
    assert f"/{OWNER}/{WORKSPACE}/{RUN}/{original['document_id']}/" in copy_row.object_key
    assert r2.objects[copy_row.object_key] == payload
    assert r2.objects[original_key] == payload
    assert await store.get_web_xlsx_metadata(
        tenant_id=WORKSPACE, owner_id=OWNER, workspace_id=WORKSPACE,
        document_id=result["workcopy_document_id"],
    ) is None
    sources = await store.get_web_xlsx(
        tenant_id=WORKSPACE, owner_id=OWNER, workspace_id=WORKSPACE,
        document_id=original["document_id"],
    )
    assert sources is not None and sources[1] == payload


@pytest.mark.asyncio
async def test_denied_or_missing_grant_never_reads_original_r2_or_writes_copy():
    store, metadata, r2, original, payload = await setup()
    original_key = metadata.rows[original["document_id"]].object_key
    for verifier in (None, lambda **scope: False, lambda **scope: 1):
        with pytest.raises(WorkspaceStorageAccessError):
            await store.create_approved_web_xlsx_workcopy(
                **kwargs(original), grant_verifier=verifier,
            )
        assert list(r2.objects) == [original_key]
        assert len(metadata.rows) == 1


@pytest.mark.asyncio
async def test_wrong_owner_or_digest_rejected_before_any_grant_or_byte_read():
    store, metadata, r2, original, payload = await setup()
    seen = []
    def verifier(**scope):
        seen.append(scope)
        return True
    for wrong in (
        {"owner_id": OTHER},
        {"workspace_id": "ws_other"},
        {"expected_source_sha256": "f" * 64},
        {"source_document_id": "doc_" + "f" * 32},
    ):
        with pytest.raises(WorkspaceStorageAccessError):
            await store.create_approved_web_xlsx_workcopy(
                **kwargs(original, **wrong), grant_verifier=verifier,
            )
    assert seen == []
    assert len(metadata.rows) == len(r2.objects) == 1


@pytest.mark.asyncio
async def test_original_r2_tampering_after_grant_prevents_copy():
    store, metadata, r2, original, payload = await setup()
    original_key = metadata.rows[original["document_id"]].object_key
    r2.objects[original_key] = b"changed data"
    with pytest.raises(WorkspaceStorageError, match="digest mismatch|length mismatch"):
        await store.create_approved_web_xlsx_workcopy(
            **kwargs(original), grant_verifier=lambda **scope: True,
        )
    assert len(metadata.rows) == len(r2.objects) == 1


@pytest.mark.asyncio
async def test_expired_original_and_db_write_rollback_fail_closed():
    store, metadata, r2, original, payload = await setup()
    doc = original["document_id"]
    metadata.rows[doc] = replace(
        metadata.rows[doc],
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    with pytest.raises(WorkspaceStorageAccessError):
        await store.create_approved_web_xlsx_workcopy(
            **kwargs(original), grant_verifier=lambda **scope: True,
        )
    assert len(r2.objects) == len(metadata.rows) == 1

@pytest.mark.asyncio
async def test_failed_metadata_insert_removes_only_new_r2_copy_not_original():
    store, metadata, r2, original, payload = await setup()
    source_key = metadata.rows[original["document_id"]].object_key

    async def failing_insert(_meta):
        raise RuntimeError("simulated D1 outage")

    metadata.insert = failing_insert
    with pytest.raises(WorkspaceStorageError, match="workcopy write failed"):
        await store.create_approved_web_xlsx_workcopy(
            **kwargs(original), grant_verifier=lambda **scope: True,
        )
    assert list(r2.objects) == [source_key]
    assert r2.objects[source_key] == payload
    assert len(metadata.rows) == 1
    assert len(r2.delete_calls) == 1
    assert r2.delete_calls[0] != source_key
