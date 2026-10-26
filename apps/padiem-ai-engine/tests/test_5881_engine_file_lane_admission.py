"""#5881 stage 3: a COM2 ``file_id`` attachment reaches the document context path.

Three load-bearing contracts:

* the reference shape is read from the configured lane origin and admitted
  through the same ``admit_document`` authority the inline path uses, so the
  existing trusted resolver and context projection consume it unchanged;
* with no configured origin the inline path answers byte-for-byte what it
  answered before this slice, and a reference request fails closed without an
  outbound read;
* a document longer than one window mounts only that window and reports the
  continuation coordinates instead of pretending the text ended there.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

import httpx
import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.document_admission_service import (  # noqa: E402
    DOCUMENT_ADMISSION_PATH,
    DocumentAdmissionEngineService,
)
from app.document_byte_store import (  # noqa: E402
    InMemoryDocumentByteStore,
    ScopedDocumentByteStore,
)
from app.document_context_projection import (  # noqa: E402
    ContextWindowProjection,
    MAX_CONTEXT_PREVIEW_CHARS,
)
from app.document_context_service import TrustedCallerScope  # noqa: E402
from app.file_lane_text_port import (  # noqa: E402
    FILE_LANE_ORIGIN_ENV,
    FILE_TICKET_HEADER_NAMES,
    FileLaneTextError,
    FileLaneTextPort,
)
from app.trusted_document_resolver import (  # noqa: E402
    DurableDocumentStoragePort,
    TrustedDocumentResolver,
    resolve_and_normalize,
)

BASE_TIME = datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc)
SCOPE = TrustedCallerScope(app_id="app.revenue", subject_id="user.42", tenant_id="tenant.a")
ORIGIN = "https://files.example.test"
FILE_ID = "file_" + "ab12" * 8
SHA256 = "0" * 64
INLINE_TEXT = b"quarterly revenue projections for beta-corp"
INLINE_B64 = base64.b64encode(INLINE_TEXT).decode("ascii")
MARKER = "LANEWINDOWMARKER-5881"
DOCUMENT_TEXT = MARKER + " revenue projections for beta-corp"
LONG_DOCUMENT = "가" * (MAX_CONTEXT_PREVIEW_CHARS + 40)
REF_GRAMMAR = re.compile(r"^doc_[A-Za-z0-9_-]{16,120}$")
# Sentinel: answer the lane's own computed value. ``None`` omits the header.
_DEFAULT = object()
TICKET = {
    "X-Padiem-File-Ticket": "eyJ1c2VyX2lkIjoidXNlci00MiIsIm1heF9ieXRlcyI6MX0",
    "X-Padiem-File-Time": "1761550000",
    "X-Padiem-File-Proof": "f" * 64,
}


class RecordingStore:
    def __init__(self, inner: ScopedDocumentByteStore) -> None:
        self.inner = inner
        self.calls: list[dict] = []

    async def admit_document(self, **kwargs) -> object:
        record = await self.inner.admit_document(**kwargs)
        # Record only completed admissions: a pre-delegation append would hide
        # the proof that a refused request wrote nothing.
        self.calls.append(kwargs)
        return record

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


class FixedScopeAuthority:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def scope_for_request(self, *, app_id: str, auth_session_id: str):
        self.calls.append((app_id, auth_session_id))
        return SCOPE


def _lane(
    document: str,
    *,
    next_offset: object = _DEFAULT,
    eof: object = _DEFAULT,
    total_chars: object = _DEFAULT,
    failure_status: int | None = None,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    """Mock of the merged lane window contract: it slices exactly as COM2 does."""

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if failure_status is not None:
            return httpx.Response(
                failure_status, json={"ok": False, "error": {"code": "encrypted_pdf"}}
            )
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["max_chars"])
        window = document[offset : offset + limit]
        reached = offset + len(window)
        headers = {
            "X-File-Lane-Next-Offset": (
                str(reached) if next_offset is _DEFAULT else next_offset
            ),
            "X-File-Lane-EOF": (
                str(reached >= len(document)).lower() if eof is _DEFAULT else eof
            ),
            # The saved count: known whatever length this window happened to be.
            "X-File-Lane-Total-Chars": (
                str(len(document)) if total_chars is _DEFAULT else total_chars
            ),
        }
        # ``None`` answers the header away: an origin that does not implement
        # the window contract must not be silently read as end of file.
        return httpx.Response(
            200,
            text=window,
            headers={key: value for key, value in headers.items() if value is not None},
        )

    return httpx.MockTransport(handler), seen


def _service(
    *, origin: str | None = ORIGIN, document: str = DOCUMENT_TEXT, **lane_kwargs
) -> tuple[DocumentAdmissionEngineService, RecordingStore, FixedScopeAuthority, list]:
    transport, seen = _lane(document, **lane_kwargs)
    store = RecordingStore(
        ScopedDocumentByteStore(port=InMemoryDocumentByteStore(), clock=lambda: BASE_TIME)
    )
    authority = FixedScopeAuthority()
    service = DocumentAdmissionEngineService(
        document_byte_store=store,
        scope_authority=authority,
        file_lane_text_port=(
            None if origin is None else FileLaneTextPort(origin=origin, transport=transport)
        ),
    )
    return service, store, authority, seen


def _reference_payload(**overrides: object) -> dict:
    body: dict[str, object] = {
        "app_id": "app.revenue",
        "session_id": "sess.0123456789abcdef",
        "file_id": FILE_ID,
        "sha256": SHA256,
        "file_ticket": dict(TICKET),
    }
    body.update(overrides)
    return body


def _inline_payload(**overrides: object) -> dict:
    body: dict[str, object] = {
        "app_id": "app.revenue",
        "session_id": "sess.0123456789abcdef",
        "media_type": "text/plain",
        "document_base64": INLINE_B64,
    }
    body.update(overrides)
    return body


def _admit(service: DocumentAdmissionEngineService, payload: dict):
    return asyncio.run(service.admit_payload(payload))


def _stable_body(body: dict) -> bytes:
    """Serialize a receipt with the randomly minted reference neutralized."""

    copy = json.loads(json.dumps(body))
    document = copy.get("document")
    if isinstance(document, dict):
        document["document_ref"] = "doc_stable"
        document["expires_at"] = None
    return json.dumps(copy, sort_keys=True).encode("utf-8")


# --- 1. the file_id path ----------------------------------------------------------


def test_file_id_reference_reads_lane_and_feeds_existing_document_context() -> None:
    service, store, authority, seen = _service()

    response = _admit(service, _reference_payload(filename="  quarterly report.pdf "))

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert str(request.url) == (
        f"{ORIGIN}/files/{FILE_ID}/text?offset=0&max_chars={MAX_CONTEXT_PREVIEW_CHARS}"
    )
    # Chat's signed ticket travels through untouched; Engine holds no secret.
    for name in FILE_TICKET_HEADER_NAMES:
        assert request.headers[name] == TICKET[name]
    document = response.body["document"]
    assert REF_GRAMMAR.fullmatch(document["document_ref"])
    assert document["media_type"] == "text/plain"
    assert document["byte_size"] == len(DOCUMENT_TEXT.encode("utf-8"))
    assert document["total_chars"] == len(DOCUMENT_TEXT)
    assert document["next_offset"] == len(DOCUMENT_TEXT)
    assert document["window_eof"] is True
    assert store.calls == [
        {
            "data": DOCUMENT_TEXT.encode("utf-8"),
            "media_type": "text/plain",
            # The lane text is plain text whatever the source was: the stem
            # stays, the suffix follows the admitted media type.
            "name": "quarterly report.txt",
            "app_id": SCOPE.app_id,
            "tenant_id": SCOPE.tenant_id,
            "subject_id": SCOPE.subject_id,
        }
    ]
    assert authority.calls == [("app.revenue", "sess.0123456789abcdef")]
    receipt = json.dumps(response.body, ensure_ascii=False)
    assert DOCUMENT_TEXT not in receipt
    assert TICKET["X-Padiem-File-Proof"] not in receipt

    # The admitted reference is an ordinary document: the canonical trusted
    # resolver and context projection read it with no file-lane knowledge.
    resolver = TrustedDocumentResolver(storage=DurableDocumentStoragePort(store.inner))
    normalized = asyncio.run(
        resolve_and_normalize(
            resolver,
            document["document_ref"],
            app_id=SCOPE.app_id,
            subject_id=SCOPE.subject_id,
            tenant_id=SCOPE.tenant_id,
        )
    )
    projection = ContextWindowProjection.from_normalized(normalized)
    assert projection.text_chars == len(DOCUMENT_TEXT)
    assert projection.truncated_text_preview == DOCUMENT_TEXT


# --- 2. unset origin keeps the inline path byte-identical -------------------------


def test_unset_origin_answers_inline_bytes_identically_and_refuses_reference() -> None:
    unconfigured, store, authority, seen = _service(origin=None)
    # Built exactly as the admission lane was before this slice existed.
    before_this_slice = DocumentAdmissionEngineService(
        document_byte_store=RecordingStore(
            ScopedDocumentByteStore(port=InMemoryDocumentByteStore(), clock=lambda: BASE_TIME)
        ),
        scope_authority=FixedScopeAuthority(),
    )

    inline = _admit(unconfigured, _inline_payload())
    over_the_route = asyncio.run(
        unconfigured.handle(
            method="POST",
            path=DOCUMENT_ADMISSION_PATH,
            content_type="application/json",
            body=json.dumps(_inline_payload()).encode("utf-8"),
        )
    )
    legacy = _admit(before_this_slice, _inline_payload())

    assert inline.status_code == 200
    assert _stable_body(inline.body) == _stable_body(legacy.body)
    assert _stable_body(over_the_route.body) == _stable_body(legacy.body)
    assert set(inline.body["document"]) == {
        "document_ref", "media_type", "byte_size", "expires_at",
    }
    assert _stable_body(inline.body) == json.dumps(
        {
            "ok": True,
            "document": {
                "document_ref": "doc_stable",
                "media_type": "text/plain",
                "byte_size": len(INLINE_TEXT),
                "expires_at": None,
            },
        },
        sort_keys=True,
    ).encode("utf-8")
    assert [call["data"] for call in store.calls] == [INLINE_TEXT, INLINE_TEXT]
    assert seen == []

    refused = _admit(unconfigured, _reference_payload())

    assert refused.status_code == 503
    assert refused.body["error"]["code"] == "file_lane_unavailable"
    assert "example.test" not in json.dumps(refused.body)
    # No outbound read and no half-started admission: the session was never even
    # resolved, so the refusal cannot consume an auth-session lookup either.
    assert seen == []
    assert len(store.calls) == 2
    assert len(authority.calls) == 2


# --- 3. windowed read -------------------------------------------------------------


def test_long_document_mounts_first_window_and_reports_continuation() -> None:
    service, store, _authority, seen = _service(document=LONG_DOCUMENT)

    response = _admit(service, _reference_payload())

    assert response.status_code == 200
    assert len(seen) == 1
    assert seen[0].url.params["offset"] == "0"
    assert seen[0].url.params["max_chars"] == str(MAX_CONTEXT_PREVIEW_CHARS)
    document = response.body["document"]
    window = LONG_DOCUMENT[:MAX_CONTEXT_PREVIEW_CHARS]
    assert document["next_offset"] == MAX_CONTEXT_PREVIEW_CHARS
    # The lane counted the whole document when it saved the text, so a window
    # that stops mid-document still states the real length.
    assert document["total_chars"] == len(LONG_DOCUMENT)
    assert document["window_eof"] is False
    assert document["byte_size"] == len(window.encode("utf-8"))
    assert store.calls[0]["data"] == window.encode("utf-8")
    assert len(store.calls[0]["data"].decode("utf-8")) == MAX_CONTEXT_PREVIEW_CHARS

    # An origin that answers without the saved count claims nothing it cannot
    # prove: exact at end of file, unclaimed while text still follows.
    unreported, unreported_store, _unreported_authority, _unreported_seen = _service(
        document=LONG_DOCUMENT, total_chars=None
    )
    partial = _admit(unreported, _reference_payload())
    assert partial.body["document"]["total_chars"] is None
    assert partial.body["document"]["next_offset"] == MAX_CONTEXT_PREVIEW_CHARS
    assert unreported_store.calls[0]["data"] == window.encode("utf-8")

    short_unreported, _short_store, _authority, _seen = _service(
        document="끝.", total_chars=None
    )
    ended = _admit(short_unreported, _reference_payload())
    assert ended.body["document"]["total_chars"] == 2

    # A document that ends inside the first window reports an exact total.
    short_service, short_store, _short_authority, short_seen = _service(document="끝.")
    short = _admit(short_service, _reference_payload())

    assert short.status_code == 200
    assert len(short_seen) == 1
    assert short.body["document"]["total_chars"] == 2
    assert short.body["document"]["next_offset"] == 2
    assert short.body["document"]["window_eof"] is True
    assert short_store.calls[0]["data"] == "끝.".encode("utf-8")


# --- fail-closed boundaries -------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"file_id": "file_ZZ12" + "ab12" * 7},
        {"file_id": "file_" + "ab12" * 8 + "/../../etc/passwd"},
        {"file_id": 7},
        {"sha256": "0" * 63},
        {"sha256": "Z" * 64},
        {"file_ticket": {**TICKET, "X-Padiem-File-Proof": "inject\r\nX-Evil: 1"}},
        {"file_ticket": {k: v for k, v in TICKET.items() if k != "X-Padiem-File-Proof"}},
        {"file_ticket": "not-an-object"},
        {"document_base64": INLINE_B64},
        {"media_type": "application/pdf"},
        {"url": "https://caller-chosen.example"},
        {"origin": "https://caller-chosen.example"},
        {"tenant_id": "tenant.caller"},
    ],
    ids=[
        "file_id_not_hex", "file_id_traversal", "file_id_not_string", "sha256_short",
        "sha256_not_hex", "ticket_header_injection", "ticket_missing_name",
        "ticket_not_object", "inline_bytes_rejected", "caller_media_type_rejected",
        "caller_url_rejected", "caller_origin_rejected", "caller_tenant_rejected",
    ],
)
def test_reference_shape_fails_closed_without_read_or_write(overrides: dict) -> None:
    service, store, _authority, seen = _service()

    response = _admit(service, _reference_payload(**overrides))

    assert response.status_code == 400
    assert response.body["error"]["code"] == "invalid_request"
    assert seen == []
    assert store.calls == []


@pytest.mark.parametrize(
    ("status", "engine_status", "code"),
    [
        (401, 401, "file_lane_ticket_rejected"),
        (404, 404, "file_lane_file_not_found"),
        (422, 422, "file_lane_parse_failed"),
        (500, 502, "file_lane_read_failed"),
    ],
)
def test_lane_failure_surfaces_only_a_safe_code(
    status: int, engine_status: int, code: str
) -> None:
    service, store, _authority, seen = _service(failure_status=status)

    response = _admit(service, _reference_payload())

    assert response.status_code == engine_status
    assert response.body["error"]["code"] == code
    assert "encrypted_pdf" not in json.dumps(response.body)
    assert len(seen) == 1
    assert store.calls == []


@pytest.mark.parametrize(
    ("next_offset", "eof", "total_chars"),
    [
        ("999999", "true", _DEFAULT),
        (_DEFAULT, "maybe", _DEFAULT),
        (None, None, None),
        ("not-a-number", "true", _DEFAULT),
        (_DEFAULT, _DEFAULT, "999999999"),
        (_DEFAULT, _DEFAULT, "3"),
        (_DEFAULT, _DEFAULT, "nope"),
    ],
    ids=[
        "offset_mismatch", "eof_not_boolean", "headers_absent", "header_malformed",
        "total_beyond_end_of_file", "total_below_window_end", "total_malformed",
    ],
)
def test_malformed_window_headers_are_refused_instead_of_mounted(
    next_offset: str | None, eof: str | None, total_chars: str | None
) -> None:
    service, store, _authority, seen = _service(
        next_offset=next_offset, eof=eof, total_chars=total_chars
    )

    response = _admit(service, _reference_payload())

    assert response.status_code == 502
    assert response.body["error"]["code"] == "file_lane_invalid_response"
    assert len(seen) == 1
    assert store.calls == []


@pytest.mark.parametrize(
    "origin",
    [
        "http://files.example.test",
        "https://files.example.test/parse",
        "https://user:pass@files.example.test",
        "https://files.example.test?token=1",
        "https://files.example.test#x",
        "not a url",
        "",
        "files.example.test",
    ],
)
def test_only_a_bare_https_origin_is_configurable(origin: str) -> None:
    assert FILE_LANE_ORIGIN_ENV == "FILE_LANE_ORIGIN"

    with pytest.raises(FileLaneTextError):
        FileLaneTextPort(origin=origin, transport=httpx.MockTransport(lambda _r: httpx.Response(500)))
