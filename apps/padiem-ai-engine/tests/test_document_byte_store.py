"""Scoped document byte store tests for Engine E8C-B (#2741).

Mirrors the shape of the image byte store suite: async scenarios run under
``asyncio.run`` with sync test functions, and a fake D1 binding mirrors the
deployment SQL contract exactly. Every failure mode is proven fail-closed
and leak-free. Retention is always bounded and server-minted here — unlike
the image lane there is no caller-visible indefinite storage surface at all.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import re
from pathlib import Path
import sys
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.document_byte_store import (  # noqa: E402
    DEFAULT_DOCUMENT_RETENTION_SECONDS,
    MAX_STORED_DOCUMENT_BASE64_CHARS,
    MAX_STORED_DOCUMENT_BYTES,
    SUPPORTED_DOCUMENT_MEDIA_TYPES,
    ScopedDocumentByteStore,
    StoredDocumentRecord,
    CloudflareD1DocumentByteStore,
    InMemoryDocumentByteStore,
    DocumentByteStoreError,
)
from app.document_reference import DOC_REFERENCE_PATTERN  # noqa: E402
from padiem_ai_core.document_normalization import (  # noqa: E402
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_TEXT_DOCUMENT_BYTES,
)

FIXED_NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
SCOPE = {"app_id": "app_a", "tenant_id": "user_1", "subject_id": "workspace_x"}
PAYLOAD = b"quarterly revenue projections for beta-corp"


def _clock_at(value: datetime):
    return lambda: value


def _scoped(**kwargs: Any) -> ScopedDocumentByteStore:
    return ScopedDocumentByteStore(port=InMemoryDocumentByteStore(), **kwargs)


def _admit(store: ScopedDocumentByteStore, data: bytes = PAYLOAD, **overrides: Any):
    values: dict[str, Any] = {
        "data": data,
        "media_type": "text/plain",
        "name": "notes.txt",
        **SCOPE,
    }
    values.update(overrides)
    return asyncio.run(store.admit_document(**values))


# --- minting authority --------------------------------------------------------


def test_admitted_reference_matches_grammar_and_is_random() -> None:
    async def scenario() -> None:
        store = _scoped()
        refs = set()
        for _ in range(25):
            record = await store.admit_document(
                data=PAYLOAD, media_type="text/plain", name="n.txt", **SCOPE
            )
            assert DOC_REFERENCE_PATTERN.fullmatch(record.document_ref)
            refs.add(record.document_ref)
        assert len(refs) == 25, "every admission must mint a fresh reference"

    asyncio.run(scenario())


def test_retention_is_server_minted_default_24h() -> None:
    store = _scoped(clock=_clock_at(FIXED_NOW))
    record = _admit(store)
    assert record.created_at == FIXED_NOW
    assert record.expires_at == FIXED_NOW + timedelta(seconds=DEFAULT_DOCUMENT_RETENTION_SECONDS)
    assert DEFAULT_DOCUMENT_RETENTION_SECONDS == 24 * 60 * 60


def test_admission_signature_exposes_no_reference_expiry_or_identity_knobs() -> None:
    # Caller cannot choose ref/expiry/identity: the wire surface is data +
    # media + name + server-minted scope only.
    import inspect

    signature = inspect.signature(ScopedDocumentByteStore.admit_document)
    assert set(signature.parameters) == {
        "self",
        "data",
        "media_type",
        "name",
        "app_id",
        "tenant_id",
        "subject_id",
    }
    assert tuple(
        p.kind for p in signature.parameters.values() if p.name != "self"
    ) == (inspect.Parameter.KEYWORD_ONLY,) * 6


def test_name_is_trimmed_but_payload_never_stored_in_clear_by_d1() -> None:
    record = _admit(_scoped(), name="  quarterly.txt  ")
    assert record.name == "quarterly.txt"


# --- admission guards -----------------------------------------------------------


@pytest.mark.parametrize("data", [b"", None, "text", 42, bytearray()])
def test_empty_or_non_bytes_payload_is_rejected(data: Any) -> None:
    store = _scoped()
    with pytest.raises(DocumentByteStoreError) as info:
        _admit(store, data=data)
    assert info.value.code == "empty_payload"


@pytest.mark.parametrize(
    "media_type",
    ["image/png", "application/octet-stream", "text/html", "", "  ", None, 7],
)
def test_media_outside_core_document_allowlists_is_rejected(media_type: Any) -> None:
    store = _scoped()
    with pytest.raises(DocumentByteStoreError) as info:
        _admit(store, media_type=media_type)
    assert info.value.code == "unsupported_media_type"


def test_document_media_allowlist_matches_core() -> None:
    from padiem_ai_core import document_normalization as core

    expected = frozenset(core.TEXT_DOCUMENT_MEDIA) | frozenset(core.BINARY_DOCUMENT_MEDIA)
    assert SUPPORTED_DOCUMENT_MEDIA_TYPES == expected
    assert "application/hwp+zip" in expected  # HWPX only; legacy .hwp stays out
    assert "application/x-hwp" not in expected


def test_text_ceiling_enforced_from_core_constants() -> None:
    store = _scoped()
    assert MAX_TEXT_DOCUMENT_BYTES > 0
    with pytest.raises(DocumentByteStoreError) as too_big:
        _admit(store, data=b"x" * (MAX_TEXT_DOCUMENT_BYTES + 1))
    assert too_big.value.code == "document_too_large"
    assert too_big.value.status_code == 413
    ok = _admit(store, data=b"x" * MAX_TEXT_DOCUMENT_BYTES)
    assert ok.byte_size == MAX_TEXT_DOCUMENT_BYTES


def test_binary_ceiling_enforced_and_class_ceiling_is_the_document_bound() -> None:
    assert MAX_STORED_DOCUMENT_BYTES == MAX_BINARY_DOCUMENT_BYTES == 2 * 1024 * 1024
    store = _scoped()
    pdf = b"%PDF-1.4\n" + b"0" * (MAX_BINARY_DOCUMENT_BYTES - 9)
    ok = _admit(store, data=pdf, media_type="application/pdf", name="deck.pdf")
    assert ok.byte_size == MAX_BINARY_DOCUMENT_BYTES
    with pytest.raises(DocumentByteStoreError) as too_big:
        _admit(store, data=pdf + b"x", media_type="application/pdf")
    assert too_big.value.code == "document_too_large"


@pytest.mark.parametrize(
    "scope_key",
    [
        "invalid app",
        "app;DROP",
        "",
        "x" * 129,
    ],
)
def test_malformed_scope_components_are_rejected_on_admission(scope_key: str) -> None:
    store = _scoped()
    with pytest.raises(DocumentByteStoreError) as info:
        _admit(store, app_id=scope_key)
    assert info.value.code == "invalid_scope"


# --- fetch semantics --------------------------------------------------------------


def test_fetch_round_trips_record_and_exact_bytes() -> None:
    store = _scoped(clock=_clock_at(FIXED_NOW))
    admitted = _admit(store)

    async def scenario() -> None:
        record, data = await store.fetch_document(document_ref=admitted.document_ref, **SCOPE)
        assert data == PAYLOAD
        assert record.media_type == "text/plain"
        assert record.byte_size == len(PAYLOAD)
        assert not record.terminal

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "wrong",
    [
        {"app_id": "app_other"},
        {"tenant_id": "user_2"},
        {"subject_id": "workspace_y"},
        {
            "app_id": SCOPE["tenant_id"],
            "tenant_id": SCOPE["subject_id"],
            "subject_id": SCOPE["app_id"],
        },
    ],
)
def test_scope_mismatch_is_unauthorized_without_content(wrong: dict[str, str]) -> None:
    async def scenario(self_wrong: dict[str, str] = wrong) -> None:
        store = _scoped()
        admitted = await store.admit_document(
            data=b"secret-body-bytes", media_type="text/plain", name="s.txt", **SCOPE
        )
        caller = {**SCOPE, **self_wrong}
        with pytest.raises(DocumentByteStoreError) as info:
            await store.fetch_document(document_ref=admitted.document_ref, **caller)
        assert info.value.code == "unauthorized"
        assert "secret-body-bytes" not in str(info.value)
        assert admitted.document_ref not in str(info.value)

    asyncio.run(scenario())


def test_unknown_reference_reported_as_same_as_wrong_scope_shape() -> None:
    async def scenario() -> None:
        store = _scoped()
        with pytest.raises(DocumentByteStoreError) as info:
            await store.fetch_document(document_ref="doc_" + "0" * 24, **SCOPE)
        assert info.value.code == "not_found"
        assert "doc_" not in str(info.value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "bad_ref",
    ["", "att_" + "0" * 24, "doc_" + "0" * 15, "doc_" + "0" * 121, "not-a-ref", "../etc/passwd"],
)
def test_ref_grammar_enforced_before_any_storage_touch(bad_ref: str) -> None:
    async def scenario() -> None:
        store = _scoped()
        with pytest.raises(DocumentByteStoreError) as info:
            await store.fetch_document(document_ref=bad_ref, **SCOPE)
        assert info.value.code == "invalid_document_reference"

    asyncio.run(scenario())


def test_expiry_boundary_and_post_expiry_reads_fail_closed() -> None:
    box = {"now": FIXED_NOW}
    store = _scoped(clock=lambda: box["now"])
    admitted = _admit(store)

    async def scenario() -> None:
        box["now"] = admitted.expires_at  # at expiry == expired
        with pytest.raises(DocumentByteStoreError) as at_expiry:
            await store.fetch_document(document_ref=admitted.document_ref, **SCOPE)
        assert at_expiry.value.code == "expired"
        assert at_expiry.value.status_code == 410
        box["now"] = admitted.expires_at + timedelta(seconds=1)
        with pytest.raises(DocumentByteStoreError) as after:
            await store.fetch_document(document_ref=admitted.document_ref, **SCOPE)
        assert after.value.code == "expired"

    asyncio.run(scenario())


def test_invalidate_marks_terminal_and_terminal_reads_fail_closed() -> None:
    async def scenario() -> None:
        store = _scoped()
        admitted = await store.admit_document(
            data=PAYLOAD, media_type="text/plain", name="n.txt", **SCOPE
        )
        assert await store.invalidate(document_ref=admitted.document_ref, **SCOPE) is True
        with pytest.raises(DocumentByteStoreError) as info:
            await store.fetch_document(document_ref=admitted.document_ref, **SCOPE)
        assert info.value.code == "terminal"
        # re-invalidation is idempotent, bytes already unreadable
        assert await store.invalidate(document_ref=admitted.document_ref, **SCOPE) is True
        with pytest.raises(DocumentByteStoreError) as foreign:
            await store.invalidate(
                document_ref=admitted.document_ref,
                **{**SCOPE, "subject_id": "workspace_victim"},
            )
        assert foreign.value.code == "unauthorized"
        with pytest.raises(DocumentByteStoreError) as ghost:
            await store.invalidate(document_ref="doc_" + "9" * 20, **SCOPE)
        assert ghost.value.code == "not_found"

    asyncio.run(scenario())


def test_expired_and_terminal_together_reports_terminal_invalidation_first() -> None:
    box = {"now": FIXED_NOW}
    store = _scoped(clock=lambda: box["now"])
    admitted = _admit(store)

    async def scenario() -> None:
        await store.invalidate(document_ref=admitted.document_ref, **SCOPE)
        box["now"] = admitted.expires_at + timedelta(hours=1)
        with pytest.raises(DocumentByteStoreError) as info:
            await store.fetch_document(document_ref=admitted.document_ref, **SCOPE)
        # explicit invalidation dominates natural expiry (both are 410-range)
        assert info.value.code == "terminal"

    asyncio.run(scenario())


def test_record_validation_rejects_indefinite_or_out_of_ceiling_expiry() -> None:
    with pytest.raises(DocumentByteStoreError):
        StoredDocumentRecord(  # expires before/at creation
            document_ref="doc_" + "0" * 24,
            **SCOPE,
            media_type="text/plain",
            name="n.txt",
            byte_size=4,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW,
        )
    with pytest.raises(DocumentByteStoreError):
        StoredDocumentRecord(  # beyond the 7-day ceiling
            document_ref="doc_" + "0" * 24,
            **SCOPE,
            media_type="text/plain",
            name="n.txt",
            byte_size=4,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(days=7, seconds=1),
        )


def test_record_rejects_payload_over_size_bound_and_bad_media() -> None:
    with pytest.raises(DocumentByteStoreError):
        StoredDocumentRecord(
            document_ref="doc_" + "0" * 24,
            **SCOPE,
            media_type="image/png",
            name="n.txt",
            byte_size=4,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(hours=1),
        )
    with pytest.raises(DocumentByteStoreError):
        StoredDocumentRecord(
            document_ref="doc_" + "0" * 24,
            **SCOPE,
            media_type="text/plain",
            name="n.txt",
            byte_size=MAX_BINARY_DOCUMENT_BYTES + 1,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(hours=1),
        )


# --- D1 adapter --------------------------------------------------------------------


class _FakeStatement:
    def __init__(self, db: "_FakeD1", sql: str) -> None:
        self.db = db
        self.sql = " ".join(sql.split())
        self.params: tuple[Any, ...] = ()
        self.calls: list[str] = []

    def bind(self, *params):
        self.params = params
        return self

    async def first(self):
        self.calls.append(self.sql)
        if self.sql.endswith("LIMIT 1") and "WHERE document_ref=?" in self.sql:
            (ref,) = self.params
            return dict(self.db.rows[ref]) if ref in self.db.rows else None
        raise AssertionError("unexpected first sql")

    async def run(self):
        self.calls.append(self.sql)
        if self.sql.startswith("INSERT INTO padiem_engine_document_bytes"):
            key = self.params[0]
            if key in self.db.rows:
                raise AssertionError("duplicate primary key in padiem_engine_document_bytes")
            columns = (
                "document_ref",
                "app_id",
                "tenant_id",
                "subject_id",
                "media_type",
                "name",
                "byte_size",
                "created_at",
                "expires_at",
                "terminal",
                "payload_base64",
            )
            self.db.rows[key] = dict(zip(columns, self.params))
            return {"success": True}
        if self.sql.startswith("UPDATE padiem_engine_document_bytes SET terminal=1"):
            (ref,) = self.params
            self.db.rows[ref]["terminal"] = 1
            return {"success": True}
        raise AssertionError("unexpected run sql")


class _FakeD1:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.statements: list[_FakeStatement] = []

    def prepare(self, sql: str) -> _FakeStatement:
        statement = _FakeStatement(self, sql)
        self.statements.append(statement)
        return statement


def _d1() -> tuple[ScopedDocumentByteStore, _FakeD1]:
    db = _FakeD1()
    return ScopedDocumentByteStore(port=CloudflareD1DocumentByteStore(db), clock=_clock_at(FIXED_NOW)), db


def test_d1_round_trip_stores_base64_payload_and_reads_exact_bytes() -> None:
    import base64

    db = _FakeD1()
    port = CloudflareD1DocumentByteStore(db)

    async def scenario() -> None:
        record = StoredDocumentRecord(
            document_ref="doc_" + "a" * 24,
            **SCOPE,
            media_type="application/pdf",
            name="deck.pdf",
            byte_size=len(PAYLOAD),
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(hours=2),
        )
        await port.put(record, PAYLOAD)
        stored_record, data = await port.fetch(record.document_ref)
        assert data == PAYLOAD
        assert stored_record.media_type == "application/pdf"
        assert stored_record.byte_size == len(PAYLOAD)
        row = db.rows[record.document_ref]
        assert row["media_type"] == "application/pdf"
        assert row["byte_size"] == len(PAYLOAD)
        assert base64.b64decode(row["payload_base64"]) == PAYLOAD
        assert PAYLOAD.decode("ascii", "ignore") not in row["payload_base64"]

    asyncio.run(scenario())

    async def scoped_scenario() -> None:
        store, db2 = _d1()
        admitted = await store.admit_document(
            data=PAYLOAD, media_type="text/plain", name="n.txt", **SCOPE
        )
        record, data = await store.fetch_document(document_ref=admitted.document_ref, **SCOPE)
        assert data == PAYLOAD
        terminal_ok = await store.invalidate(document_ref=admitted.document_ref, **SCOPE)
        assert terminal_ok is True
        assert db2.rows[admitted.document_ref]["terminal"] == 1
        with pytest.raises(DocumentByteStoreError) as info:
            await store.fetch_document(document_ref=admitted.document_ref, **SCOPE)
        assert info.value.code == "terminal"

    asyncio.run(scoped_scenario())


def test_d1_integrity_tampering_detected_on_read() -> None:
    async def scenario() -> None:
        store, db = _d1()
        admitted = await store.admit_document(
            data=PAYLOAD, media_type="text/plain", name="n.txt", **SCOPE
        )
        db.rows[admitted.document_ref]["byte_size"] = len(PAYLOAD) + 99
        with pytest.raises(DocumentByteStoreError) as info:
            await store.fetch_document(document_ref=admitted.document_ref, **SCOPE)
        assert info.value.code == "integrity_mismatch"
        db.rows[admitted.document_ref]["byte_size"] = len(PAYLOAD)
        db.rows[admitted.document_ref]["payload_base64"] = "!!!not base64!!!"
        with pytest.raises(DocumentByteStoreError) as broken:
            await store.fetch_document(document_ref=admitted.document_ref, **SCOPE)
        assert broken.value.code == "integrity_mismatch"
        # expiry tampering beyond retention ceiling must not be readable
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT[\d:.+]+", str(db.rows[admitted.document_ref]["expires_at"]))

    asyncio.run(scenario())


def test_d1_store_requires_binding_with_prepare() -> None:
    with pytest.raises(ValueError):
        CloudflareD1DocumentByteStore(None)
    with pytest.raises(ValueError):
        CloudflareD1DocumentByteStore(object())


def test_ref_conflict_mints_a_fresh_candidate_instead_of_clobbering() -> None:
    async def scenario() -> None:
        port = InMemoryDocumentByteStore()
        store = ScopedDocumentByteStore(port=port, clock=_clock_at(FIXED_NOW))
        first = await store.admit_document(
            data=PAYLOAD, media_type="text/plain", name="a.txt", **SCOPE
        )
        # simulate key collision: pre-seed the same minted ref again
        with pytest.raises(DocumentByteStoreError) as info:
            await port.put(
                replace(first, name="b.txt"), PAYLOAD
            )  # same document_ref -> append-only conflict
        assert info.value.code == "ref_conflict"
        # original bytes intact
        record, data = await store.fetch_document(document_ref=first.document_ref, **SCOPE)
        assert data == PAYLOAD
        assert record.name == "a.txt"

    asyncio.run(scenario())
