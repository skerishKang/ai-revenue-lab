"""Wire-boundary tests for the #2741 document admission service.

Mirrors the image admission suite shape with the two #2741 hardenings under
test: mandatory server-minted expiry on every receipt and the cross-store
proof that an admitted ``doc_*`` reference resolves through the canonical
trusted resolver — but can never touch the image lane (or vice versa).
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.document_admission_service import (  # noqa: E402
    DOCUMENT_ADMISSION_PATH,
    MAX_DOCUMENT_ADMISSION_REQUEST_BODY_BYTES,
    DocumentAdmissionEngineService,
)
from app.document_byte_store import (  # noqa: E402
    MAX_STORED_DOCUMENT_BASE64_CHARS,
    InMemoryDocumentByteStore,
    ScopedDocumentByteStore,
)
from app.document_context_service import (  # noqa: E402
    DocumentAuthorityError,
    TrustedCallerScope,
)
from app.document_reference import require_document_reference  # noqa: E402
from app.trusted_document_resolver import (  # noqa: E402
    DurableDocumentStoragePort,
    DocumentResolutionError,
    TrustedDocumentResolver,
)

BASE_TIME = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)
SCOPE = TrustedCallerScope(app_id="app.revenue", subject_id="user.42", tenant_id="tenant.a")
PAYLOAD = b"quarterly revenue projections for beta-corp"
PAYLOAD_MARKER = "PAYLOADMARKERNOTINRECEIPT-2741"
REF_GRAMMAR = re.compile(r"^doc_[A-Za-z0-9_-]{16,120}$")
B64 = base64.b64encode(PAYLOAD).decode("ascii")


class RecordingStore:
    def __init__(self, inner: ScopedDocumentByteStore) -> None:
        self.inner = inner
        self.calls: list[dict] = []

    async def admit_document(self, **kwargs) -> object:
        record = await self.inner.admit_document(**kwargs)
        # record only completed admissions: failures must prove the store
        # wrote nothing, so a pre-delegation append would mask that.
        self.calls.append(kwargs)
        return record

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
) -> tuple[DocumentAdmissionEngineService, RecordingStore, FixedScopeAuthority]:
    inner = RecordingStore(
        ScopedDocumentByteStore(port=InMemoryDocumentByteStore(), clock=lambda: BASE_TIME)
    )
    real_store = store if store is not None else inner
    real_authority = authority if authority is not None else FixedScopeAuthority()
    service = DocumentAdmissionEngineService(
        document_byte_store=real_store,
        scope_authority=real_authority,
    )
    return service, real_store, real_authority


def _payload(**overrides: object) -> dict:
    body: dict[str, object] = {
        "app_id": "app.revenue",
        "session_id": "sess.0123456789abcdef",
        "media_type": "text/plain",
        "document_base64": B64,
    }
    body.update(overrides)
    return body


def _admit(service: DocumentAdmissionEngineService, payload: dict):
    return asyncio.run(service.admit_payload(payload))


# --- happy path receipt --------------------------------------------------------


def test_admission_mints_server_ref_and_returns_bounded_receipt_with_expiry() -> None:
    service, store, authority = _service()

    response = _admit(service, _payload())

    assert response.status_code == 200
    assert response.body["ok"] is True
    document = response.body["document"]
    assert set(document) == {"document_ref", "media_type", "byte_size", "expires_at"}
    assert REF_GRAMMAR.fullmatch(document["document_ref"])
    assert document["media_type"] == "text/plain"
    assert document["byte_size"] == len(PAYLOAD)
    # #2741 hardening: document receipts always carry a bounded expiry.
    assert document["expires_at"] is not None
    expires = datetime.fromisoformat(document["expires_at"])
    assert BASE_TIME < expires <= BASE_TIME + timedelta(days=7)
    assert authority.calls == [("app.revenue", "sess.0123456789abcdef")]
    assert store.calls == [
        {
            "data": PAYLOAD,
            "media_type": "text/plain",
            "name": "document.txt",  # server-derived default
            "app_id": SCOPE.app_id,
            "tenant_id": SCOPE.tenant_id,
            "subject_id": SCOPE.subject_id,
        }
    ]


@pytest.mark.parametrize(
    ("media_type", "default_name"),
    [
        ("text/plain", "document.txt"),
        ("text/markdown", "document.md"),
        ("text/csv", "document.csv"),
        ("application/json", "document.json"),
        ("application/pdf", "document.pdf"),
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "document.docx",
        ),
        (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "document.pptx",
        ),
        (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "document.xlsx",
        ),
        ("application/hwp+zip", "document.hwpx"),
    ],
)
def test_default_filename_is_derived_from_core_allowlists(media_type: str, default_name: str) -> None:
    service, store, _authority = _service()
    payload = _payload(media_type=media_type)
    response = _admit(service, payload)

    assert response.status_code == 200
    assert store.calls[0]["name"] == default_name


def test_filename_is_trimmed_and_carried_to_the_store() -> None:
    service, store, _authority = _service()
    response = _admit(service, _payload(filename="  quarterly report.txt "))

    assert response.status_code == 200
    assert store.calls[0]["name"] == "quarterly report.txt"


@pytest.mark.parametrize(
    "filename", ["   ", "x" * 121, "evil\nname", "tab\tname", "C:\\Windows\\x.txt" * 20, 7, []]
)
def test_malformed_filenames_fail_closed(filename: object) -> None:
    service, store, authority = _service()
    response = _admit(service, _payload(filename=filename))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert store.calls == []
    assert authority.calls == []


def test_receipt_never_leaks_payload_scope_or_storage_state() -> None:
    service, _store, _authority = _service()
    response = _admit(
        service, _payload(document_base64=base64.b64encode(PAYLOAD + PAYLOAD_MARKER.encode()).decode("ascii"))
    )

    serialized = str(response.body)
    assert PAYLOAD_MARKER not in serialized
    assert "quarterly revenue" not in serialized
    assert SCOPE.tenant_id not in serialized
    assert SCOPE.subject_id not in serialized
    assert "padiem_engine_document_bytes" not in serialized
    assert "data:" not in serialized


def test_two_admissions_of_same_bytes_never_share_a_reference() -> None:
    service, _store, _authority = _service()
    first = _admit(service, _payload())
    second = _admit(service, _payload())

    assert first.status_code == 200 and second.status_code == 200
    assert first.body["document"]["document_ref"] != second.body["document"]["document_ref"]


# --- closed wire shape -----------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "tenant_id",
        "subject_id",
        "document_ref",
        "attachment_ref",
        "expires_at",
        "expiry_ttl_seconds",
        "storage_locator",
        "url",
        "location",
        "trace_id",  # deliberately NOT part of this envelope
        "evidence_id",
    ],
)
def test_client_supplied_or_foreign_identity_fields_are_rejected(field: str) -> None:
    service, store, authority = _service()
    response = _admit(service, _payload(**{field: "caller-controlled"}))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert "caller-controlled" not in json.dumps(response.body)
    assert store.calls == []
    assert authority.calls == []


@pytest.mark.parametrize(
    "field", ["app_id", "session_id", "media_type", "document_base64"]
)
def test_each_required_field_is_mandatory(field: str) -> None:
    service, _store, _authority = _service()
    body = _payload()
    del body[field]
    response = _admit(service, body)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("value", [7, None, True, ["text/plain"]])
def test_required_fields_must_be_strings(value: object) -> None:
    service, _store, _authority = _service()
    response = _admit(service, _payload(media_type=value))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("payload", [None, "scalar", 3, [1, 2]])
def test_non_object_body_is_rejected(payload: object) -> None:
    service, _store, _authority = _service()
    response = _admit(service, payload)

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"


# --- base64 admission guard -------------------------------------------------------


def test_oversized_or_invalid_base64_is_rejected_before_any_store_touch() -> None:
    service, store, authority = _service()
    bad_candidates = [
        "not base64!!",
        "AAAA=extra",
        base64.b64encode(b"x").decode("ascii") + "  ",
        "A" * (MAX_STORED_DOCUMENT_BASE64_CHARS + 1),
    ]
    for bad in bad_candidates:
        response = _admit(service, _payload(document_base64=bad))

        assert response.status_code in (400, 413), bad[:16]
        assert response.body["ok"] is False
        assert store.calls == []
        assert authority.calls == []


def test_empty_decoded_payload_is_rejected_by_store_authority() -> None:
    service, store, _authority = _service()
    response = _admit(service, _payload(document_base64=""))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "empty_payload"
    assert store.calls == []


# --- media authority stays with the Core allowlists ----------------------------------


@pytest.mark.parametrize(
    ("media_type", "payload_marker"),
    [
        ("image/png", base64.b64encode(b"\x89PNG\r\n\x1a\nfake image bytes").decode("ascii")),
        ("application/octet-stream", B64),
        ("text/html", B64),
        ("application/x-hwp", B64),  # legacy HWP stays unsupported
        ("application/zip", B64),
    ],
)
def test_media_outside_document_allowlists_fails_closed_from_store(
    media_type: str, payload_marker: str
) -> None:
    service, store, _authority = _service()
    response = _admit(service, _payload(media_type=media_type, document_base64=payload_marker))

    assert response.status_code == 415
    assert response.body["error"]["code"] == "unsupported_media_type"
    assert store.calls == []  # the store refused the write: media authority proven fail-closed


def test_text_ceiling_is_enforced_from_core_constants() -> None:
    service, store, _authority = _service()
    too_big = base64.b64encode(b"x" * (1024 * 1024)).decode("ascii")
    response = _admit(service, _payload(media_type="text/plain", document_base64=too_big))

    assert response.status_code == 413
    assert response.body["error"]["code"] == "document_too_large"
    assert store.calls == []


# --- availability / scope failures ----------------------------------------------------


@pytest.mark.parametrize("omit", ["store", "authority"])
def test_missing_dependency_fails_closed_503(omit: str) -> None:
    built_store = RecordingStore(
        ScopedDocumentByteStore(port=InMemoryDocumentByteStore(), clock=lambda: BASE_TIME)
    )
    service = DocumentAdmissionEngineService(
        document_byte_store=None if omit == "store" else built_store,
        scope_authority=None if omit == "authority" else FixedScopeAuthority(),
    )
    response = _admit(service, _payload())

    assert response.status_code == 503
    assert response.body["error"]["code"] == "document_admission_unavailable"
    assert built_store.calls == []


def test_authority_error_codes_are_passed_through_unchanged() -> None:
    class Rejecting:
        async def scope_for_request(self, **_kwargs):
            raise DocumentAuthorityError(
                "auth_scope_mismatch", "Caller app does not own this session.", status_code=403
            )

    service = DocumentAdmissionEngineService(
        document_byte_store=RecordingStore(
            ScopedDocumentByteStore(port=InMemoryDocumentByteStore(), clock=lambda: BASE_TIME)
        ),
        scope_authority=Rejecting(),
    )
    response = _admit(service, _payload())

    assert response.status_code == 403
    assert response.body["error"]["code"] == "auth_scope_mismatch"


def test_authority_internal_failures_never_reflect_internals() -> None:
    class Exploding:
        async def scope_for_request(self, **_kwargs):
            raise RuntimeError("session row 991 leak")

    service = DocumentAdmissionEngineService(
        document_byte_store=RecordingStore(
            ScopedDocumentByteStore(port=InMemoryDocumentByteStore(), clock=lambda: BASE_TIME)
        ),
        scope_authority=Exploding(),
    )
    response = _admit(service, _payload())

    assert response.status_code == 503
    assert response.body["error"]["code"] == "document_admission_unavailable"
    assert "991" not in json.dumps(response.body)


# --- cross-store proof: admitted doc_* resolves ONLY through the document lane ---------


def test_admitted_reference_resolves_through_canonical_trusted_resolver() -> None:
    service, store, _authority = _service()
    response = _admit(service, _payload())
    assert response.status_code == 200
    ref = response.body["document"]["document_ref"]

    resolver = TrustedDocumentResolver(
        storage=DurableDocumentStoragePort(store.inner)
    )
    raw, meta = asyncio.run(
        resolver.resolve(ref, app_id=SCOPE.app_id, subject_id=SCOPE.subject_id, tenant_id=SCOPE.tenant_id)
    )
    assert raw == PAYLOAD
    assert meta.byte_size == len(PAYLOAD)

    with pytest.raises(DocumentResolutionError) as foreign:
        asyncio.run(
            resolver.resolve(
                ref, app_id="app.other", subject_id=SCOPE.subject_id, tenant_id=SCOPE.tenant_id
            )
        )
    assert foreign.value.code == "unauthorized"


def test_admitted_reference_is_a_legal_document_reference_never_an_att_reference() -> None:
    service, _store, _authority = _service()
    ref = _admit(service, _payload()).body["document"]["document_ref"]

    assert require_document_reference(ref) == ref
    assert not ref.startswith("att_")


# --- route envelope --------------------------------------------------------------


def _post(service: DocumentAdmissionEngineService, *, method="POST", path=DOCUMENT_ADMISSION_PATH, ctype="application/json", body=b"{}"):
    return asyncio.run(service.handle(method=method, path=path, content_type=ctype, body=body))


def test_route_accepts_posted_json_envelope() -> None:
    service, store, _authority = _service()
    response = _post(service, body=json.dumps(_payload()).encode("utf-8"))

    assert response.status_code == 200
    assert store.calls and store.calls[0]["data"] == PAYLOAD


@pytest.mark.parametrize(
    ("kwargs", "code", "status"),
    [
        ({"path": "/internal/v1/documentsx"}, "not_found", 404),
        ({"method": "get"}, "method_not_allowed", 405),
        ({"ctype": "text/plain"}, "unsupported_media_type", 415),
        ({"ctype": None}, "unsupported_media_type", 415),
        ({"body": b"{oops"}, "invalid_json", 400),
        ({"body": b"\xff\xfe"}, "invalid_json", 400),
    ],
)
def test_route_surface_fails_closed_on_shape(kwargs: dict, code: str, status: int) -> None:
    service, store, _authority = _service()
    response = _post(service, **kwargs)

    assert response.status_code == status
    assert response.body["error"]["code"] == code
    assert store.calls == []


def test_route_body_ceiling_matches_admission_bound() -> None:
    service, _store, _authority = _service()
    response = _post(service, body=b"x" * (MAX_DOCUMENT_ADMISSION_REQUEST_BODY_BYTES + 1))

    assert response.status_code == 413
    assert response.body["error"]["code"] == "request_too_large"
