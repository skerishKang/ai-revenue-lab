"""#5881 stage 4: Chat loads a COM2 reference onto the Engine, not the text.

  EXISTING_ENGINE_CALLER_REUSED   = YES
  EXISTING_TICKET_MINT_REUSED     = YES
  TICKET_FRESH_INSIDE_CALL        = YES
  NO_DOCUMENT_TEXT_TO_ENGINE      = YES
  NO_OS_ENVIRON_SECRET_PATH       = YES
  NO_PUBLIC_ROUTE                 = YES
  UNCONFIGURED_LANE_INLINE_SAME   = YES

The fake Engine binding records the exact internal request; the lane is the real
COM2 Starlette app so the forwarded claim is verified by its own authority.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from types import SimpleNamespace

import httpx
import pytest

from app.attachments import AttachmentValidationError
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_file_lane_admission_composition import (
    ClawFileLaneAdmissionError,
    ClawFileLaneDocumentAdmission,
    FILE_LANE_DIAGNOSTIC,
    build_claw_file_lane_document_admission,
    build_claw_file_lane_document_admission_with_diagnostic,
)
from app.claw_p01_composition import build_claw_engine_client_with_diagnostic
from app.b54_canonical_session import (
    B54CanonicalSessionProducer,
    B54ServerAuthenticatedOwner,
)
from app.config import Settings
from app.file_lane import FileLaneClient, TICKET_LIFETIME_SECONDS
from app.history import UserProfile
from app.main import create_app
from app.request_contract import _validate_payload_async
from app.worker_config import (
    P01_DIAG_ENGINE_SERVICE_MISSING,
    P01_ENGINE_SERVICE_BINDING_NAME,
)

from kagent.p01_adapter import P01_APP_ID
from padiem_ai_engine_client import (
    ENGINE_DOCUMENT_ADMISSION_PATH,
    ENGINE_INTERNAL_ORIGIN,
    EngineTransportResponse,
    FILE_TICKET_HEADER_NAMES,
    PadiemAiEngineClientError,
)
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    IdentityLinkState,
    ProductIdentityLink,
)
from padiem_control_plane.b54_identity_bridge import B54_PRODUCT_ID

SECRET = "offline-file-lane-contract-000000000000000000"
USER = "usr_" + "a" * 32
TENANT = "tenant_0123456789abcdef0123456789abcdef"
VALID_CALLER = "b54-p01-overlay-20260914-a1"
VALID_CREDENTIAL = "c" * 48
# Time anchors: BRIDGED_AT and the document body's expires_at (10-28) are a
# fixed PAIR that is only ever checked against each other (the bridge clock),
# never against the wall clock — that is why this suite stays deterministic.
# If a real-clock check ever enters this path, either pass now= into it or pin
# the module clock (see docs/operations/TEST_TIME_ANCHOR_AUDIT_20261029.md §4).
BRIDGED_AT = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
DOCUMENT_BYTES = b"COM2 document context"
MARKER_TEXT = DOCUMENT_BYTES.decode()
DOC_REF = "doc_" + "Ab3_-9" * 4
TICKET_SHAPED = {
    "X-Padiem-File-Ticket": "eyJ1c2VyX2lkIjoidXNyX2xhbmUifQ",
    "X-Padiem-File-Time": "1761550000",
    "X-Padiem-File-Proof": "f" * 64,
}


def _lane_app(tmp_path, monkeypatch):
    # Cross-app fixture imports source only: Chat has no COM2 package dependency.
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "padiem-file-lane/src")
    )
    from padiem_file_lane.app import create_app as create_file_app

    return create_file_app(root=tmp_path, secret=SECRET)


def _document_body(**overrides: object) -> str:
    document = {
        "document_ref": DOC_REF,
        "media_type": "text/plain",
        "byte_size": len(DOCUMENT_BYTES),
        "expires_at": "2026-10-28T12:00:00+00:00",
        "total_chars": 21,
        "next_offset": 21,
        "window_eof": True,
    }
    document.update(overrides)
    return json.dumps({"ok": True, "document": document}, ensure_ascii=False)


class _FakeWorkerRequest:
    def __init__(self, url: str, **options: object) -> None:
        self.url = url
        self.options = options
        self.js_object = self


class _FakeEngineResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self.status = status
        self.headers = {"content-type": "application/json"}
        self._body = body

    async def text(self) -> str:
        return self._body


class _FakeEngineServiceBinding:
    def __init__(self, response_body: str | None = None) -> None:
        self.calls: list[_FakeWorkerRequest] = []
        self._response_body = response_body or _document_body()

    async def fetch(self, request: _FakeWorkerRequest) -> _FakeEngineResponse:
        self.calls.append(request)
        return _FakeEngineResponse(self._response_body)


class _FakeB54Authority:
    def resolve_or_create_product_link(self, **kwargs: object) -> ProductIdentityLink:
        return ProductIdentityLink(
            product_id=kwargs["product_id"],
            product_user_id=kwargs["product_user_id"],
            canonical_subject_id=f"subject:{kwargs['product_id']}:{kwargs['product_user_id']}",
            state=IdentityLinkState.ACTIVE,
        )

    def resolve_active_memberships(self, *, canonical_subject_id: str):
        return (TENANT,)

    def establish_auth_session(self, **kwargs: object) -> AuthSessionSnapshot:
        subject = kwargs["subject"]
        return AuthSessionSnapshot(
            session_id=f"sess_{subject.subject_id}",
            product_id=kwargs["product_id"],
            subject=subject,
            issued_at=kwargs["authenticated_at"],
            expires_at=kwargs["not_after"],
            state=AuthSessionState.ACTIVE,
            revision=1,
            tenant_id=TENANT,
        )


async def _bridged_session():
    producer = B54CanonicalSessionProducer(
        authority=_FakeB54Authority(),
        session_max_age_seconds=3600,
        clock=lambda: BRIDGED_AT,
    )
    return await producer.establish(
        B54ServerAuthenticatedOwner(
            product_user_id="usr_lane", provider_subject="lane.owner"
        )
    )


def _env(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        P01_ENGINE_SERVICE_BINDING_NAME: SimpleNamespace(name="engine-service"),
        "P01_ENGINE_CALLER_ID": VALID_CALLER,
        "P01_ENGINE_CREDENTIAL": VALID_CREDENTIAL,
    }
    values.update(overrides)
    return values


def _settings(**kwargs: object) -> Settings:
    return Settings.from_values(
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="offline.apps.example.test",
        google_client_secret="offline",
        session_secret="offline-chat-session-secret-00000000000000000",
        **kwargs,
    )


def _claims(ticket: dict[str, str]) -> dict[str, object]:
    """Decode only to prove the claim: the Engine itself never reads these values."""

    raw = ticket["X-Padiem-File-Ticket"]
    padded = raw + "=" * (-len(raw) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))


async def _uploaded_reference(file_app) -> dict[str, object]:
    lane = FileLaneClient("https://files.example.test", SECRET)
    ticket = lane.upload_ticket(USER, len(DOCUMENT_BYTES))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=file_app), base_url="https://files.example.test"
    ) as files:
        uploaded = await files.post(
            "/files?filename=notes.txt", headers=ticket["headers"], content=DOCUMENT_BYTES
        )
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()


# --- 1. the reference is loaded onto the Engine ------------------------------------


@pytest.mark.asyncio
async def test_reference_loads_onto_engine_with_a_fresh_lane_claim(tmp_path, monkeypatch):
    file_app = _lane_app(tmp_path, monkeypatch)
    meta = await _uploaded_reference(file_app)
    assert meta["kind"] == "txt" and meta["size_bytes"] == len(DOCUMENT_BYTES)

    binding = _FakeEngineServiceBinding()
    admission = build_claw_file_lane_document_admission(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: binding}),
        request_factory=_FakeWorkerRequest,
        file_lane=FileLaneClient(
            "https://files.example.test", SECRET, transport=httpx.ASGITransport(app=file_app)
        ),
    )
    session = await _bridged_session()

    receipt = await admission.admit(
        session,
        user_id=USER,
        file_id=meta["file_id"],
        sha256=meta["sha256"],
        filename="quarterly notes.pdf",
    )

    assert receipt == {
        "document_ref": DOC_REF,
        "media_type": "text/plain",
        "byte_size": len(DOCUMENT_BYTES),
        "expires_at": "2026-10-28T12:00:00+00:00",
        "total_chars": 21,
        "next_offset": 21,
        "window_eof": True,
    }
    assert len(binding.calls) == 1
    request = binding.calls[0]
    assert request.url == f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_DOCUMENT_ADMISSION_PATH}"
    assert request.options["method"] == "POST"
    headers = request.options["headers"]
    assert headers["X-Padiem-Engine-Caller"] == VALID_CALLER
    assert headers["X-Padiem-Engine-Credential"] == VALID_CREDENTIAL

    payload = json.loads(str(request.options["body"]))
    assert set(payload) == {
        "app_id", "session_id", "file_id", "sha256", "file_ticket", "filename",
    }
    # Identity is server-resolved; a browser can name neither of them.
    assert payload["app_id"] == P01_APP_ID
    # The Engine resolves the session only when its product matches this app_id,
    # which is why the seam is composed on the existing B54 pairing and nowhere
    # with a Chat-selected identity.
    assert P01_APP_ID == B54_PRODUCT_ID
    assert payload["session_id"] == session.auth_session.session_id
    assert session.auth_session.product_id == B54_PRODUCT_ID
    assert payload["file_id"] == meta["file_id"] and payload["sha256"] == meta["sha256"]
    # The document body never leaves COM2 toward this process or the Engine.
    assert MARKER_TEXT not in str(request.options["body"])

    ticket = payload["file_ticket"]
    assert set(ticket) == FILE_TICKET_HEADER_NAMES
    claims = _claims(ticket)
    assert claims["user_id"] == USER and claims["max_bytes"] == 1
    now = int(time.time())
    assert now < claims["expires"] <= now + TICKET_LIFETIME_SECONDS
    assert int(ticket["X-Padiem-File-Time"]) <= claims["expires"]

    # The real COM2 authority accepts the forwarded claim for the same owner.
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "padiem-file-lane/src")
    )
    from padiem_file_lane.tickets import verify_ticket

    verified = verify_ticket(
        {name.lower(): value for name, value in ticket.items()}, SECRET
    )
    assert (verified.user_id, verified.max_bytes) == (USER, 1)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=file_app), base_url="https://files.example.test"
    ) as files:
        read = await files.get(
            f"/files/{meta['file_id']}/text", params={"offset": 0, "max_chars": 40_000},
            headers=ticket,
        )
    assert read.status_code == 200 and read.text == MARKER_TEXT
    assert read.headers["x-file-lane-total-chars"] == str(len(MARKER_TEXT))

    # Every admission mints its own claim inside its own lifetime.
    await admission.admit(
        session, user_id=USER, file_id=meta["file_id"], sha256=meta["sha256"]
    )
    second = json.loads(str(binding.calls[1].options["body"]))["file_ticket"]
    assert set(second) == FILE_TICKET_HEADER_NAMES
    assert _claims(second)["user_id"] == USER
    assert len(binding.calls) == 2


# --- 2. no lane configured keeps the inline path identical --------------------------


@pytest.mark.asyncio
async def test_unconfigured_lane_builds_no_seam_and_keeps_inline_path_identical(tmp_path, monkeypatch):
    file_app = _lane_app(tmp_path, monkeypatch)
    configured = FileLaneClient(
        "https://files.example.test", SECRET, transport=httpx.ASGITransport(app=file_app)
    )
    unconfigured = FileLaneClient(None, None)
    assert unconfigured.ready is False and configured.ready is True

    seam = build_claw_file_lane_document_admission(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: _FakeEngineServiceBinding()}),
        request_factory=_FakeWorkerRequest,
        file_lane=unconfigured,
    )
    assert seam is None
    missing, diagnostic = build_claw_file_lane_document_admission_with_diagnostic(
        _env(), request_factory=_FakeWorkerRequest, file_lane=None
    )
    assert missing is None and diagnostic == FILE_LANE_DIAGNOSTIC
    # A configured lane with no Engine binding still fails closed on the
    # existing P01 diagnostic instead of inventing a second transport.
    no_engine, engine_diagnostic = build_claw_file_lane_document_admission_with_diagnostic(
        {}, request_factory=_FakeWorkerRequest, file_lane=configured
    )
    assert no_engine is None and engine_diagnostic == P01_DIAG_ENGINE_SERVICE_MISSING

    # With both halves present the seam reuses the one existing Engine client:
    # same Worker binding, same app identity, so no second Engine protocol.
    binding = _FakeEngineServiceBinding()
    admitted = build_claw_file_lane_document_admission(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: binding}),
        request_factory=_FakeWorkerRequest,
        file_lane=configured,
    )
    assert isinstance(admitted, ClawFileLaneDocumentAdmission)
    assert admitted._client.app_id == P01_APP_ID
    assert admitted._client.caller_id == VALID_CALLER
    assert admitted._client._transport._binding is binding

    # The unconfigured deployment behaves exactly as the inline path always did.
    settings = _settings()
    app = create_app(settings, history_store=History())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
        cookies={SESSION_COOKIE: create_session_token(settings, USER)},
    ) as chat:
        assert (await chat.get("/api/files/capabilities")).json()["ready"] is False
        inline = await chat.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "읽어줘"}],
                "attachments": [
                    {"type": "document", "name": "notes.txt", "media_type": "text/plain",
                     "text": "inline stays"}
                ],
            },
            headers={"Origin": "https://chat.example.test"},
        )
        assert inline.status_code == 200
        assert inline.json()["attachments"][0]["text_chars"] == len("inline stays")
        reference = await chat.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "읽어줘"}],
                "attachments": [{"type": "file", "file_id": "file_" + "ab12" * 8}],
            },
            headers={"Origin": "https://chat.example.test"},
        )
        assert reference.status_code == 422

    parsed = await _validate_payload_async(
        {
            "messages": [{"role": "user", "content": "읽어줘"}],
            "attachments": [
                {"type": "document", "name": "notes.txt", "media_type": "text/plain",
                 "text": "inline stays"}
            ],
        }
    )
    assert parsed[3][0].text == "inline stays" and parsed[3][0].file_id is None
    with pytest.raises(AttachmentValidationError):
        await unconfigured.resolve(USER, {"type": "file", "file_id": "file_" + "ab12" * 8})


class History:
    async def get_user(self, user):
        return (
            UserProfile(user, "offline@example.test", "Offline", "")
            if user == USER
            else None
        )

    async def append_exchange(self, *args, **kwargs):
        return "chat_" + "c" * 32

    async def list_conversations(self, *args, **kwargs):
        return []


# --- fail-closed boundaries --------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_refusal_and_bad_shape_never_reach_the_browser_verbatim(
    tmp_path, monkeypatch
):
    file_app = _lane_app(tmp_path, monkeypatch)
    meta = await _uploaded_reference(file_app)
    lane = FileLaneClient(
        "https://files.example.test", SECRET, transport=httpx.ASGITransport(app=file_app)
    )
    session = await _bridged_session()

    refused = _FakeEngineServiceBinding(
        json.dumps({"ok": False, "error": {"code": "file_lane_ticket_rejected"}})
    )
    admission = build_claw_file_lane_document_admission(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: refused}),
        request_factory=_FakeWorkerRequest,
        file_lane=lane,
    )
    with pytest.raises(ClawFileLaneAdmissionError) as raised:
        await admission.admit(
            session, user_id=USER, file_id=meta["file_id"], sha256=meta["sha256"]
        )
    assert raised.value.code == "file_lane_ticket_rejected"
    assert MARKER_TEXT not in str(raised.value)

    forged = build_claw_file_lane_document_admission(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: _FakeEngineServiceBinding()}),
        request_factory=_FakeWorkerRequest,
        file_lane=lane,
    )
    for bad in (
        {"file_id": "file_ZZ12" + "ab12" * 7, "sha256": meta["sha256"]},
        {"file_id": meta["file_id"], "sha256": "0" * 63},
    ):
        with pytest.raises(ClawFileLaneAdmissionError) as refused_call:
            await forged.admit(session, user_id=USER, **bad)
        assert refused_call.value.code == "invalid_engine_request"
    # A payload-named session is never accepted by the seam.
    with pytest.raises(ClawFileLaneAdmissionError) as stranger:
        await forged.admit(
            {"auth_session": {"session_id": "sess_browser_chosen"}},
            user_id=USER,
            file_id=meta["file_id"],
            sha256=meta["sha256"],
        )
    assert stranger.value.code == "invalid_admission_session"


def test_seam_module_never_reads_os_environ_or_mints_identity():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "claw_file_lane_admission_composition.py").read_text(
        encoding="utf-8"
    )
    assert "import os" not in source
    assert "os.environ" not in source
    assert "import secrets" not in source
    assert "secrets." not in source
    assert "uuid" not in source
    # The claim is minted at the one existing #5893 point, never here.
    assert "ticket_headers" not in source
    assert "hmac" not in source


def test_seam_is_not_wired_to_any_public_route():
    root = Path(__file__).resolve().parents[1]
    module_name = "claw_file_lane_admission_composition"
    for relative in ("worker.py", "app/app_factory.py", "app/claw_routes.py",
                     "app/claw_general_routes.py", "app/chat_routes.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert module_name not in source, relative
    seam = (root / "app" / f"{module_name}.py").read_text(encoding="utf-8")
    assert "/api/" not in seam
    assert "add_route" not in seam
    assert "from starlette" not in seam


def test_client_grammar_refuses_a_bad_reference_before_any_transport():
    seen: list[dict] = []

    class Recording:
        async def request(self, **kwargs):
            seen.append(kwargs)
            return EngineTransportResponse(status=200, body=_document_body().encode("utf-8"))

    client = build_claw_engine_client_with_diagnostic(
        _env(**{P01_ENGINE_SERVICE_BINDING_NAME: _FakeEngineServiceBinding()}),
        request_factory=_FakeWorkerRequest,
    )[0]
    client._transport = Recording()
    base = {
        "session_id": "sess_subject:b54-padiem-claw:usr_lane",
        "file_id": "file_" + "ab12" * 8,
        "sha256": "0" * 64,
        "file_ticket": dict(TICKET_SHAPED),
    }

    for broken in (
        {**base, "file_id": "file_ZZ12" + "ab12" * 7},
        {**base, "sha256": "0" * 63},
        {**base, "file_ticket": {k: v for k, v in TICKET_SHAPED.items() if k != "X-Padiem-File-Proof"}},
        {**base, "file_ticket": {**TICKET_SHAPED, "X-Padiem-File-Proof": "inject\r\nX-Evil: 1"}},
        {**base, "document_base64": "AAAA"},
    ):
        with pytest.raises(PadiemAiEngineClientError) as refused:
            asyncio.run(client.admit_document_reference(broken))
        assert refused.value.code == "invalid_engine_request"
    assert seen == []

    admitted = asyncio.run(client.admit_document_reference(base))
    assert len(seen) == 1
    assert admitted["document_ref"] == DOC_REF
    assert json.loads(seen[0]["body"].decode("utf-8"))["file_ticket"] == dict(TICKET_SHAPED)
