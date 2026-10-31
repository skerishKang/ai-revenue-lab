"""#5881: the Engine document receipt and the Python client projection cannot drift.

The client mirrors the reference grammar so a bad request fails before any
transport, and it projects the Engine receipt into a fixed field set. Both
mirrors are only safe while they agree with the Engine's own modules, so this
suite pins them against the running service rather than against copied text.

  ENGINE_ROUTE_PATH_PINNED          = PASS
  TICKET_HEADER_NAMES_PINNED        = PASS
  REFERENCE_GRAMMAR_PINNED          = PASS
  WINDOW_SIZE_PINNED                = PASS
  REAL_RECEIPT_ACCEPTED_BY_CLIENT   = PASS
  RECEIPT_FIELD_SET_PINNED          = PASS
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import httpx
import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
CLIENT_ROOT = APP_ROOT / "clients" / "python"
if str(CLIENT_ROOT) not in sys.path:
    sys.path.insert(0, str(CLIENT_ROOT))

from app.document_admission_service import (  # noqa: E402
    DOCUMENT_ADMISSION_PATH,
    LANE_DOCUMENT_MEDIA_TYPE,
    DocumentAdmissionEngineService,
)
from app.document_byte_store import (  # noqa: E402
    InMemoryDocumentByteStore,
    ScopedDocumentByteStore,
)
from app.document_context_projection import MAX_CONTEXT_PREVIEW_CHARS  # noqa: E402
from app.document_context_service import TrustedCallerScope  # noqa: E402
from app.file_lane_text_port import (  # noqa: E402
    DEFAULT_TEXT_WINDOW_CHARS,
    FILE_ID_PATTERN,
    FILE_TICKET_HEADER_NAMES,
    FileLaneTextPort,
)

from padiem_ai_engine_client import (  # noqa: E402
    DOCUMENT_LANE_MEDIA_TYPE,
    ENGINE_DOCUMENT_ADMISSION_PATH,
    EngineTransportResponse,
    FILE_TICKET_HEADER_NAMES as CLIENT_TICKET_HEADER_NAMES,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)

BASE_TIME = datetime(2026, 10, 27, 9, 0, 0, tzinfo=timezone.utc)
APP_ID = "b54-padiem-claw"
SCOPE = TrustedCallerScope(app_id=APP_ID, subject_id="user.42", tenant_id="tenant.a")
SESSION_ID = "sess_subject:b54-padiem-claw:user.42"
FILE_ID = "file_" + "ab12" * 8
SHA256 = "0" * 64
TEXT = "COM2 owns the document bytes; the Engine reads only this text."
TICKET = {
    "X-Padiem-File-Ticket": "eyJ1c2VyX2lkIjoidXNyXzQyIiwibWF4X2J5dGVzIjoxfQ",
    "X-Padiem-File-Time": "1761550000",
    "X-Padiem-File-Proof": "f" * 64,
}
CALLER_ID = "b54-p01-overlay-20260914-a1"
CREDENTIAL = "c" * 48


class _FixedScopeAuthority:
    async def scope_for_request(self, *, app_id: str, auth_session_id: str):
        return SCOPE


class _RecordingClientTransport:
    def __init__(self, body: str) -> None:
        self._body = body
        self.calls: list[dict] = []

    async def request(self, **kwargs) -> EngineTransportResponse:
        self.calls.append(kwargs)
        return EngineTransportResponse(
            status=200,
            body=self._body.encode("utf-8"),
            headers={"content-type": "application/json"},
        )


def _lane_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=TEXT,
            headers={
                "X-File-Lane-Next-Offset": str(len(TEXT)),
                "X-File-Lane-EOF": "true",
                "X-File-Lane-Total-Chars": str(len(TEXT)),
            },
        )

    return httpx.MockTransport(handler)


def _reference_request(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "session_id": SESSION_ID,
        "file_id": FILE_ID,
        "sha256": SHA256,
        "file_ticket": dict(TICKET),
    }
    body.update(overrides)
    return body


def _admitted_receipt() -> dict:
    store = ScopedDocumentByteStore(
        port=InMemoryDocumentByteStore(), clock=lambda: BASE_TIME
    )
    service = DocumentAdmissionEngineService(
        document_byte_store=store,
        scope_authority=_FixedScopeAuthority(),
        file_lane_text_port=FileLaneTextPort(
            origin="https://files.example.test", transport=_lane_transport()
        ),
    )
    payload = {"app_id": APP_ID, **_reference_request()}
    response = asyncio.run(service.admit_payload(payload))
    assert response.status_code == 200, response.body
    return response.body


def test_the_client_names_the_route_media_and_window_the_engine_uses() -> None:
    assert ENGINE_DOCUMENT_ADMISSION_PATH == DOCUMENT_ADMISSION_PATH
    assert DOCUMENT_LANE_MEDIA_TYPE == LANE_DOCUMENT_MEDIA_TYPE
    assert FILE_TICKET_HEADER_NAMES == frozenset(TICKET)
    assert DEFAULT_TEXT_WINDOW_CHARS == MAX_CONTEXT_PREVIEW_CHARS


@pytest.mark.parametrize(
    "header_name",
    ["X-Padiem-File-Ticket", "X-Padiem-File-Time", "X-Padiem-File-Proof", "X-Evil"],
)
def test_ticket_header_vocabulary_is_the_same_set(header_name: str) -> None:
    assert CLIENT_TICKET_HEADER_NAMES == FILE_TICKET_HEADER_NAMES
    assert (header_name in FILE_TICKET_HEADER_NAMES) == (
        header_name in CLIENT_TICKET_HEADER_NAMES
    ), header_name


@pytest.mark.parametrize(
    "candidate",
    [
        FILE_ID,
        "file_" + "AB12" * 8,          # lane mints lowercase hex only
        "file_" + "ab12" * 7,
        "file_" + "ab12" * 8 + "00",
        "file_" + "./x" * 8,
        "doc_" + "ab12" * 8,
        "",
    ],
)
def test_file_reference_grammar_decides_identically(candidate: str) -> None:
    client = PadiemAiEngineClient(
        transport=_RecordingClientTransport(json.dumps({"ok": True})),
        app_id=APP_ID,
        caller_id=CALLER_ID,
        credential=CREDENTIAL,
    )
    accepted_by_client = True
    try:
        asyncio.run(client.admit_document_reference(_reference_request(file_id=candidate)))
    except PadiemAiEngineClientError as exc:
        accepted_by_client = exc.code != "invalid_engine_request"
    assert accepted_by_client is bool(FILE_ID_PATTERN.fullmatch(candidate)), candidate


def test_the_real_engine_receipt_projects_through_the_client() -> None:
    receipt = _admitted_receipt()
    transport = _RecordingClientTransport(json.dumps(receipt, ensure_ascii=False))
    client = PadiemAiEngineClient(
        transport=transport,
        app_id=APP_ID,
        caller_id=CALLER_ID,
        credential=CREDENTIAL,
    )

    projection = asyncio.run(client.admit_document_reference(_reference_request()))

    assert set(projection) == set(receipt["document"])
    assert projection == dict(receipt["document"])
    assert projection["media_type"] == "text/plain"
    assert projection["total_chars"] == len(TEXT)
    assert projection["next_offset"] == len(TEXT)
    assert projection["window_eof"] is True
    sent = json.loads(transport.calls[0]["body"].decode("utf-8"))
    assert sent["app_id"] == APP_ID and sent["session_id"] == SESSION_ID
    assert sent["file_ticket"] == {name: TICKET[name] for name in sorted(TICKET)}
    assert TEXT not in transport.calls[0]["body"].decode("utf-8")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document.pop("total_chars"),
        lambda document: document.update({"window_eof": "true"}),
        lambda document: document.update({"next_offset": -1}),
        lambda document: document.update({"total_chars": 1}),
        lambda document: document.update({"media_type": "application/pdf"}),
        lambda document: document.update({"document_ref": "doc_short"}),
        lambda document: document.update({"expires_at": "2026-10-28T12:00:00"}),
    ],
    ids=[
        "missing_total", "eof_as_string", "negative_offset", "total_before_window_end",
        "wrong_media", "bad_reference", "naive_expiry",
    ],
)
def test_a_receipt_the_engine_never_answers_fails_closed_in_the_client(mutate) -> None:
    receipt = _admitted_receipt()
    mutate(receipt["document"])
    client = PadiemAiEngineClient(
        transport=_RecordingClientTransport(json.dumps(receipt, ensure_ascii=False)),
        app_id=APP_ID,
        caller_id=CALLER_ID,
        credential=CREDENTIAL,
    )

    with pytest.raises(PadiemAiEngineClientError) as raised:
        asyncio.run(client.admit_document_reference(_reference_request()))

    assert raised.value.code == "invalid_engine_response"
