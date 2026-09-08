"""Scoped image-byte store acceptance tests for #2138 E5-S1.

The fake D1 binding mirrors the existing evidence_storage_d1 test fake exactly:
``prepare(sql) -> statement.bind(*params)`` with awaitable ``first``/``run``
over an in-process dict. No network, filesystem or provider access.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.attachment_authority import require_opaque_attachment_ref  # noqa: E402
from app.attachment_byte_store import (  # noqa: E402
    MAX_STORED_IMAGE_BASE64_CHARS,
    MAX_STORED_IMAGE_BYTES,
    SUPPORTED_IMAGE_MEDIA_TYPES,
    CloudflareD1ImageByteStore,
    ImageByteStoreError,
    InMemoryImageByteStore,
    ScopedImageByteStore,
    StoredImageRecord,
)
from padiem_ai_core.b14_multimodal import (  # noqa: E402
    MAX_B14_IMAGE_BYTES as CORE_MAX_B14_IMAGE_BYTES,
)
from padiem_ai_core.b14_multimodal import (  # noqa: E402
    _ALLOWED_IMAGE_MEDIA_TYPES as CORE_ALLOWED_IMAGE_MEDIA_TYPES,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"pixeldata" * 8
JPEG_BYTES = b"\xff\xd8\xff" + b"jpegdata" * 8
SCOPE = {"app_id": "app.revenue", "tenant_id": "tenant.a", "subject_id": "user.42"}
SECRET_TAIL = "PAYLOADMARKERNOTINERRORS-21380"
BASE_TIME = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _store(clock: MutableClock | None = None) -> tuple[ScopedImageByteStore, MutableClock]:
    tick = clock or MutableClock(BASE_TIME)
    return ScopedImageByteStore(port=InMemoryImageByteStore(), clock=tick), tick


# --- admit / fetch round trip ---------------------------------------------------------


def test_admit_then_fetch_round_trips_exact_bytes_and_record() -> None:
    store, _ = _store()

    async def scenario() -> None:
        record = await store.admit_image(data=PNG_BYTES, media_type="image/png", **SCOPE)
        assert isinstance(record, StoredImageRecord)
        assert record.byte_size == len(PNG_BYTES)
        assert record.media_type == "image/png"
        assert record.created_at == BASE_TIME
        assert record.expires_at is None
        assert record.terminal is False
        fetched_record, data = await store.fetch_image(attachment_ref=record.attachment_ref, **SCOPE)
        assert fetched_record == record
        assert data == PNG_BYTES

    asyncio.run(scenario())


def test_reference_is_server_minted_opaque_and_unguessable() -> None:
    store, _ = _store()

    async def scenario() -> None:
        first = await store.admit_image(data=PNG_BYTES, media_type="image/png", **SCOPE)
        second = await store.admit_image(data=JPEG_BYTES, media_type="image/jpeg", **SCOPE)
        require_opaque_attachment_ref(first.attachment_ref)
        assert first.attachment_ref != second.attachment_ref
        for fragment in (SCOPE["app_id"], SCOPE["tenant_id"], SCOPE["subject_id"], SECRET_TAIL):
            assert fragment not in first.attachment_ref

    asyncio.run(scenario())


def test_media_type_is_normalized_and_allowlisted() -> None:
    store, _ = _store()

    async def scenario() -> None:
        record = await store.admit_image(data=PNG_BYTES, media_type=" IMAGE/PNG ", **SCOPE)
        assert record.media_type == "image/png"
        for rejected in ("image/gif", "image/svg+xml", "application/pdf", "", "png"):
            with pytest.raises(ImageByteStoreError) as excinfo:
                await store.admit_image(data=PNG_BYTES, media_type=rejected, **SCOPE)
            assert excinfo.value.code == "unsupported_media_type"
            assert excinfo.value.status_code == 415

    asyncio.run(scenario())


def test_admit_enforces_byte_bounds_and_non_empty_payload() -> None:
    store, _ = _store()

    async def scenario() -> None:
        with pytest.raises(ImageByteStoreError) as empty:
            await store.admit_image(data=b"", media_type="image/png", **SCOPE)
        assert empty.value.code == "empty_payload"
        with pytest.raises(ImageByteStoreError) as oversized:
            await store.admit_image(
                data=b"\x00" * (MAX_STORED_IMAGE_BYTES + 1),
                media_type="image/png",
                **SCOPE,
            )
        assert oversized.value.code == "attachment_too_large"
        assert oversized.value.status_code == 413
        boundary = await store.admit_image(
            data=b"\x00" * MAX_STORED_IMAGE_BYTES,
            media_type="image/png",
            **SCOPE,
        )
        assert boundary.byte_size == MAX_STORED_IMAGE_BYTES

    asyncio.run(scenario())


@pytest.mark.parametrize("bad_scope", [{"app_id": "../etc/passwd"}, {"tenant_id": ""}, {"subject_id": "a b"}])
def test_admit_rejects_invalid_scope(bad_scope: dict) -> None:
    store, _ = _store()
    merged = {**SCOPE, **bad_scope}

    async def scenario() -> None:
        with pytest.raises(ImageByteStoreError) as excinfo:
            await store.admit_image(data=PNG_BYTES, media_type="image/png", **merged)
        assert excinfo.value.code == "invalid_scope"

    asyncio.run(scenario())


def test_admit_rejects_naive_or_past_expiry() -> None:
    store, _ = _store()

    async def scenario() -> None:
        with pytest.raises(ImageByteStoreError) as naive:
            await store.admit_image(
                data=PNG_BYTES, media_type="image/png", expires_at=datetime(2099, 1, 1), **SCOPE
            )
        assert naive.value.code == "invalid_expiry"
        with pytest.raises(ImageByteStoreError) as past:
            await store.admit_image(
                data=PNG_BYTES,
                media_type="image/png",
                expires_at=BASE_TIME - timedelta(seconds=1),
                **SCOPE,
            )
        assert past.value.code == "invalid_expiry"

    asyncio.run(scenario())


# --- fetch fail-closed matrix ---------------------------------------------------------


@pytest.mark.parametrize(
    "bad_ref",
    [
        "att_short",
        "https://cdn.example.com/att_abcdefghijklmnop",
        "/var/secrets/att_abcdefghijklmnop",
        "file_blob_key_att_abcdefghijklmnop",
        "ATT_abcdefghijklmnopqrst",
        "",
        None,
        123,
    ],
)
def test_fetch_rejects_non_opaque_references(bad_ref: object) -> None:
    store, _ = _store()

    async def scenario() -> None:
        with pytest.raises(ImageByteStoreError) as excinfo:
            await store.fetch_image(attachment_ref=bad_ref, **SCOPE)  # type: ignore[arg-type]
        assert excinfo.value.code == "invalid_attachment_reference"

    asyncio.run(scenario())


def test_fetch_unknown_reference_is_not_found() -> None:
    store, _ = _store()
    unknown = "att_" + "Z" * 32

    async def scenario() -> None:
        require_opaque_attachment_ref(unknown)
        with pytest.raises(ImageByteStoreError) as excinfo:
            await store.fetch_image(attachment_ref=unknown, **SCOPE)
        assert excinfo.value.code == "not_found"
        assert excinfo.value.status_code == 404

    asyncio.run(scenario())


@pytest.mark.parametrize("field", ["app_id", "tenant_id", "subject_id"])
def test_fetch_rejects_scope_mismatch(field: str) -> None:
    store, _ = _store()

    async def scenario() -> None:
        record = await store.admit_image(data=PNG_BYTES, media_type="image/png", **SCOPE)
        mismatched = {**SCOPE, field: "scope.evil"}
        with pytest.raises(ImageByteStoreError) as excinfo:
            await store.fetch_image(attachment_ref=record.attachment_ref, **mismatched)
        assert excinfo.value.code == "unauthorized"
        assert excinfo.value.status_code == 403

    asyncio.run(scenario())


def test_expiry_fails_closed_against_clock() -> None:
    clock = MutableClock(BASE_TIME)
    store, _ = _store(clock)

    async def scenario() -> None:
        record = await store.admit_image(
            data=PNG_BYTES,
            media_type="image/png",
            expires_at=BASE_TIME + timedelta(minutes=5),
            **SCOPE,
        )
        live_record, data = await store.fetch_image(attachment_ref=record.attachment_ref, **SCOPE)
        assert data == PNG_BYTES
        clock.now = BASE_TIME + timedelta(minutes=5)
        with pytest.raises(ImageByteStoreError) as excinfo:
            await store.fetch_image(attachment_ref=live_record.attachment_ref, **SCOPE)
        assert excinfo.value.code == "attachment_expired"
        assert excinfo.value.status_code == 410

    asyncio.run(scenario())


def test_terminal_invalidation_fails_closed_and_is_scope_checked() -> None:
    store, _ = _store()

    async def scenario() -> None:
        record = await store.admit_image(data=PNG_BYTES, media_type="image/png", **SCOPE)
        with pytest.raises(ImageByteStoreError) as wrong_scope:
            await store.invalidate(attachment_ref=record.attachment_ref, app_id="other", tenant_id="tenant.a", subject_id="user.42")
        assert wrong_scope.value.code == "unauthorized"
        with pytest.raises(ImageByteStoreError) as unknown:
            await store.invalidate(attachment_ref="att_" + "Q" * 32, **SCOPE)
        assert unknown.value.code == "not_found"
        assert await store.invalidate(attachment_ref=record.attachment_ref, **SCOPE) is True
        with pytest.raises(ImageByteStoreError) as terminal:
            await store.fetch_image(attachment_ref=record.attachment_ref, **SCOPE)
        assert terminal.value.code == "attachment_terminal"
        assert terminal.value.status_code == 410
        assert await store.invalidate(attachment_ref=record.attachment_ref, **SCOPE) is True

    asyncio.run(scenario())


class TamperingPort:
    """Port fake that returns a record whose byte_size disagrees with payload."""

    def __init__(self, record: StoredImageRecord, data: bytes) -> None:
        self._record = record
        self._data = data

    async def put(self, record: StoredImageRecord, data: bytes) -> None:
        raise AssertionError("unused")

    async def fetch(self, attachment_ref: str) -> tuple[StoredImageRecord, bytes]:
        return self._record, self._data

    async def mark_terminal(self, attachment_ref: str) -> bool:
        raise AssertionError("unused")


def test_backing_record_inconsistency_fails_closed() -> None:
    good = StoredImageRecord(
        attachment_ref="att_" + "A" * 32,
        app_id=SCOPE["app_id"],
        tenant_id=SCOPE["tenant_id"],
        subject_id=SCOPE["subject_id"],
        media_type="image/png",
        byte_size=len(PNG_BYTES),
        created_at=BASE_TIME,
    )
    lying = StoredImageRecord(
        attachment_ref=good.attachment_ref,
        app_id=good.app_id,
        tenant_id=good.tenant_id,
        subject_id=good.subject_id,
        media_type="image/png",
        byte_size=len(PNG_BYTES) + 7,
        created_at=BASE_TIME,
    )
    store = ScopedImageByteStore(port=TamperingPort(lying, PNG_BYTES), clock=MutableClock(BASE_TIME))

    async def scenario() -> None:
        with pytest.raises(ImageByteStoreError) as excinfo:
            await store.fetch_image(attachment_ref=good.attachment_ref, **SCOPE)
        assert excinfo.value.code == "integrity_mismatch"
        assert excinfo.value.status_code == 503

    asyncio.run(scenario())


def test_in_memory_port_rejects_duplicate_refs_and_empty_payloads() -> None:
    port = InMemoryImageByteStore()
    record = StoredImageRecord(
        attachment_ref="att_" + "B" * 32,
        app_id=SCOPE["app_id"],
        tenant_id=SCOPE["tenant_id"],
        subject_id=SCOPE["subject_id"],
        media_type="image/png",
        byte_size=len(PNG_BYTES),
        created_at=BASE_TIME,
    )

    async def scenario() -> None:
        await port.put(record, PNG_BYTES)
        with pytest.raises(ImageByteStoreError) as duplicate:
            await port.put(record, PNG_BYTES)
        assert duplicate.value.code == "ref_conflict"
        with pytest.raises(ImageByteStoreError) as empty:
            await port.put(
                StoredImageRecord(
                    attachment_ref="att_" + "C" * 32,
                    app_id=SCOPE["app_id"],
                    tenant_id=SCOPE["tenant_id"],
                    subject_id=SCOPE["subject_id"],
                    media_type="image/png",
                    byte_size=1,
                    created_at=BASE_TIME,
                ),
                b"",
            )
        assert empty.value.code == "empty_payload"
        assert await port.fetch("att_" + "D" * 32) is None

    asyncio.run(scenario())


# --- D1 adapter (fake binding, mirrors evidence_storage_d1 harness) --------------------


class FakeStatement:
    def __init__(self, db: "FakeD1", sql: str) -> None:
        self.db = db
        self.sql = sql
        self.params: tuple = ()

    def bind(self, *params):
        self.params = params
        return self

    async def run(self):
        if self.sql.startswith("INSERT INTO padiem_engine_attachment_images"):
            self.db.rows[self.params[0]] = {
                "attachment_ref": self.params[0],
                "app_id": self.params[1],
                "tenant_id": self.params[2],
                "subject_id": self.params[3],
                "media_type": self.params[4],
                "byte_size": self.params[5],
                "created_at": self.params[6],
                "expires_at": self.params[7],
                "terminal": self.params[8],
                "payload_base64": self.params[9],
            }
            return {"success": True}
        if self.sql.startswith("UPDATE padiem_engine_attachment_images"):
            self.db.rows[self.params[0]]["terminal"] = 1
            return {"success": True}
        raise AssertionError(f"unexpected SQL: {self.sql}")

    async def first(self):
        if self.sql == (
            "SELECT attachment_ref FROM padiem_engine_attachment_images WHERE attachment_ref=? LIMIT 1"
        ):
            row = self.db.rows.get(self.params[0])
            return dict(row) if row is not None else None
        if self.sql.startswith("SELECT attachment_ref,app_id"):
            row = self.db.rows.get(self.params[0])
            return dict(row) if row is not None else None
        raise AssertionError(f"unexpected SQL: {self.sql}")


class FakeD1:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def prepare(self, sql: str) -> FakeStatement:
        return FakeStatement(self, sql)


def _d1_store() -> tuple[CloudflareD1ImageByteStore, FakeD1]:
    db = FakeD1()
    return CloudflareD1ImageByteStore(db), db


def _record(ref: str = "att_" + "E" * 32, **overrides) -> StoredImageRecord:
    fields = {
        "attachment_ref": ref,
        "app_id": SCOPE["app_id"],
        "tenant_id": SCOPE["tenant_id"],
        "subject_id": SCOPE["subject_id"],
        "media_type": "image/png",
        "byte_size": len(PNG_BYTES),
        "created_at": BASE_TIME,
    }
    fields.update(overrides)
    return StoredImageRecord(**fields)


def test_d1_adapter_round_trips_through_binding() -> None:
    port, db = _d1_store()

    async def scenario() -> None:
        record = _record()
        await port.put(record, PNG_BYTES)
        assert record.attachment_ref in db.rows
        fetched = await port.fetch(record.attachment_ref)
        assert fetched is not None
        stored_record, data = fetched
        assert stored_record == record
        assert data == PNG_BYTES
        assert await port.fetch("att_" + "F" * 32) is None

    asyncio.run(scenario())


def test_d1_adapter_expiry_and_terminal_persist_as_flags() -> None:
    port, _ = _d1_store()

    async def scenario() -> None:
        expires_at = BASE_TIME + timedelta(hours=1)
        record = _record(expires_at=expires_at)
        await port.put(record, PNG_BYTES)
        fetched = await port.fetch(record.attachment_ref)
        assert fetched is not None
        assert fetched[0] == record
        assert await port.mark_terminal(record.attachment_ref) is True
        refetched = await port.fetch(record.attachment_ref)
        assert refetched is not None
        assert refetched[0].terminal is True
        assert refetched[0].expires_at == expires_at
        assert await port.mark_terminal("att_" + "G" * 32) is False

    asyncio.run(scenario())


def test_d1_adapter_rejects_duplicate_conflicting_binding_and_oversized_payload() -> None:
    port, db = _d1_store()

    async def scenario() -> None:
        with pytest.raises(ImageByteStoreError) as no_prepare:
            CloudflareD1ImageByteStore(object())
        assert no_prepare.value.code == "store_unavailable"
        with pytest.raises(ImageByteStoreError):
            CloudflareD1ImageByteStore(None)
        record = _record()
        await port.put(record, PNG_BYTES)
        with pytest.raises(ImageByteStoreError) as duplicate:
            await port.put(record, PNG_BYTES)
        assert duplicate.value.code == "ref_conflict"
        oversized = _record(ref="att_" + "H" * 32, byte_size=MAX_STORED_IMAGE_BYTES)
        with pytest.raises(ImageByteStoreError) as too_large:
            await port.put(oversized, b"\x00" * (MAX_STORED_IMAGE_BASE64_CHARS + 1))
        assert too_large.value.code == "integrity_mismatch"
        assert "att_" + "H" * 32 not in db.rows

    asyncio.run(scenario())


def test_d1_adapter_malformed_rows_fail_closed_as_integrity_mismatch() -> None:
    port, db = _d1_store()

    async def scenario() -> None:
        record = _record()
        await port.put(record, PNG_BYTES)
        db.rows[record.attachment_ref]["payload_base64"] = "!!!notbase64!!!"
        with pytest.raises(ImageByteStoreError) as bad_b64:
            await port.fetch(record.attachment_ref)
        assert bad_b64.value.code == "integrity_mismatch"
        await port.put(_record(ref="att_" + "I" * 32), PNG_BYTES)
        db.rows["att_" + "I" * 32]["media_type"] = "image/gif"
        with pytest.raises(ImageByteStoreError) as bad_media:
            await port.fetch("att_" + "I" * 32)
        assert bad_media.value.code == "integrity_mismatch"
        await port.put(_record(ref="att_" + "J" * 32), PNG_BYTES)
        db.rows["att_" + "J" * 32]["created_at"] = "2026-09-08T12:00:00"
        with pytest.raises(ImageByteStoreError) as naive_ts:
            await port.fetch("att_" + "J" * 32)
        assert naive_ts.value.code == "integrity_mismatch"

    asyncio.run(scenario())


def test_d1_adapter_repr_is_constant_and_holds_no_payload() -> None:
    port, _ = _d1_store()
    assert repr(port) == "CloudflareD1ImageByteStore(configured)"


# --- zero-leak and drift guards ---------------------------------------------------------


def test_errors_never_echo_payload_bytes_or_references() -> None:
    store, _ = _store()
    marker = SECRET_TAIL.encode("ascii")

    async def scenario() -> None:
        record = await store.admit_image(data=PNG_BYTES + marker, media_type="image/png", **SCOPE)
        cases: list[ImageByteStoreError] = []
        for attempt in (
            store.fetch_image(attachment_ref="att_bad", **SCOPE),
            store.fetch_image(attachment_ref=record.attachment_ref, app_id="other", tenant_id="tenant.a", subject_id="user.42"),
            store.admit_image(data=PNG_BYTES, media_type="image/gif", **SCOPE),
        ):
            try:
                await attempt
            except ImageByteStoreError as exc:
                cases.append(exc)
        assert cases
        for exc in cases:
            rendered = repr(exc) + str(exc) + exc.code + exc.safe_message
            assert marker.decode("ascii") not in rendered
            assert record.attachment_ref not in rendered

    asyncio.run(scenario())


def test_record_repr_and_public_fields_carry_no_payload() -> None:
    record = _record()
    rendered = repr(record) + str(record)
    assert "payload" not in rendered
    assert PNG_BYTES[:6].decode("latin-1") not in rendered
    assert not any(getattr(record, name, None) for name in ("data", "payload", "locator", "url", "path", "key"))


def test_constants_match_core_authority_without_drift() -> None:
    assert SUPPORTED_IMAGE_MEDIA_TYPES == CORE_ALLOWED_IMAGE_MEDIA_TYPES
    assert MAX_STORED_IMAGE_BYTES is CORE_MAX_B14_IMAGE_BYTES
    from app import attachment_authority, attachment_byte_store

    assert attachment_byte_store._SAFE_ID_RE.pattern == attachment_authority._SAFE_ID_RE.pattern


# --- source-only boundary ---------------------------------------------------------------


def test_module_is_pure_and_declares_no_schema_or_io() -> None:
    source = (APP_ROOT / "app" / "attachment_byte_store.py").read_text(encoding="utf-8")
    assert "CREATE TABLE" not in source.upper()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    for forbidden in ("socket", "http", "urllib", "requests", "httpx", "os", "pathlib", "subprocess", "sqlite3"):
        assert forbidden not in imported, forbidden
    assert "open(" not in source


def test_store_is_wired_only_into_canonical_composition() -> None:
    """#2182 S5: the byte store reaches Production through worker_identity only.

    No app-layer service constructs or imports the storage adapter directly, and
    the binding stays a repo-owned D1 declaration rather than a new surface.
    """

    for name in (
        "engine_composition.py",
        "document_context_service.py",
        "attachment_authority.py",
        "multimodal_attachment_service.py",
    ):
        source = (APP_ROOT / "app" / name).read_text(encoding="utf-8")
        assert "attachment_byte_store" not in source
        assert "ScopedImageByteStore" not in source
    identity = (APP_ROOT / "worker_identity.py").read_text(encoding="utf-8")
    assert "from app.attachment_byte_store import" in identity
    assert 'ENGINE_IMAGE_STORE_BINDING = "ENGINE_IMAGE_STORE"' in identity
    wrangler = (APP_ROOT / "wrangler.toml").read_text(encoding="utf-8")
    assert 'binding = "ENGINE_IMAGE_STORE"' in wrangler
    assert "[[r2_buckets]]" not in wrangler
    assert "[[kv_namespaces]]" not in wrangler
