"""Durable D1 evidence storage port acceptance tests for #1750 E5B-S4b.

The fake D1 binding mirrors the existing continuation_d1 test fake exactly:
``prepare(sql) -> statement.bind(*params)`` with awaitable ``first``/``run``
over an in-process dict. No network, filesystem or provider access.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.document_evidence_projection import EvidenceStorageProjection  # noqa: E402
from app.evidence_storage_d1 import (  # noqa: E402
    MAX_EVIDENCE_RECORD_CHARS,
    CloudflareD1EvidenceStoragePort,
)
from app.trusted_document_resolver import ResolvedDocumentMeta  # noqa: E402
from padiem_ai_core.document_normalization import NormalizedDocument  # noqa: E402
from padiem_ai_core.document_semantics import (  # noqa: E402
    DocumentLocator,
    DocumentSegment,
    LocatorKind,
    LocatorPrecision,
)

REF = "att_s4bdoc000000000c"
LOCATOR = "opaque-blob-locator-101"
EVIDENCE_ID = "s4bevidence0000001"
BODY = "durable evidence body with a tail marker TAILNOTINREPR-44120"
SCOPE = {"app_id": "app.revenue", "subject_id": "user.42", "tenant_id": "tenant.a"}


def _meta() -> ResolvedDocumentMeta:
    return ResolvedDocumentMeta(
        media_type="text/plain",
        name="notes.txt",
        byte_size=len(BODY.encode("utf-8")),
        **SCOPE,
    )


def _document(text: str = BODY) -> NormalizedDocument:
    return NormalizedDocument(
        name="notes.txt",
        media_type="text/plain",
        text=text,
        byte_size=len(text.encode("utf-8")),
    )


def _projection(
    document: NormalizedDocument | None = None,
    *,
    evidence_id: str = EVIDENCE_ID,
) -> EvidenceStorageProjection:
    return EvidenceStorageProjection.from_resolver_result(
        REF,
        document if document is not None else _document(),
        _meta(),
        f"evidence://{REF}",
        evidence_id=evidence_id,
    )


class FakeStatement:
    def __init__(self, db: "FakeD1", sql: str) -> None:
        self.db = db
        self.sql = " ".join(sql.split())
        self.params = ()

    def bind(self, *params):
        self.params = params
        return self

    async def run(self):
        if self.sql.startswith("INSERT INTO padiem_engine_evidence"):
            evidence_id, document_json, retention_json, created_at = self.params
            if evidence_id in self.db.rows:
                raise AssertionError("duplicate primary key")
            self.db.rows[evidence_id] = {
                "evidence_id": evidence_id,
                "document_json": document_json,
                "retention_json": retention_json,
                "created_at": created_at,
            }
            return {"success": True}
        raise AssertionError(f"unexpected run SQL: {self.sql}")

    async def first(self):
        if self.sql == "SELECT evidence_id FROM padiem_engine_evidence WHERE evidence_id=? LIMIT 1":
            (evidence_id,) = self.params
            return {"evidence_id": evidence_id} if evidence_id in self.db.rows else None
        if self.sql.startswith("SELECT evidence_id,document_json,retention_json,created_at FROM"):
            (evidence_id,) = self.params
            row = self.db.rows.get(evidence_id)
            return dict(row) if row else None
        raise AssertionError(f"unexpected first SQL: {self.sql}")


class FakeD1:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def prepare(self, sql: str) -> FakeStatement:
        return FakeStatement(self, sql)


def _port() -> tuple[CloudflareD1EvidenceStoragePort, FakeD1]:
    db = FakeD1()
    return CloudflareD1EvidenceStoragePort(db), db


# --- round-trip ----------------------------------------------------------------


def test_store_then_retrieve_round_trips_the_full_projection() -> None:
    port, _db = _port()
    projection = _projection()

    async def scenario() -> None:
        stored_id = await port.store(projection)
        assert stored_id == EVIDENCE_ID
        retrieved = await port.retrieve(EVIDENCE_ID)
        assert isinstance(retrieved, EvidenceStorageProjection)
        assert retrieved.evidence_id == projection.evidence_id
        assert retrieved.att_ref == REF
        assert retrieved.storage_locator == f"evidence://{REF}"
        assert retrieved.normalized_document.text == BODY
        assert retrieved.normalized_document.name == "notes.txt"
        assert retrieved.normalized_document.media_type == "text/plain"
        assert retrieved.normalized_document.byte_size == projection.normalized_document.byte_size
        assert retrieved.normalized_document.status is projection.normalized_document.status
        assert retrieved.document_locator.kind is LocatorKind.SECTION
        assert retrieved.created_at == projection.created_at

    asyncio.run(scenario())


def test_round_trip_preserves_multi_segment_provenance() -> None:
    segments = tuple(
        DocumentSegment(
            text=f"segment {index} body",
            order=index,
            locator=DocumentLocator(
                kind=LocatorKind.PARAGRAPH,
                value=f"paragraph:{index + 1}",
                precision=LocatorPrecision.EXACT,
            ),
        )
        for index in range(3)
    )
    text = "\n".join(segment.text for segment in segments)
    document = NormalizedDocument(
        name="notes.txt",
        media_type="text/plain",
        text=text,
        byte_size=len(text.encode("utf-8")),
        segments=segments,
        warnings=("bounded",),
    )
    port, _db = _port()

    async def scenario() -> None:
        stored = _projection(document)
        await port.store(stored)
        retrieved = await port.retrieve(EVIDENCE_ID)
        assert retrieved.normalized_document.segments == segments
        assert retrieved.normalized_document.warnings == ("bounded",)
        assert retrieved.document_locator == stored.document_locator

    asyncio.run(scenario())


# --- duplicate / unknown semantics ----------------------------------------------


def test_duplicate_evidence_id_is_rejected_with_valueerror() -> None:
    port, db = _port()

    async def scenario() -> None:
        await port.store(_projection())
        with pytest.raises(ValueError) as raised:
            await port.store(_projection())
        assert str(raised.value) == "evidence id already exists in this store"
        assert list(db.rows) == [EVIDENCE_ID]

    asyncio.run(scenario())


def test_unknown_or_invalid_evidence_id_raises_keyerror() -> None:
    port, _db = _port()

    async def scenario() -> None:
        with pytest.raises(KeyError):
            await port.retrieve("neverminted0000000")
        with pytest.raises(KeyError):
            await port.retrieve("")
        with pytest.raises(KeyError):
            await port.retrieve(None)

    asyncio.run(scenario())


def test_non_projection_store_is_rejected_without_touching_binding() -> None:
    port, db = _port()

    async def scenario() -> None:
        with pytest.raises(ValueError) as raised:
            await port.store({"evidence_id": EVIDENCE_ID})  # type: ignore[arg-type]
        assert str(raised.value) == "evidence storage accepts EvidenceStorageProjection only"
        assert db.rows == {}

    asyncio.run(scenario())


# --- payload guards --------------------------------------------------------------


def test_empty_document_payload_is_rejected() -> None:
    port, db = _port()
    empty_document = NormalizedDocument(name="empty.txt", media_type="text/plain", text="")

    async def scenario() -> None:
        with pytest.raises(ValueError) as raised:
            await port.store(_projection(empty_document))
        assert str(raised.value) == "evidence document payload must be non-empty"
        assert db.rows == {}

    asyncio.run(scenario())


def test_oversized_document_payload_is_rejected_before_any_write() -> None:
    port, db = _port()
    text = "x" * (MAX_EVIDENCE_RECORD_CHARS + 1)
    document = NormalizedDocument(
        name="huge.txt",
        media_type="text/plain",
        text=text,
        byte_size=len(text.encode("utf-8")),
        segments=(DocumentSegment(text="anchor", order=0),),
    )

    async def scenario() -> None:
        with pytest.raises(ValueError) as raised:
            await port.store(_projection(document))
        assert str(raised.value) == "evidence record exceeds the durable storage bound"
        assert db.rows == {}

    asyncio.run(scenario())


def test_missing_or_invalid_binding_fails_closed() -> None:
    with pytest.raises(ValueError) as raised:
        CloudflareD1EvidenceStoragePort(None)
    assert str(raised.value) == "evidence storage binding must provide prepare(sql)"
    with pytest.raises(ValueError):
        CloudflareD1EvidenceStoragePort(object())


def test_malformed_row_surfaces_a_constant_invalid_record_error() -> None:
    port, db = _port()

    async def scenario() -> None:
        await port.store(_projection())
        db.rows[EVIDENCE_ID]["document_json"] = "{not json"
        with pytest.raises(ValueError) as raised:
            await port.retrieve(EVIDENCE_ID)
        assert str(raised.value) == "evidence storage returned an invalid record"

    asyncio.run(scenario())


# --- redaction / leak surface ------------------------------------------------------


def test_port_repr_and_diagnostics_never_render_body_ref_or_locator() -> None:
    port, db = _port()

    async def scenario() -> None:
        await port.store(_projection())
        surfaces = [repr(port)]
        try:
            await port.store(_projection())
        except ValueError as exc:
            surfaces.append(str(exc))
        try:
            await port.retrieve("neverminted0000000")
        except KeyError as exc:
            surfaces.append(str(exc))
        db.rows["broken"] = {
            "evidence_id": "broken",
            "document_json": "{bad",
            "retention_json": "{bad",
            "created_at": "invalid",
        }
        try:
            await port.retrieve("broken")
        except ValueError as exc:
            surfaces.append(str(exc))
        combined = " | ".join(surfaces)
        assert "CloudflareD1EvidenceStoragePort(configured)" in repr(port)
        for forbidden in (BODY, REF, "att_", LOCATOR, "evidence://", "app.revenue", "user.42"):
            assert forbidden not in combined

    asyncio.run(scenario())


# --- source-only boundary -----------------------------------------------------------


def test_durable_port_is_not_wired_into_production_composition() -> None:
    adapter_source = (APP_ROOT / "app" / "evidence_storage_d1.py").read_text(encoding="utf-8")
    assert "CREATE TABLE" not in adapter_source.upper()
    for name in ("engine_composition.py", "document_context_service.py"):
        source = (APP_ROOT / "app" / name).read_text(encoding="utf-8")
        assert "evidence_storage_d1" not in source
        assert "CloudflareD1EvidenceStoragePort" not in source
    identity_source = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert "evidence_storage_d1" not in identity_source
    assert "CloudflareD1EvidenceStoragePort" not in identity_source
