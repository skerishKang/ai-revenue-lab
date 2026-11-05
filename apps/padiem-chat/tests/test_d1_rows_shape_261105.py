"""#5568 follow-on: the statement result shape must not decide whether rows exist.

The operating 컴2 host (`app.d1_sqlite.SqliteD1`) answers `prepare(sql).all()` with a
bare list of row dicts. Cloudflare's D1 answers the same call with a result object
carrying `results`. The PDF → Markdown ledger read only the second shape, so on
Production every job and item was written, then invisible: `list_jobs` and
`list_items` returned nothing and the owner never got a '변환 실행' button.

These tests run the same reads against both host shapes, including the shipped
migration, so a shape-specific reader cannot pass by testing one host only.
"""
from __future__ import annotations

from typing import ClassVar

import pytest
from test_5568_document_convert_routes import (
    OWNER,
    FakeD1,
    MemoryR2,
    build_client,
    open_job,
    pdf_bytes,
    upload,
)

from app.b66_template_source import D1B66TemplateSourceMetadataStore
from app.d1_rows import rows_from_result
from app.document_convert_store import D1DocumentConvertStore

SHAPES = ("sqlite", "d1")
TEN_PAGE_PDF = pdf_bytes(texts=[f"page {index} text 12345" for index in range(1, 11)])


class _ShapedStatement:
    def __init__(self, db, sql, params=()):
        self.db, self.sql, self.params = db, sql, params

    def bind(self, *params):
        return _ShapedStatement(self.db, self.sql, params)

    async def first(self):
        row = self.db.conn.execute(self.sql, self.params).fetchone()
        return dict(row) if row else None

    async def all(self):
        rows = [dict(row) for row in self.db.conn.execute(self.sql, self.params).fetchall()]
        return rows if self.db.shape == "sqlite" else {"results": rows}

    async def run(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return {"meta": {"changes": cursor.rowcount}, "results": []}


class ShapedD1(FakeD1):
    """The shipped 066 migration, answering `.all()` like one host or the other."""

    def __init__(self, shape):
        super().__init__()
        if shape not in SHAPES:
            raise ValueError(shape)
        self.shape = shape

    def prepare(self, sql):
        return _ShapedStatement(self, sql)


def test_rows_from_result_normalizes_every_host_shape():
    class _CarriesResults:
        results: ClassVar[list] = [{"id": "carried"}]

    assert rows_from_result(None) == []
    assert rows_from_result({"results": [{"id": "a"}]}) == [{"id": "a"}]
    assert rows_from_result({"results": None}) == []
    assert rows_from_result(_CarriesResults()) == [{"id": "carried"}]
    assert rows_from_result([{"id": "bare"}, {"id": "list"}]) == [{"id": "bare"}, {"id": "list"}]
    assert rows_from_result(({"id": "tuple"},)) == [{"id": "tuple"}]
    assert rows_from_result([]) == []
    assert rows_from_result("not-a-result") == []


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", SHAPES)
async def test_ledger_lists_job_and_item_after_upload_in_both_host_shapes(shape):
    """The load-bearing regression: a written ledger has to come back readable."""
    store = D1DocumentConvertStore(ShapedD1(shape))
    job = await store.create_job(OWNER, mode="verify")
    item = await store.add_item(OWNER, job.id, name="Business35_Master_Proposal_10p.pdf", page_count=10)

    jobs = await store.list_jobs(OWNER, limit=50)
    items = await store.list_items(OWNER, job.id)

    assert [listed.id for listed in jobs] == [job.id]
    assert jobs[0].item_count == 1
    assert [found.name for found in items] == [item.name]
    assert items[0].page_count == 10
    assert items[0].status == "queued"


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", SHAPES)
async def test_owner_can_list_run_and_delete_a_ten_page_conversion_in_both_host_shapes(shape):
    """The Production journey the shape bug broke: list → 변환 실행 → 일치도 → 삭제."""
    client, app = await build_client(d1=ShapedD1(shape), r2=MemoryR2())
    # The operating host lifts the migration pause through this state flag, which is
    # how Production reaches the ledger at all; no constant is patched here.
    app.state.pdfmd_com2_ready = True
    async with client:
        job_id = await open_job(client, mode="verify")
        uploaded = await upload(client, job_id, TEN_PAGE_PDF, name="Business35_Master_Proposal_10p.pdf")
        assert uploaded.status_code == 201, uploaded.text

        listed = await client.get("/api/document-conversions?limit=50")
        detail = await client.get(f"/api/document-conversions/{job_id}")
        assert listed.status_code == 200 and detail.status_code == 200
        jobs = listed.json()["jobs"]
        assert [job["id"] for job in jobs] == [job_id], jobs
        assert jobs[0]["mode"] == "verify"
        items = detail.json()["items"]
        assert [item["name"] for item in items] == ["Business35_Master_Proposal_10p.pdf"], items

        run = await client.post(f"/api/document-conversions/items/{items[0]['id']}/run")
        assert run.status_code == 200, run.text
        converted = run.json()["item"]
        assert converted["page_count"] == 10
        assert len(converted["report"]["pages"]) == 10
        assert len(converted["report"]["agreement"]) == 10
        assert all(row["character_coverage"] == 1.0 for row in converted["report"]["agreement"])

        deleted = await client.delete(f"/api/document-conversions/items/{converted['id']}")
        assert deleted.status_code == 200, deleted.text
        after = await client.get("/api/document-conversions?limit=50")

    assert after.json()["jobs"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", SHAPES)
async def test_a_ledger_without_items_leaves_the_owners_list_in_both_host_shapes(shape):
    store = D1DocumentConvertStore(ShapedD1(shape))
    job = await store.create_job(OWNER, mode="fast")
    item = await store.add_item(OWNER, job.id, name="one.pdf", page_count=1)
    second = await store.create_job(OWNER, mode="fast")
    await store.add_item(OWNER, second.id, name="two.pdf", page_count=1)

    assert await store.delete_item(OWNER, item.id) is True

    jobs = await store.list_jobs(OWNER, limit=50)
    assert [listed.id for listed in jobs] == [second.id]
    # The empty ledger is still addressable by id while a job is in flight.
    assert await store.get_job(OWNER, job.id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", SHAPES)
async def test_template_metadata_store_reads_rows_in_both_host_shapes(shape):
    """The same shape-only reader lived in B66 template source custody (#3884)."""
    store = D1B66TemplateSourceMetadataStore(ShapedD1(shape))
    rows = await store._all("SELECT id FROM users ORDER BY id")
    assert rows, shape
