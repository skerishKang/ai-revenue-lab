"""#5728 — the REAL store's create_file must accept image originals.

The merged slice routed image uploads through D1ProjectFileStore.create_file,
whose text-document validation (validate_document_fields) rejects every
image media type — the route-level tests passed because their in-memory
store fakes bypass this method, while the production Worker 422s every
upload ("현재는 TXT, Markdown, CSV, JSON 문서만 지원합니다."). These tests
drive the REAL D1ProjectFileStore against a minimal D1-binding fake.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.project_files import D1ProjectFileStore, ProjectFileRecord


class _FakeStatement:
    def __init__(self, sql: str, recorder: list[tuple[str, Any]]):
        self.sql = sql
        self.recorder = recorder

    def bind(self, *values):
        self.recorder.append((self.sql, values))
        return self

    async def first(self):
        return None

    async def run(self):
        # Mirror the route's expectation: the ownership-conditional INSERT
        # RETURNING id must look like it wrote one row.
        return {"results": [{"id": "file_ok"}]}


class _FakeD1:
    def __init__(self):
        self.statements: list[tuple[str, Any]] = []

    def prepare(self, sql: str):
        return _FakeStatement(sql, self.statements)


def _statement_values(recorder: list[tuple[str, Any]], needle: str) -> tuple:
    for sql, values in recorder:
        if needle in sql:
            return values
    raise AssertionError(f"no statement containing {needle!r}")


@pytest.mark.asyncio
async def test_image_original_creates_a_record_without_text_validation():
    d1 = _FakeD1()
    store = D1ProjectFileStore(d1)
    record = await store.create_file("u1", "p1", "행사 사진.png", "image/png", "")
    assert isinstance(record, ProjectFileRecord)
    assert record.media_type == "image/png"
    assert record.content_text == ""
    assert record.content_chars == 0
    insert = _statement_values(d1.statements, "INSERT INTO project_files")
    # (fid, user_id, name, media_type, text, chars, now, now, pid, uid)
    assert insert[3] == "image/png"
    assert insert[4] == ""
    assert insert[5] == 0


@pytest.mark.asyncio
async def test_text_document_still_goes_through_document_validation():
    d1 = _FakeD1()
    store = D1ProjectFileStore(d1)
    with pytest.raises(Exception) as exc:
        await store.create_file("u1", "p1", "메모.png", "image/png", "", source_media_type="image/jpeg")
    # A mismatched source_media_type is refused before anything else.
    assert "source_media_type" in str(exc.value)

    # A text upload keeps its document normalization (an unsupported text
    # media type must still be refused exactly as before).
    from app.documents import DocumentValidationError

    with pytest.raises(DocumentValidationError):
        await store.create_file("u1", "p1", "파일.xyz", "application/xyz", "본문")
