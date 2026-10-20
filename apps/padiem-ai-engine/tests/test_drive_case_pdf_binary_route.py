"""B67 case-folder PDF internal byte route (#4379).

Proves the Engine -> Chat seam ships one raw octet-stream frame instead of a
whole-file Base64 string, that the frame carries the same closed projection and
version evidence the JSON RPC carried, and that every denial still happens
before a single byte is read.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import importlib
import json
import pathlib
import sys
import types
from typing import Any

import pytest

APP_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from padiem_ai_core.drive_capability import DriveCapability  # noqa: E402
from padiem_ai_core.drive_case_folder_scope import (  # noqa: E402
    DriveCaseResource,
    GOOGLE_FOLDER_MIME,
)

from app.connector_bindings import (  # noqa: E402
    DRIVE_AGENT_ID,
    DRIVE_REFERENCE_APP_ID,
    DriveGrant,
)
from app.drive_case_folder_binding import (  # noqa: E402
    DriveCaseFolderBindingAuthority,
    InMemoryDriveCaseFolderBindingStore,
)
from app.drive_case_pdf_binary import (  # noqa: E402
    B67_CASE_PDF_BINARY_CONTRACT_VERSION,
    B67_CASE_PDF_BINARY_CONTENT_TYPE,
    B67_CASE_PDF_BINARY_PATH,
    DriveCasePdfBinaryResponse,
    MAX_BINARY_PDF_HEADER_BYTES,
    decode_binary_pdf_frame,
    drive_case_pdf_binary_read,
    drive_case_pdf_binary_snapshot,
    encode_binary_pdf_frame,
)
from app.drive_case_pdf_service import (  # noqa: E402
    MAX_B67_CASE_PDF_BYTES,
    DriveCasePdfService,
)

WORKSPACE_REF = "ws_legal_001"
PROJECT_ID = "proj_" + "b" * 32
BINDING_REF = "bind:legal_drive"
FOLDER_ID = "folder_case_001"
FILE_ID = "pdf_case_001"
PDF_BYTES = b"%PDF-1.7\ncase evidence\n%%EOF"
CALLER_ID = "b67-binary-route-caller"
CALLER_SECRET = "b67-binary-route-secret-0123456789abcdef-0123456789abcdef"

FOLDER_METADATA = {
    "id": FOLDER_ID,
    "name": "Case Folder",
    "mimeType": GOOGLE_FOLDER_MIME,
    "parents": ["root"],
    "trashed": False,
    "version": 1,
}

PDF_METADATA = {
    "id": FILE_ID,
    "name": "brief.pdf",
    "mimeType": "application/pdf",
    "parents": [FOLDER_ID],
    "trashed": False,
    "version": 7,
    "modifiedTime": "2026-10-01T00:00:00Z",
    "resourceKey": "resource_key_must_not_leave_engine",
    "size": len(PDF_BYTES),
}

_REQUEST = {
    "app_id": DRIVE_REFERENCE_APP_ID,
    "workspace_ref": WORKSPACE_REF,
    "project_id": PROJECT_ID,
    "file_id": FILE_ID,
}


def run(coro):
    return asyncio.run(coro)


def request_body(**overrides: Any) -> bytes:
    payload = dict(_REQUEST)
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class FakeGrantProvider:
    def __init__(self, value: DriveGrant) -> None:
        self.value = value
        self.calls: list[str] = []

    async def current_drive_grant(self, *, workspace_ref: str):
        self.calls.append(workspace_ref)
        return self.value


class FakeDrivePort:
    def __init__(self, *, metadata: dict | None = None, content: bytes = PDF_BYTES) -> None:
        self.metadata = dict(metadata if metadata is not None else PDF_METADATA)
        self.content = content
        self.calls: list[tuple[str, dict]] = []

    def get_json(self, **kwargs):
        self.calls.append(("json", dict(kwargs)))
        return dict(self.metadata)

    def get_bytes(self, **kwargs):
        self.calls.append(("bytes", dict(kwargs)))
        return self.content


async def make_service(
    *, port: FakeDrivePort | None = None
) -> tuple[DriveCasePdfService, FakeDrivePort]:
    active_grant = DriveGrant(
        app_id=DRIVE_REFERENCE_APP_ID,
        canonical_agent_id=DRIVE_AGENT_ID,
        binding_ref=BINDING_REF,
        actor_ref="actor_legal",
        granted_capabilities=(DriveCapability.READ,),
    )
    selected = DriveCaseResource.from_provider(
        binding_ref=active_grant.binding_ref, metadata=dict(FOLDER_METADATA)
    )
    authority = DriveCaseFolderBindingAuthority(
        store=InMemoryDriveCaseFolderBindingStore()
    )
    await authority.bind_selected_folder(
        workspace_ref=WORKSPACE_REF,
        project_id=PROJECT_ID,
        drive_grant=active_grant,
        selected_resource=selected,
    )
    drive_port = port or FakeDrivePort()
    return (
        DriveCasePdfService(
            grant_provider=FakeGrantProvider(active_grant),
            drive_port=drive_port,
            binding_authority=authority,
        ),
        drive_port,
    )


# --- frame codec ------------------------------------------------------------


def test_frame_is_byte_exact_and_carries_no_base64() -> None:
    header = {
        "file": {"file_id": FILE_ID},
        "byte_size": len(PDF_BYTES),
        "sha256": hashlib.sha256(PDF_BYTES).hexdigest(),
        "version_evidence": {},
        "authorization": {},
        "contract_version": B67_CASE_PDF_BINARY_CONTRACT_VERSION,
    }
    frame = encode_binary_pdf_frame(header, PDF_BYTES)

    assert frame[:4] == len(
        json.dumps(header, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).to_bytes(4, "big")
    assert frame.endswith(PDF_BYTES)
    decoded_header, payload = decode_binary_pdf_frame(frame)
    assert payload == PDF_BYTES
    assert decoded_header["byte_size"] == len(PDF_BYTES)

    # The old contract could not carry a byte whose base64 form was mistaken for
    # text; the frame keeps the payload verbatim, including a JPEG-style body.
    binary = b"%PDF-1.7\n\x00\x01\x02\xff\xfe\xfddeterministic\n%%EOF"
    decoded_header2, payload2 = decode_binary_pdf_frame(
        encode_binary_pdf_frame(header, binary)
    )
    assert payload2 == binary


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x00\x00\x00\x00" + PDF_BYTES,
        b"\x00\x00\x00\x02" + b"{}",
        b"\x00\x01\x00\x00" + b"{}" + PDF_BYTES,
        (2).to_bytes(4, "big") + b"[]" + PDF_BYTES,
        (2).to_bytes(4, "big") + b"{}" + PDF_BYTES,
        len(b'{"a": "\xff\xfe"}').to_bytes(4, "big") + b'{"a": "\xff\xfe"}' + PDF_BYTES,
    ],
)
def test_malformed_frames_are_refused(raw: bytes) -> None:
    with pytest.raises(ValueError):
        decode_binary_pdf_frame(raw)


def test_encoder_refuses_empty_payload_and_oversize_header() -> None:
    with pytest.raises(ValueError):
        encode_binary_pdf_frame({"file": {}}, b"")
    with pytest.raises(ValueError):
        encode_binary_pdf_frame({"x": "y" * MAX_BINARY_PDF_HEADER_BYTES}, PDF_BYTES)


# --- dispatcher -------------------------------------------------------------


def test_binary_read_returns_the_exact_pdf_and_closed_projection() -> None:
    service, port = run(make_service())
    result = run(drive_case_pdf_binary_read(service, body=request_body()))

    assert isinstance(result, DriveCasePdfBinaryResponse)
    assert result.status_code == 200
    assert result.content_type == B67_CASE_PDF_BINARY_CONTENT_TYPE
    assert b"content_base64" not in result.body

    header, payload = decode_binary_pdf_frame(result.body)
    assert payload == PDF_BYTES
    assert header["byte_size"] == len(PDF_BYTES)
    assert header["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert header["contract_version"] == B67_CASE_PDF_BINARY_CONTRACT_VERSION
    assert header["file"]["file_id"] == FILE_ID
    assert header["file"]["mime_type"] == "application/pdf"
    assert header["file"]["intake_state"] == "browser_pdf_ready"
    # Drive reports revision as an integer; the frame carries it unchanged.
    assert header["version_evidence"]["version"] == 7
    assert "resource_key" not in header["version_evidence"]
    assert "resource_key_must_not_leave_engine" not in json.dumps(header)
    assert header["authorization"] == {"direct_parent_proof": True, "source_type": "drive"}
    assert [kind for kind, _ in port.calls] == ["json", "bytes"]
    assert port.calls[1][1]["max_response_bytes"] == MAX_B67_CASE_PDF_BYTES


def test_binary_read_matches_the_legacy_json_rpc_projection() -> None:
    service, _ = run(make_service())
    legacy = run(service.read(
        workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, file_id=FILE_ID
    ))
    result = run(drive_case_pdf_binary_read(service, body=request_body()))
    header, payload = decode_binary_pdf_frame(result.body)
    assert payload == PDF_BYTES
    assert header["file"] == legacy["file"]
    assert header["version_evidence"] == legacy["version_evidence"]
    assert header["authorization"] == legacy["authorization"]
    assert header["byte_size"] == legacy["byte_size"]
    # The frame is strictly smaller than the Base64 body it replaces.
    assert len(result.body) == 4 + len(
        json.dumps(
            {
                "file": legacy["file"],
                "byte_size": legacy["byte_size"],
                "sha256": hashlib.sha256(PDF_BYTES).hexdigest(),
                "version_evidence": legacy["version_evidence"],
                "authorization": legacy["authorization"],
                "contract_version": B67_CASE_PDF_BINARY_CONTRACT_VERSION,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ) + len(PDF_BYTES)


def test_missing_service_fails_closed_as_unavailable() -> None:
    result = run(drive_case_pdf_binary_read(None, body=request_body()))
    assert result.status_code == 503
    assert result.content_type == "application/json; charset=utf-8"
    body = json.loads(result.body.decode("utf-8"))
    assert body["ok"] is False
    assert body["error"]["code"] == "drive_case_pdf_unavailable"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({**_REQUEST, "extra": "x"}, 400),
        ({}, 400),
        ({k: v for k, v in _REQUEST.items() if k != "file_id"}, 400),
        ({**_REQUEST, "file_id": None}, 400),
        ({**_REQUEST, "workspace_ref": "  "}, 400),
        ({**_REQUEST, "project_id": "p" * 201}, 400),
        ({**_REQUEST, "app_id": "b54-padiem-claw-calendar"}, 403),
    ],
)
def test_request_grammar_is_closed(payload: dict, expected: int) -> None:
    service, port = run(make_service())
    result = run(
        drive_case_pdf_binary_read(
            service, body=json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
    )
    assert result.status_code == expected
    assert result.content_type == "application/json; charset=utf-8"
    assert [kind for kind, _ in port.calls] == []


def test_unparsable_body_is_a_bounded_invalid_request() -> None:
    service, port = run(make_service())
    for body in (b"not json", b"[]", b"", b'{"app_id": 1}'):
        result = run(drive_case_pdf_binary_read(service, body=body))
        assert result.status_code == 400
        assert json.loads(result.body.decode("utf-8"))["error"]["code"] == "invalid_request"
    assert port.calls == []


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({**PDF_METADATA, "parents": ["other_folder"]}, "drive_parent_contract_failed"),
        ({**PDF_METADATA, "mimeType": "text/plain"}, "not_pdf"),
        ({**PDF_METADATA, "trashed": True}, "drive_case_folder_scope_denied"),
        ({**PDF_METADATA, "size": MAX_B67_CASE_PDF_BYTES + 1}, "execution_fallback_required"),
        ({**PDF_METADATA, "size": 0}, "pdf_size_unverifiable"),
    ],
)
def test_denials_happen_before_any_pdf_bytes(metadata: dict, expected: str) -> None:
    port = FakeDrivePort(metadata=metadata)
    service, _ = run(make_service(port=port))
    result = run(drive_case_pdf_binary_read(service, body=request_body()))
    assert result.content_type == "application/json; charset=utf-8"
    assert result.status_code in (400, 403, 409, 413, 415, 422, 502)
    assert json.loads(result.body.decode("utf-8"))["error"]["code"] == expected
    assert [kind for kind, _ in port.calls] == ["json"]


def test_non_pdf_payload_is_refused_before_the_frame() -> None:
    port = FakeDrivePort(content=b"not a pdf at all")
    service, _ = run(make_service(port=port))
    result = run(drive_case_pdf_binary_read(service, body=request_body()))
    assert json.loads(result.body.decode("utf-8"))["error"]["code"] == "pdf_integrity_mismatch"
    assert result.status_code == 502


def test_snapshot_declares_the_replacement_contract() -> None:
    snapshot = drive_case_pdf_binary_snapshot()
    assert snapshot["content_base64_in_response"] is False
    assert snapshot["canonical_selected_folder_authority_reused"] is True
    assert snapshot["canonical_drive_app_id_reused"] is True
    assert snapshot["browser_reachable"] is False
    assert snapshot["production_mutation"] is False
    assert snapshot["path"] == B67_CASE_PDF_BINARY_PATH
    assert snapshot["content_type"] == B67_CASE_PDF_BINARY_CONTENT_TYPE


# --- worker route boundary --------------------------------------------------


class _FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, ctx: Any = None, env: Any = None) -> None:
        self.ctx = ctx
        self.env = env


def _workers_stub() -> types.ModuleType:
    module = types.ModuleType("workers")
    module.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.Response = _FakeResponse  # type: ignore[attr-defined]
    module.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    return module


@pytest.fixture(scope="module")
def identity_modules():
    saved = {name: sys.modules.get(name) for name in ("workers", "worker", "worker_identity")}
    sys.modules["workers"] = _workers_stub()
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        identity = importlib.import_module("worker_identity")
        legacy = importlib.import_module("worker")
        yield legacy, identity
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _Env:
    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


class _Request:
    def __init__(self, path: str, *, method: str = "POST", body: bytes = b"{}") -> None:
        self.url = f"https://padiem-ai-engine.internal{path}"
        self.method = method
        self.headers = {
            "content-type": "application/json",
            "x-padiem-engine-caller": CALLER_ID,
            "x-padiem-engine-credential": CALLER_SECRET,
        }
        self._text = body.decode("utf-8")

    async def text(self) -> str:
        return self._text


def _identity_env(**extra: Any) -> _Env:
    return _Env(
        PADIEM_ENGINE_CALLER_ID=CALLER_ID,
        PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
        PADIEM_ENGINE_ALLOWED_APPS=DRIVE_REFERENCE_APP_ID,
        **extra,
    )


def _fetch(identity: Any, env: Any, request: Any) -> Any:
    return run(identity.Default(ctx=None, env=env).fetch(request))


def _json_body(response: Any) -> dict:
    """Both error shapes: the shared JSON helper sends text, this route sends bytes."""

    raw = response.body
    if isinstance(raw, (bytes, bytearray, memoryview)):
        raw = bytes(raw).decode("utf-8")
    return json.loads(str(raw))


def _patch_service(monkeypatch: pytest.MonkeyPatch, identity: Any, service: Any) -> None:
    monkeypatch.setattr(
        identity, "_drive_case_pdf_service_for_env", lambda _env: service, raising=False
    )


def test_route_is_admitted_and_serves_the_frame(identity_modules, monkeypatch) -> None:
    legacy, identity = identity_modules
    service, _ = run(make_service())
    _patch_service(monkeypatch, identity, service)

    response = _fetch(
        identity, _identity_env(), _Request(B67_CASE_PDF_BINARY_PATH, body=request_body())
    )

    assert response.status == 200
    assert response.headers["Content-Type"] == B67_CASE_PDF_BINARY_CONTENT_TYPE
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    header, payload = decode_binary_pdf_frame(bytes(response.body))
    assert payload == PDF_BYTES
    assert header["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()


def test_route_rejects_an_unauthenticated_caller(identity_modules, monkeypatch) -> None:
    legacy, identity = identity_modules
    service, port = run(make_service())
    _patch_service(monkeypatch, identity, service)

    request = _Request(B67_CASE_PDF_BINARY_PATH, body=request_body())
    request.headers = {"content-type": "application/json"}
    response = _fetch(identity, _identity_env(), request)

    assert response.status == 401
    assert _json_body(response)["error"]["code"] == "service_authentication_failed"
    assert port.calls == []


def test_route_without_composed_service_fails_closed(identity_modules, monkeypatch) -> None:
    _legacy, identity = identity_modules
    _patch_service(monkeypatch, identity, None)
    response = _fetch(
        identity, _identity_env(), _Request(B67_CASE_PDF_BINARY_PATH, body=request_body())
    )
    assert response.status == 503
    assert _json_body(response)["error"]["code"] == "drive_case_pdf_unavailable"


def test_composition_failure_never_leaks_detail(identity_modules, monkeypatch) -> None:
    _legacy, identity = identity_modules

    def explode(_env):
        raise RuntimeError("raw infrastructure detail")

    monkeypatch.setattr(
        identity, "_drive_case_pdf_service_for_env", explode, raising=False
    )
    response = _fetch(
        identity, _identity_env(), _Request(B67_CASE_PDF_BINARY_PATH, body=request_body())
    )
    assert response.status == 503
    rendered = str(response.body)
    assert "raw infrastructure detail" not in rendered
    assert _json_body(response)["error"]["code"] == "drive_case_pdf_unavailable"


def test_binary_path_is_not_the_rpc_route_and_stays_internal(identity_modules) -> None:
    legacy, identity = identity_modules
    for module in (legacy, identity):
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        assert "/api/b67" not in source
        assert "/internal/v1/b67" not in source
    legacy_source = pathlib.Path(legacy.__file__).read_text(encoding="utf-8")
    assert "B67_CASE_PDF_BINARY_PATH" in legacy_source
    assert "PADIEM_AI_ENGINE" not in legacy_source


def test_unknown_internal_path_still_returns_not_found(identity_modules) -> None:
    _legacy, identity = identity_modules
    response = _fetch(
        identity,
        _identity_env(),
        _Request("/internal/v1/projects/drive-case-pdf/write", body=request_body()),
    )
    assert response.status == 404
    assert json.loads(str(response.body))["error"]["code"] == "not_found"


def test_rpc_operations_are_unchanged_by_the_binary_route(identity_modules) -> None:
    legacy, _identity = identity_modules
    for operation in (
        "b67_case_pdf_candidates",
        "b67_case_pdf_read",
        "b67_case_pdf_review_extraction",
    ):
        assert callable(getattr(legacy.Default, operation, None)), operation


def test_binary_response_is_a_frozen_completed_value() -> None:
    result = DriveCasePdfBinaryResponse(status_code=200, body=PDF_BYTES, content_type="x/y")
    assert dataclasses.is_dataclass(result)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.status_code = 500  # type: ignore[misc]
