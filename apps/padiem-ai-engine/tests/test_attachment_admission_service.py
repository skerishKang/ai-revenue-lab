"""Trusted admission boundary acceptance tests for Engine E5C (#2727).

The store behind the service is the canonical ``ScopedImageByteStore`` over
``InMemoryImageByteStore``; the scope seam is either a stand-in for the
server-minted authority or the real ``AuthSessionScopeAuthority`` over a fake
Control Plane session client. No network, filesystem or provider access.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.attachment_admission_service import (  # noqa: E402
    ATTACHMENT_ADMISSION_PATH,
    MAX_ADMISSION_REQUEST_BODY_BYTES,
    AttachmentAdmissionEngineService,
)
from app.attachment_authority import EngineAttachmentAuthorityError  # noqa: E402
from app.attachment_byte_store import (  # noqa: E402
    MAX_STORED_IMAGE_BASE64_CHARS,
    MAX_STORED_IMAGE_BYTES,
    InMemoryImageByteStore,
    ScopedImageByteStore,
    StoredImageRecord,
)
from app.attachment_resolver import ByteStoreTrustedAttachmentResolver  # noqa: E402
from app.auth_session_scope_authority import AuthSessionScopeAuthority  # noqa: E402
from app.document_context_service import (  # noqa: E402
    DocumentAuthorityError,
    TrustedCallerScope,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"pixeldata" * 8
PNG_B64 = base64.b64encode(PNG_BYTES).decode("ascii")
BASE_TIME = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
SCOPE = TrustedCallerScope(app_id="app.revenue", subject_id="user.42", tenant_id="tenant.a")
PAYLOAD_MARKER = "PAYLOADMARKERNOTINRECEIPT-2727"
REF_GRAMMAR = re.compile(r"^att_[A-Za-z0-9_-]{16,120}$")


def _clock() -> datetime:
    return BASE_TIME


class RecordingStore:
    """Counts admission attempts while delegating to the canonical store."""

    def __init__(self, inner: ScopedImageByteStore) -> None:
        self.inner = inner
        self.calls: list[dict] = []

    async def admit_image(self, **kwargs) -> StoredImageRecord:
        self.calls.append(kwargs)
        return await self.inner.admit_image(**kwargs)

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


class FixedScopeAuthority:
    def __init__(self, scope: TrustedCallerScope | None = SCOPE) -> None:
        self.scope = scope
        self.calls: list[tuple[str, str]] = []

    async def scope_for_request(self, *, app_id: str, auth_session_id: str):
        self.calls.append((app_id, auth_session_id))
        if self.scope is None:
            raise DocumentAuthorityError(
                "auth_session_unavailable",
                "Control Plane auth session resolution is unavailable.",
                status_code=503,
            )
        return self.scope


def _service(
    store: RecordingStore | None = None,
    authority: FixedScopeAuthority | None = None,
) -> tuple[AttachmentAdmissionEngineService, RecordingStore, FixedScopeAuthority]:
    inner = RecordingStore(ScopedImageByteStore(port=InMemoryImageByteStore(), clock=_clock))
    real_store = store if store is not None else inner
    real_authority = authority if authority is not None else FixedScopeAuthority()
    service = AttachmentAdmissionEngineService(
        image_byte_store=real_store,
        scope_authority=real_authority,
    )
    return service, real_store, real_authority


def _payload(**overrides) -> dict:
    body = {
        "app_id": "app.revenue",
        "session_id": "sess.0123456789abcdef",
        "media_type": "image/png",
        "image_base64": PNG_B64,
    }
    body.update(overrides)
    return body


def _admit(service: AttachmentAdmissionEngineService, payload: dict):
    return asyncio.run(service.admit_payload(payload))


# --- happy path receipt ---------------------------------------------------------------


def test_admission_mints_server_opaque_ref_and_returns_bounded_receipt() -> None:
    service, store, authority = _service()

    response = _admit(service, _payload())

    assert response.status_code == 200
    attachment = response.body["attachment"]
    assert response.body["ok"] is True
    assert set(attachment) == {
        "attachment_ref",
        "media_type",
        "byte_size",
        "expires_at",
    }
    assert REF_GRAMMAR.fullmatch(attachment["attachment_ref"])
    assert attachment["media_type"] == "image/png"
    assert attachment["byte_size"] == len(PNG_BYTES)
    assert attachment["expires_at"] is None
    assert authority.calls == [("app.revenue", "sess.0123456789abcdef")]
    assert store.calls == [
        {
            "data": PNG_BYTES,
            "media_type": "image/png",
            "app_id": SCOPE.app_id,
            "tenant_id": SCOPE.tenant_id,
            "subject_id": SCOPE.subject_id,
        }
    ]


def test_receipt_body_never_leaks_scope_storage_or_payload_state() -> None:
    service, _store, _authority = _service()
    payload = _payload(
        image_base64=base64.b64encode(PNG_BYTES + PAYLOAD_MARKER.encode()).decode("ascii")
    )

    response = _admit(service, payload)

    serialized = str(response.body)
    assert PAYLOAD_MARKER not in serialized
    assert SCOPE.tenant_id not in serialized
    assert SCOPE.subject_id not in serialized
    assert "padiem_engine_attachment_images" not in serialized
    assert "data:" not in serialized


def test_admitted_ref_resolves_through_existing_e5a_trusted_resolver() -> None:
    store = ScopedImageByteStore(port=InMemoryImageByteStore(), clock=_clock)
    service = AttachmentAdmissionEngineService(
        image_byte_store=store,
        scope_authority=FixedScopeAuthority(),
    )

    async def scenario() -> None:
        response = await service.admit_payload(_payload())
        assert response.status_code == 200
        ref = response.body["attachment"]["attachment_ref"]
        resolver = ByteStoreTrustedAttachmentResolver(store=store, scope=SCOPE)
        resolved = await resolver.resolve_image(app_id=SCOPE.app_id, attachment_ref=ref)
        assert resolved.data == PNG_BYTES
        assert resolved.media_type == "image/png"
        assert resolved.attachment_ref == ref

    asyncio.run(scenario())


def test_other_scope_cannot_read_admitted_attachment() -> None:
    store = ScopedImageByteStore(port=InMemoryImageByteStore(), clock=_clock)
    service = AttachmentAdmissionEngineService(
        image_byte_store=store,
        scope_authority=FixedScopeAuthority(),
    )

    async def scenario() -> None:
        ref = (await service.admit_payload(_payload())).body["attachment"]["attachment_ref"]
        alien = TrustedCallerScope(
            app_id="app.other", subject_id="user.99", tenant_id="tenant.b"
        )
        with pytest.raises(EngineAttachmentAuthorityError):
            await ByteStoreTrustedAttachmentResolver(store=store, scope=alien).resolve_image(
                app_id="app.other", attachment_ref=ref
            )

    asyncio.run(scenario())


# --- wire shape fails closed -----------------------------------------------------------


def test_non_mapping_payload_is_invalid_request() -> None:
    service, store, _authority = _service()

    response = _admit(service, ["not", "an", "object"])

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert store.calls == []


@pytest.mark.parametrize(
    "missing",
    ["app_id", "session_id", "media_type", "image_base64"],
)
def test_missing_required_fields_fail_closed(missing: str) -> None:
    service, store, _authority = _service()
    payload = _payload()
    del payload[missing]

    response = _admit(service, payload)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert store.calls == []


@pytest.mark.parametrize(
    "field",
    ["tenant_id", "subject_id", "attachment_ref", "locator", "expires_in_seconds", "agent"],
)
def test_client_side_scope_reference_and_expiry_fields_are_rejected(field: str) -> None:
    service, store, _authority = _service()

    response = _admit(service, _payload(**{field: "whatever"}))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert store.calls == [] and _authority.calls == []


@pytest.mark.parametrize("field", ["app_id", "session_id", "media_type", "image_base64"])
def test_non_string_fields_fail_closed(field: str) -> None:
    service, store, _authority = _service()

    response = _admit(service, _payload(**{field: 42}))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert store.calls == []


def test_trace_id_is_accepted_but_not_required() -> None:
    service, _store, _authority = _service()

    response = _admit(service, _payload(trace_id="trace-2727"))

    assert response.status_code == 200


def test_bad_trace_id_still_fails_closed() -> None:
    service, store, _authority = _service()

    response = _admit(service, _payload(trace_id=7))

    assert response.status_code == 400
    assert store.calls == []


# --- payload validation mirrors the canonical store -------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["not base64!!", "c29tZQ==x", "\u00e9\u00e8"],
)
def test_invalid_base64_fails_closed_before_any_store_write(bad: str) -> None:
    service, store, authority = _service()

    response = _admit(service, _payload(image_base64=bad))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_attachment_base64"
    assert store.calls == [] and authority.calls == []


def test_unpadded_or_multi_line_base64_is_rejected() -> None:
    service, store, authority = _service()

    response = _admit(service, _payload(image_base64=PNG_B64[:-1]))
    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_attachment_base64"

    response = _admit(service, _payload(image_base64=PNG_B64[:10] + "\n" + PNG_B64[10:]))
    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_attachment_base64"
    assert store.calls == [] and authority.calls == []


def test_empty_payload_maps_canonical_store_error() -> None:
    service, store, _authority = _service()

    response = _admit(service, _payload(image_base64=""))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "empty_payload"
    assert len(store.calls) == 1  # the canonical store made this call, not the wire


@pytest.mark.parametrize("media", ["image/gif", "application/pdf", "text/plain", ""])
def test_unsupported_media_type_maps_canonical_store_error(media: str) -> None:
    service, store, _authority = _service()

    response = _admit(service, _payload(media_type=media))

    assert response.status_code == 415
    assert response.body["error"]["code"] == "unsupported_media_type"
    assert store.inner._port._records == {}


def test_media_type_is_case_and_space_normalized_by_the_canonical_store() -> None:
    service, store, _authority = _service()

    response = _admit(service, _payload(media_type=" IMAGE/PNG "))

    assert response.status_code == 200
    assert response.body["attachment"]["media_type"] == "image/png"
    assert len(store.inner._port._records) == 1


def test_decoded_size_above_store_ceiling_is_rejected() -> None:
    big = b"\x89PNG\r\n\x1a\n" + bytes(MAX_STORED_IMAGE_BYTES - 8 + 1)
    service, store, _authority = _service()

    response = _admit(service, _payload(image_base64=base64.b64encode(big).decode("ascii")))

    assert response.status_code == 413
    assert response.body["error"]["code"] == "attachment_too_large"
    # The canonical store made the rejection; the wire never stored anything.
    assert len(store.calls) == 1
    assert store.inner._port._records == {}


def test_encoded_b64_bound_is_enforced_before_decoding() -> None:
    service, store, _authority = _service()
    oversized = "A" * (MAX_STORED_IMAGE_BASE64_CHARS + 1)

    response = _admit(service, _payload(image_base64=oversized))

    assert response.status_code == 413
    assert response.body["error"]["code"] == "attachment_too_large"
    assert store.calls == [] and _authority.calls == []


# --- authority fail-closed seams ---------------------------------------------------------


def test_missing_store_fails_closed_as_503_after_wire_validation() -> None:
    service = AttachmentAdmissionEngineService(
        image_byte_store=None,
        scope_authority=FixedScopeAuthority(),
    )

    response = _admit(service, _payload())

    assert response.status_code == 503
    assert response.body["error"]["code"] == "attachment_admission_unavailable"


def test_missing_scope_authority_fails_closed_without_touching_store() -> None:
    service, store, _authority = _service()
    service = AttachmentAdmissionEngineService(
        image_byte_store=store,
        scope_authority=None,
    )

    response = _admit(service, _payload())

    assert response.status_code == 503
    assert response.body["error"]["code"] == "attachment_admission_unavailable"
    assert store.calls == []


def test_unresolved_session_maps_authority_error() -> None:
    authority = FixedScopeAuthority(scope=None)
    service = AttachmentAdmissionEngineService(
        image_byte_store=RecordingStore(
            ScopedImageByteStore(port=InMemoryImageByteStore(), clock=_clock)
        ),
        scope_authority=authority,
    )

    response = _admit(service, _payload())

    assert response.status_code == 503
    assert response.body["error"]["code"] == "auth_session_unavailable"


# --- real scope authority over a fake Control Plane client --------------------------------


class FakeSessionClient:
    def __init__(self, drop_tenant: bool = False, **overrides) -> None:
        self.drop_tenant = drop_tenant
        self.overrides = overrides

    async def resolve_auth_session(self, *, session_id: str):
        session = {
            "session_id": session_id,
            "product_id": "app.revenue",
            "subject": {"subject_type": "user", "subject_id": "user.42"},
            "tenant_id": "tenant.a",
            "issued_at": BASE_TIME.isoformat(),
            "expires_at": BASE_TIME.replace(hour=13).isoformat(),
            "state": "active",
            "revision": 1,
        }
        session.update(self.overrides)
        if self.drop_tenant:
            session.pop("tenant_id")
        return session


def _live_service(session_client_overrides=None, *, drop_tenant: bool = False):
    store = ScopedImageByteStore(port=InMemoryImageByteStore(), clock=_clock)
    authority = AuthSessionScopeAuthority(
        session_client=FakeSessionClient(drop_tenant=drop_tenant, **(session_client_overrides or {})),
        clock=_clock,
    )
    return AttachmentAdmissionEngineService(image_byte_store=store, scope_authority=authority), store


def test_live_authority_admission_stores_session_minted_scope() -> None:
    service, store = _live_service()

    response = _admit(service, _payload())
    assert response.status_code == 200
    ref = response.body["attachment"]["attachment_ref"]
    record, data = asyncio.run(
        store.fetch_image(
            attachment_ref=ref,
            app_id="app.revenue",
            tenant_id="tenant.a",
            subject_id="user.42",
        )
    )
    assert data == PNG_BYTES
    assert record.tenant_id == "tenant.a"


def test_cross_app_session_binding_fails_closed() -> None:
    service, store = _live_service({"product_id": "app.evil"})

    response = _admit(service, _payload())

    assert response.status_code == 403
    assert response.body["error"]["code"] == "auth_scope_mismatch"
    assert store._port._records == {}


def test_revoked_session_fails_closed() -> None:
    service, _store = _live_service({"state": "revoked"})

    response = _admit(service, _payload())

    assert response.status_code == 403
    assert response.body["error"]["code"] == "auth_session_inactive"


def test_missing_tenant_never_defaults_or_aliases() -> None:
    service, store = _live_service(drop_tenant=True)

    response = _admit(service, _payload())

    assert response.status_code == 503
    assert response.body["error"]["code"] == "tenant_unavailable"
    assert store._port._records == {}


# --- transport boundary ---------------------------------------------------------------------


def _handle(service, *, method="POST", path=ATTACHMENT_ADMISSION_PATH, content_type="application/json", body=b"{}"):
    return asyncio.run(
        service.handle(method=method, path=path, content_type=content_type, body=body)
    )


def test_handle_rejects_wrong_path_and_method_and_content_type() -> None:
    service, store, _authority = _service()

    assert _handle(service, path="/internal/v1/multimodal/execute").status_code == 404
    assert _handle(service, method="GET").status_code == 405
    assert _handle(service, content_type="text/plain").status_code == 415
    assert _handle(service, method="get", path="/nope").status_code == 404
    assert store.calls == []


def test_handle_rejects_oversized_raw_body_before_parsing() -> None:
    service, store, _authority = _service()

    response = _handle(service, body=b"x" * (MAX_ADMISSION_REQUEST_BODY_BYTES + 1))

    assert response.status_code == 413
    assert response.body["error"]["code"] == "request_too_large"
    assert store.calls == []


def test_handle_rejects_invalid_json() -> None:
    service, store, _authority = _service()

    response = _handle(service, body=b"{not json")

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_json"
    assert store.calls == []


def test_handle_round_trips_valid_envelope() -> None:
    import json

    service, _store, _authority = _service()

    response = _handle(service, body=json.dumps(_payload()).encode("utf-8"))

    assert response.status_code == 200
    assert REF_GRAMMAR.fullmatch(response.body["attachment"]["attachment_ref"])


def test_constructor_shape_checks() -> None:
    with pytest.raises(ValueError):
        AttachmentAdmissionEngineService(image_byte_store=object(), scope_authority=None)
    with pytest.raises(ValueError):
        AttachmentAdmissionEngineService(image_byte_store=None, scope_authority=object())
