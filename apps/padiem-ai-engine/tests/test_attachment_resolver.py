"""Focused network-free acceptance tests for the #2137 S1 trusted resolver.

The resolver is exercised against the real merged #2138 canonical store
(``ScopedImageByteStore`` + ``InMemoryImageByteStore``) and through the real
``MultimodalAttachmentEngineService`` consumption boundary. No provider,
network, filesystem or environment access may occur in this suite.
"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from padiem_ai_core import (
    B14RouteMetadata,
    ExecutionResult,
    RunMetadata,
    RunStatus,
    UsageMetadata,
)

from app.attachment_authority import (
    EngineAttachmentAuthorityError,
    TrustedAttachmentResolver,
    TrustedImageAttachment,
)
from app.attachment_byte_store import (
    ScopedImageByteStore,
    StoredImageRecord,
)
from app.attachment_resolver import ByteStoreTrustedAttachmentResolver
from app.document_context_service import TrustedCallerScope
from app.multimodal_attachment_service import MultimodalAttachmentEngineService

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"2137-png-payload"
WEBP_BYTES = b"RIFF\x14\x00\x00\x00WEBP" + b"2137-webp-payload"
APP_ID = "app.revenue"
TENANT_ID = "tenant.a"
SUBJECT_ID = "user.42"
SCOPE = TrustedCallerScope(app_id=APP_ID, subject_id=SUBJECT_ID, tenant_id=TENANT_ID)
OTHER_SCOPE = TrustedCallerScope(app_id="app.other", subject_id="user.99", tenant_id="tenant.z")
BASE_TIME = datetime(2099, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
FIXED_PROVENANCE = "prov_2137_0001"

PRIVATE_MARKER = "STORESTATENOTINERRORS-21370"


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _pair(
    clock: MutableClock | None = None,
) -> tuple[ScopedImageByteStore, MutableClock, ByteStoreTrustedAttachmentResolver]:
    tick = clock or MutableClock(BASE_TIME)
    store = ScopedImageByteStore(port=FakeRecordingPort(), clock=tick)
    resolver = ByteStoreTrustedAttachmentResolver(
        store=store, scope=SCOPE, provenance_factory=lambda record: FIXED_PROVENANCE
    )
    return store, tick, resolver


class FakeRecordingPort:
    """Deterministic in-process backing: wraps dict storage, records every lookup."""

    def __init__(self) -> None:
        self.records: dict[str, StoredImageRecord] = {}
        self.payloads: dict[str, bytes] = {}
        self.lookups: list[dict[str, str]] = []

    async def put(self, record: StoredImageRecord, data: bytes) -> None:
        self.records[record.attachment_ref] = record
        self.payloads[record.attachment_ref] = bytes(data)

    async def fetch(self, attachment_ref: str) -> tuple[StoredImageRecord, bytes] | None:
        self.lookups.append({"attachment_ref": attachment_ref})
        record = self.records.get(attachment_ref)
        if record is None:
            return None
        return record, bytes(self.payloads[attachment_ref])

    async def mark_terminal(self, attachment_ref: str) -> bool:
        from dataclasses import replace

        record = self.records.get(attachment_ref)
        if record is None:
            return False
        self.records[attachment_ref] = replace(record, terminal=True)
        return True


async def _admit(
    store: ScopedImageByteStore,
    *,
    data: bytes = PNG_BYTES,
    media_type: str = "image/png",
    expires_at: datetime | None = None,
    scope: TrustedCallerScope = SCOPE,
) -> StoredImageRecord:
    return await store.admit_image(
        data=data,
        media_type=media_type,
        app_id=scope.app_id,
        tenant_id=scope.tenant_id,
        subject_id=scope.subject_id,
        expires_at=expires_at,
    )


def _resolver_for(store: ScopedImageByteStore, scope: TrustedCallerScope) -> ByteStoreTrustedAttachmentResolver:
    return ByteStoreTrustedAttachmentResolver(
        store=store, scope=scope, provenance_factory=lambda record: FIXED_PROVENANCE
    )


# --- protocol conformance ---------------------------------------------------------------


def test_resolver_is_bound_to_the_existing_protocol() -> None:
    _, _, resolver = _pair()
    assert isinstance(resolver, object)
    assert callable(getattr(resolver, "resolve_image", None))
    assert "resolve_image" in TrustedAttachmentResolver.__annotations__ or hasattr(
        TrustedAttachmentResolver, "resolve_image"
    )
    assert repr(resolver) == "ByteStoreTrustedAttachmentResolver(configured)"


def test_constructor_rejects_invalid_authority_inputs() -> None:
    for bad_store in (None, object()):
        with pytest.raises(ValueError):
            ByteStoreTrustedAttachmentResolver(store=bad_store, scope=SCOPE)
    with pytest.raises(ValueError):
        ByteStoreTrustedAttachmentResolver(store=_pair()[0], scope={"app_id": APP_ID})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ByteStoreTrustedAttachmentResolver(store=_pair()[0], scope=SCOPE, provenance_factory="x")  # type: ignore[arg-type]


# --- happy path --------------------------------------------------------------------------


def test_resolve_returns_the_existing_trusted_attachment_contract() -> None:
    store, _, resolver = _pair()

    async def scenario() -> None:
        record = await _admit(store)
        resolved = await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        assert isinstance(resolved, TrustedImageAttachment)
        assert resolved.attachment_ref == record.attachment_ref
        assert resolved.app_id == APP_ID
        assert resolved.media_type == "image/png"
        assert resolved.data == PNG_BYTES
        assert resolved.provenance_id == FIXED_PROVENANCE
        assert resolved.expires_at is None
        assert resolved.expired is False

    asyncio.run(scenario())


def test_expiry_and_scope_fields_pass_through_to_the_contract() -> None:
    store, _, resolver = _pair()

    async def scenario() -> None:
        record = await _admit(store, data=WEBP_BYTES, media_type="image/webp", expires_at=BASE_TIME + timedelta(hours=1))
        resolved = await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        assert resolved.media_type == "image/webp"
        assert resolved.data == WEBP_BYTES
        assert resolved.expires_at == BASE_TIME + timedelta(hours=1)

    asyncio.run(scenario())


def test_default_provenance_is_safe_id_unique_and_reused_contract() -> None:
    store, _, _ = _pair()
    resolver = None

    async def scenario() -> None:
        nonlocal resolver
        resolver = ByteStoreTrustedAttachmentResolver(store=store, scope=SCOPE)
        record = await _admit(store)
        first = await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        second = await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        assert first.provenance_id.startswith("prov_")
        assert first.provenance_id != second.provenance_id
        assert first.data == second.data == PNG_BYTES

    asyncio.run(scenario())


# --- fail-closed matrix -------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_ref",
    ["att_bad", "https://x/att_" + "A" * 16, "/tmp/att_" + "A" * 16, "att_" + "A" * 8, "", None],
)
def test_malformed_reference_fails_closed(bad_ref: object) -> None:
    _, _, resolver = _pair()

    async def scenario() -> None:
        with pytest.raises(EngineAttachmentAuthorityError) as excinfo:
            await resolver.resolve_image(app_id=APP_ID, attachment_ref=bad_ref)  # type: ignore[arg-type]
        assert excinfo.value.code == "invalid_attachment_reference"
        assert excinfo.value.status_code == 400

    asyncio.run(scenario())


def test_client_asserted_app_id_cannot_override_trusted_scope() -> None:
    store, _, resolver = _pair()

    async def scenario() -> None:
        record = await _admit(store)
        with pytest.raises(EngineAttachmentAuthorityError) as excinfo:
            await resolver.resolve_image(app_id="attacker.app", attachment_ref=record.attachment_ref)
        assert excinfo.value.code == "attachment_scope_mismatch"
        assert excinfo.value.status_code == 403
        assert record.attachment_ref not in str(excinfo.value)

    asyncio.run(scenario())


def test_unknown_reference_maps_to_not_found() -> None:
    _, _, resolver = _pair()

    async def scenario() -> None:
        with pytest.raises(EngineAttachmentAuthorityError) as excinfo:
            await resolver.resolve_image(app_id=APP_ID, attachment_ref="att_" + "Z" * 32)
        assert excinfo.value.code == "attachment_not_found"
        assert excinfo.value.status_code == 404

    asyncio.run(scenario())


def test_tenant_or_subject_divergence_fails_closed_even_with_matching_app() -> None:
    store, _, _ = _pair()

    async def scenario() -> None:
        record = await _admit(store)
        leaky_scope = TrustedCallerScope(app_id=APP_ID, subject_id="user.evil", tenant_id=TENANT_ID)
        resolver = _resolver_for(store, leaky_scope)
        with pytest.raises(EngineAttachmentAuthorityError) as excinfo:
            await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        assert excinfo.value.code == "attachment_scope_mismatch"
        assert excinfo.value.status_code == 403

    asyncio.run(scenario())


def test_expiry_fails_closed_against_the_store_clock() -> None:
    clock = MutableClock(BASE_TIME)
    store, _, resolver = _pair(clock)

    async def scenario() -> None:
        record = await _admit(store, expires_at=BASE_TIME + timedelta(minutes=5))
        live = await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        assert live.expired is False
        clock.now = BASE_TIME + timedelta(minutes=5)
        with pytest.raises(EngineAttachmentAuthorityError) as excinfo:
            await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        assert excinfo.value.code == "attachment_expired"
        assert excinfo.value.status_code == 410

    asyncio.run(scenario())


def test_terminal_invalidation_fails_closed() -> None:
    store, _, resolver = _pair()

    async def scenario() -> None:
        record = await _admit(store)
        await store.invalidate(attachment_ref=record.attachment_ref, app_id=APP_ID, tenant_id=TENANT_ID, subject_id=SUBJECT_ID)
        with pytest.raises(EngineAttachmentAuthorityError) as excinfo:
            await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        assert excinfo.value.code == "attachment_expired"
        assert excinfo.value.status_code == 410

    asyncio.run(scenario())


class CorruptPort(FakeRecordingPort):
    async def fetch(self, attachment_ref: str) -> tuple[StoredImageRecord, bytes] | None:
        fetched = await super().fetch(attachment_ref)
        if fetched is None:
            return None
        record, data = fetched
        return record, data + PRIVATE_MARKER.encode("ascii")


def test_backing_integrity_inconsistency_maps_to_unavailable_503() -> None:
    tick = MutableClock(BASE_TIME)
    port = CorruptPort()
    store = ScopedImageByteStore(port=port, clock=tick)
    resolver = _resolver_for(store, SCOPE)

    async def scenario() -> None:
        record = await _admit(store)
        with pytest.raises(EngineAttachmentAuthorityError) as excinfo:
            await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        assert excinfo.value.code == "attachment_resolver_unavailable"
        assert excinfo.value.status_code == 503
        assert PRIVATE_MARKER not in str(excinfo.value) + repr(excinfo.value)

    asyncio.run(scenario())


class ExplodingPort(FakeRecordingPort):
    async def fetch(self, attachment_ref: str) -> None:
        raise RuntimeError("private backend detail with " + PRIVATE_MARKER)


def test_unexpected_backend_failure_never_escapes_raw_detail() -> None:
    tick = MutableClock(BASE_TIME)
    store = ScopedImageByteStore(port=ExplodingPort(), clock=tick)
    resolver = _resolver_for(store, SCOPE)

    async def scenario() -> None:
        with pytest.raises(EngineAttachmentAuthorityError) as excinfo:
            await resolver.resolve_image(app_id=APP_ID, attachment_ref="att_" + "Y" * 32)
        assert excinfo.value.code == "attachment_resolver_unavailable"
        assert excinfo.value.status_code == 503
        assert PRIVATE_MARKER not in str(excinfo.value) + repr(excinfo.value)

    asyncio.run(scenario())


def test_invalid_provenance_factory_fails_closed_before_contract_return() -> None:
    store, _, _ = _pair()
    resolver = ByteStoreTrustedAttachmentResolver(store=store, scope=SCOPE, provenance_factory=lambda record: "bad provenance!")

    async def scenario() -> None:
        record = await _admit(store)
        with pytest.raises(EngineAttachmentAuthorityError) as excinfo:
            await resolver.resolve_image(app_id=APP_ID, attachment_ref=record.attachment_ref)
        assert excinfo.value.code == "invalid_attachment_authority"
        assert excinfo.value.status_code == 503

    asyncio.run(scenario())


# --- real consuming-service boundary ------------------------------------------------------


class FakeRuntime:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def run(self, request: Any) -> ExecutionResult:
        self.requests.append(request)
        return ExecutionResult(
            answer="사진 답변",
            route=B14RouteMetadata(
                selected_provider="provider-x",
                selected_model="provider-x/image",
                actual_response_model="provider-x/image",
                attempt_count=1,
                fallback_used=False,
            ),
            metadata=RunMetadata(
                trace_id="trace-2137",
                app_id=APP_ID,
                agent_id="image-agent",
                session_id="session-2137",
                status=RunStatus.COMPLETED,
                provider="provider-x",
                model="provider-x/image",
                duration_ms=12,
                usage=UsageMetadata(input_tokens=5, output_tokens=3, total_tokens=8),
            ),
        )


def _service(resolver: ByteStoreTrustedAttachmentResolver) -> tuple[MultimodalAttachmentEngineService, FakeRuntime]:
    runtime = FakeRuntime()
    return (
        MultimodalAttachmentEngineService(
            runtime_factory=lambda app_id: runtime,
            attachment_resolver=resolver,
        ),
        runtime,
    )


def _payload(ref: str, app_id: str = APP_ID) -> dict[str, Any]:
    return {
        "app_id": app_id,
        "agent": {
            "id": "image-agent",
            "title": "Image",
            "description": "Bounded image description assistant.",
            "system_instruction": "Describe the image carefully.",
            "task_type": "general",
            "optimize_for": "korean",
            "max_tokens": 512,
            "required_capabilities": ["chat", "image"],
            "model_policy": {"model": "b14/auto", "allow_external_fallback": False, "max_attempts": 1},
        },
        "messages": [{"role": "user", "content": "이 사진을 설명해줘"}],
        "attachment_ref": ref,
        "session_id": "session-2137",
        "trace_id": "trace-2137",
    }


def test_service_resolves_through_the_real_store_boundary() -> None:
    store, _, resolver = _pair()
    service, runtime = _service(resolver)

    async def scenario() -> None:
        record = await _admit(store)
        response = await service.execute_payload(_payload(record.attachment_ref))
        assert response.status_code == 200
        assert response.body["answer"] == "사진 답변"
        assert response.body["attachment"] == {
            "kind": "image",
            "media_type": "image/png",
            "byte_size": len(PNG_BYTES),
            "provenance_id": FIXED_PROVENANCE,
        }
        assert repr(PNG_BYTES) not in repr(response.body)
        assert runtime.requests and runtime.requests[0].messages

    asyncio.run(scenario())


def test_service_maps_store_failures_to_authority_status_codes() -> None:
    store, _, resolver = _pair()
    service, _ = _service(resolver)

    async def scenario() -> None:
        record = await _admit(store)
        cases = {
            "cross_app": await service.execute_payload(_payload(record.attachment_ref, app_id="other.app")),
            "unknown": await service.execute_payload(_payload("att_" + "W" * 32)),
        }
        assert cases["cross_app"].status_code == 403
        assert cases["cross_app"].body["error"]["code"] == "attachment_scope_mismatch"
        assert cases["unknown"].status_code == 404
        assert cases["unknown"].body["error"]["code"] == "attachment_not_found"

    asyncio.run(scenario())


# --- zero-leak, purity and source-only boundary --------------------------------------------


def test_errors_never_echo_payload_or_scope_values() -> None:
    store, _, resolver = _pair()

    async def scenario() -> None:
        record = await _admit(store, data=PNG_BYTES + PRIVATE_MARKER.encode("ascii"))
        failures = []
        for attempt in (
            resolver.resolve_image(app_id="nope", attachment_ref=record.attachment_ref),
            resolver.resolve_image(app_id=APP_ID, attachment_ref="att_" + "V" * 32),
            resolver.resolve_image(app_id=APP_ID, attachment_ref="not-an-ref"),
        ):
            try:
                await attempt
            except EngineAttachmentAuthorityError as exc:
                failures.append(exc)
        assert len(failures) == 3
        for exc in failures:
            rendered = str(exc) + repr(exc) + exc.code
            assert PRIVATE_MARKER not in rendered
            assert record.attachment_ref not in rendered
            assert SUBJECT_ID not in rendered and TENANT_ID not in rendered

    asyncio.run(scenario())


def test_module_is_pure_and_declares_no_io_or_schema() -> None:
    source = (APP_ROOT / "app" / "attachment_resolver.py").read_text(encoding="utf-8")
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
    assert "environ" not in source


def test_resolver_is_not_wired_into_production_composition() -> None:
    for name in (
        "engine_composition.py",
        "multimodal_attachment_service.py",
        "attachment_byte_store.py",
        "attachment_authority.py",
        "document_context_service.py",
    ):
        source = (APP_ROOT / "app" / name).read_text(encoding="utf-8")
        assert "from app.attachment_resolver" not in source
        assert "import attachment_resolver" not in source
        assert "ByteStoreTrustedAttachmentResolver" not in source
    identity_path = APP_ROOT / "worker_identity.py"
    if identity_path.exists():
        identity = identity_path.read_text(encoding="utf-8")
        assert "from app.attachment_resolver" not in identity
        assert "ByteStoreTrustedAttachmentResolver" not in identity
    wrangler = (APP_ROOT / "wrangler.toml").read_text(encoding="utf-8")
    assert "attachment" not in wrangler.lower()
