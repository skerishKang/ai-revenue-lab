"""#3933 owner/workspace/workcopy exact WRITE consent + private R2 revision."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_workspace_storage import MemoryMetadata, MemoryR2
from test_3933_web_quote_xlsx_editor import quote_fixture

from app.workspace_storage import (
    WorkspaceDocumentStore, WorkspaceStorageAccessError, WorkspaceStorageError,
)

OWNER = "usr_quote_owner"
WORKSPACE = "owner:usr_quote_owner"
RUN = "run_web_quote_one"


async def fixture():
    metadata, r2 = MemoryMetadata(), MemoryR2()
    store = WorkspaceDocumentStore(metadata, r2)
    input_bytes = quote_fixture()
    source = await store.put_web_xlsx(
        tenant_id=WORKSPACE, owner_id=OWNER, workspace_id=WORKSPACE,
        filename="test-quote.xlsx", body=input_bytes,
    )
    copy = await store.create_approved_web_xlsx_workcopy(
        tenant_id=WORKSPACE, owner_id=OWNER, workspace_id=WORKSPACE,
        source_document_id=source["document_id"],
        expected_source_sha256=source["source_sha256"],
        run_id=RUN, grant_verifier=lambda **kwargs: True,
    )
    return store, metadata, r2, source, copy, input_bytes


def scope(source, copy, **overrides):
    return dict(
        tenant_id=WORKSPACE, owner_id=OWNER, workspace_id=WORKSPACE,
        run_id=RUN, source_document_id=source["document_id"],
        expected_source_sha256=source["source_sha256"],
        workcopy_document_id=copy["workcopy_document_id"],
        school_name="광주대학교", supply_amount=99_200_000,
        **overrides,
    )


@pytest.mark.asyncio
async def test_authorized_p01_write_revision_is_distinct_and_source_unchanged():
    store, db, r2, source, copy, raw = await fixture()
    seen = []
    async def exact_authority(**kwargs):
        seen.append(kwargs)
        return (
            kwargs["owner_id"] == OWNER and kwargs["workspace_id"] == WORKSPACE
            and kwargs["source_document_id"] == source["document_id"]
            and kwargs["source_sha256"] == source["source_sha256"]
            and kwargs["workcopy_document_id"] == copy["workcopy_document_id"]
            and kwargs["workcopy_sha256"] == copy["workcopy_sha256"]
            and kwargs["operation"] == "xlsx.quote.revise_workcopy"
            and len(kwargs["edit_sha256"]) == 64
        )
    original_key = db.rows[source["document_id"]].object_key
    copy_key = db.rows[copy["workcopy_document_id"]].object_key
    result = await store.create_authorized_web_quote_revision(
        **scope(source, copy), write_grant_verifier=exact_authority,
    )
    assert len(seen) == 1
    assert result["revised_xlsx_created"] is True
    assert result["pdf_exported"] is False
    assert result["vat_amount"] == 9_920_000
    assert result["total_amount"] == 109_120_000
    assert result["original_overwritten"] is False
    record = db.rows[result["revision_document_id"]]
    assert "/web-office-revisions/" in record.object_key
    assert r2.objects[original_key] == r2.objects[copy_key] == raw
    revised = r2.objects[record.object_key]
    assert revised != raw
    assert hashlib.sha256(revised).hexdigest() == result["revision_sha256"]
    assert len(r2.objects) == len(db.rows) == 3
    assert await store.get_web_xlsx_metadata(
        tenant_id=WORKSPACE, owner_id=OWNER, workspace_id=WORKSPACE,
        document_id=result["revision_document_id"],
    ) is None


@pytest.mark.asyncio
async def test_missing_or_denied_separate_write_grant_prevents_processing_copy_read():
    store, db, r2, source, copy, raw = await fixture()
    before = len(r2.objects)
    for verifier in (None, lambda **kwargs: False, lambda **kwargs: 1):
        with pytest.raises(WorkspaceStorageAccessError):
            await store.create_authorized_web_quote_revision(
                **scope(source, copy), write_grant_verifier=verifier,
            )
        assert len(r2.objects) == before


@pytest.mark.asyncio
async def test_foreign_or_wrong_run_copy_fails_before_grant():
    store, db, r2, source, copy, raw = await fixture()
    seen = []
    def verifier(**kw):
        seen.append(kw)
        return True
    for changed in (
        {"owner_id": "usr_attacker"},
        {"workspace_id": "owner:usr_attacker"},
        {"run_id": "run_attacker"},
        {"source_document_id": "doc_" + "f" * 32},
        {"expected_source_sha256": "f" * 64},
        {"workcopy_document_id": "doc_" + "e" * 32},
    ):
        values = scope(source, copy)
        values.update(changed)
        with pytest.raises(WorkspaceStorageAccessError):
            await store.create_authorized_web_quote_revision(
                **values, write_grant_verifier=verifier,
            )
    assert seen == []
    assert len(r2.objects) == 2


@pytest.mark.asyncio
async def test_mutated_copy_bytes_and_unsupported_template_not_saved():
    store, db, r2, source, copy, raw = await fixture()
    key = db.rows[copy["workcopy_document_id"]].object_key
    r2.objects[key] = b"tampered"
    with pytest.raises(WorkspaceStorageError, match="bytes changed"):
        await store.create_authorized_web_quote_revision(
            **scope(source, copy), write_grant_verifier=lambda **kwargs: True,
        )
    assert len(r2.objects) == 2


@pytest.mark.asyncio
async def test_metadata_write_failure_rolls_back_only_revision_r2():
    store, db, r2, source, copy, raw = await fixture()
    original_keys = set(r2.objects)
    async def broken(_):
        raise RuntimeError("synthetic D1 outage")
    db.insert = broken
    with pytest.raises(WorkspaceStorageError, match="revision storage unavailable"):
        await store.create_authorized_web_quote_revision(
            **scope(source, copy), write_grant_verifier=lambda **kwargs: True,
        )
    assert set(r2.objects) == original_keys
    assert len(db.rows) == 2
    assert r2.delete_calls and r2.delete_calls[-1] not in original_keys
