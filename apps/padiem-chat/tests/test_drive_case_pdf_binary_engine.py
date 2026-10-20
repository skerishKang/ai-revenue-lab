"""Chat -> Engine Drive PDF byte transport (#4379).

The Base64 round trip on this seam is replaced by one internal octet-stream
frame. These tests drive the client through the real bounded stream reader and
check the three outcomes that matter: bytes arrive unchanged, the legacy RPC is
used only when the Engine route is genuinely absent, and every other failure is
reported instead of hidden by a silent retry.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import pathlib

import pytest

from app.drive_case_folder_engine import (
    MAX_BINARY_PDF_FRAME_BYTES,
    PDF_BINARY_CONTRACT_VERSION,
    PDF_BINARY_READ_APP_ID,
    PDF_BINARY_READ_PATH,
    PDF_CANDIDATES_OPERATION,
    PDF_READ_OPERATION,
    CloudflareDriveCaseFolderEngineClient,
    DriveCaseFolderEngineError,
    drive_case_folder_engine_seam_snapshot,
)

WORKSPACE_REF = "ws_alpha_001"
PROJECT_ID = "proj_" + "a" * 32
FILE_ID = "file_pdf_001"
CALLER_ID = "b54-p01-overlay-20260914-a1"
CREDENTIAL = "p01-credential-0123456789abcdef-0123456789abcdef"

# Bytes a Base64 body has to inflate by a third for no reason, including a NUL
# and a high byte that a text-shaped transport would have mangled.
PDF_BYTES = b"%PDF-1.7\n\x00\x01\xff\xfeh\xc3\xa9llo case evidence\n%%%%+EOF\n"

FILE_PROJECTION = {
    "file_id": FILE_ID,
    "name": "brief.pdf",
    "mime_type": "application/pdf",
    "size_bytes": len(PDF_BYTES),
    "modified_time": "2026-10-01T00:00:00Z",
    "space_kind": "my_drive",
    "intake_state": "browser_pdf_ready",
}

# Drive reports revision as an integer; this is the producer's real shape.
VERSION_EVIDENCE = {
    "version": 7,
    "modified_time": "2026-10-01T00:00:00Z",
    "md5_checksum": "d41d8cd98f00b204e9800998ecf8427e",
    "sha256_checksum": "a" * 64,
    "head_revision_id": None,
}

AUTHORIZATION = {"direct_parent_proof": True, "source_type": "drive"}

OCTET_STREAM = "application/octet-stream"
JSON = "application/json"


def run(coro):
    return asyncio.run(coro)


def frame(header: dict, payload: bytes = PDF_BYTES) -> bytes:
    encoded = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return len(encoded).to_bytes(4, "big") + encoded + payload


def header(**overrides) -> dict:
    value = {
        "file": dict(FILE_PROJECTION),
        "byte_size": len(PDF_BYTES),
        "sha256": hashlib.sha256(PDF_BYTES).hexdigest(),
        "version_evidence": dict(VERSION_EVIDENCE),
        "authorization": dict(AUTHORIZATION),
        "contract_version": PDF_BINARY_CONTRACT_VERSION,
    }
    value.update(overrides)
    return value


def engine_error(code: str, message: str = "raw provider internal detail") -> bytes:
    return json.dumps(
        {
            "ok": False,
            "error": {"code": code, "message": message, "retryable": False, "metadata": None},
        },
        separators=(",", ":"),
    ).encode("utf-8")


class _Chunk:
    def __init__(self, value=None, done: bool = False) -> None:
        self.value = value
        self.done = done


class _Reader:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.cancelled = False

    async def read(self) -> _Chunk:
        if not self._chunks:
            return _Chunk(done=True)
        return _Chunk(value=self._chunks.pop(0))

    async def cancel(self) -> None:
        self.cancelled = True


class _Stream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.reader = _Reader(chunks)

    def getReader(self) -> _Reader:
        return self.reader


class FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"",
        content_type=None,
        chunks=None,
    ):
        self.status = status
        self.body = _Stream(chunks if chunks is not None else ([body] if body else []))
        self.headers = {} if content_type is None else {"content-type": content_type}

    async def text(self) -> str:
        raise AssertionError("a byte route must never be read as text")


class FakeEngineBinding:
    """Exposes the four folder RPCs plus fetch, recording which one was used."""

    def __init__(self, *, responses: dict | None = None, fetch_response=None, fetch_raises=False):
        self.responses = responses or {}
        self.fetch_response = fetch_response
        self.fetch_raises = fetch_raises
        self.rpc_calls: list[tuple[str, dict]] = []
        self.fetch_calls: list[dict] = []

    async def drive_case_folder_status(self, payload):
        self.rpc_calls.append(("drive_case_folder_status", dict(payload)))
        return {
            "ok": True,
            "status": {
                "configured": False,
                "space_kind": None,
                "scope_token": None,
                "updated_at": None,
            },
            "contract_version": "v1",
        }

    async def drive_case_folder_folders(self, payload):
        self.rpc_calls.append(("drive_case_folder_folders", dict(payload)))
        return {"ok": True, "folders": [], "more": False, "exhaustive": False, "contract_version": "v1"}

    async def drive_case_folder_select(self, payload):
        self.rpc_calls.append(("drive_case_folder_select", dict(payload)))
        return {
            "ok": True,
            "outcome": "created",
            "status": {"configured": True, "space_kind": "my_drive", "updated_at": None},
            "contract_version": "v1",
        }

    async def drive_case_folder_clear(self, payload):
        self.rpc_calls.append(("drive_case_folder_clear", dict(payload)))
        return {"ok": True, "cleared": True}

    async def b67_case_pdf_candidates(self, payload):
        self.rpc_calls.append((PDF_CANDIDATES_OPERATION, dict(payload)))
        return {
            "ok": True,
            "files": [dict(FILE_PROJECTION)],
            "more": False,
            "direct_child_only": True,
            "contract_version": "engine-b67-case-pdf.v1",
        }

    async def b67_case_pdf_read(self, payload):
        self.rpc_calls.append((PDF_READ_OPERATION, dict(payload)))
        return self.responses.get(
            PDF_READ_OPERATION,
            {
                "ok": True,
                "file": dict(FILE_PROJECTION),
                "content_base64": base64.b64encode(PDF_BYTES).decode("ascii"),
                "byte_size": len(PDF_BYTES),
                "version_evidence": dict(VERSION_EVIDENCE),
                "authorization": dict(AUTHORIZATION),
                "contract_version": "engine-b67-case-pdf.v1",
            },
        )

    async def b67_case_pdf_review_extraction(self, payload):
        self.rpc_calls.append(("b67_case_pdf_review_extraction", dict(payload)))
        return {"ok": True}

    async def fetch(self, js_object):
        self.fetch_calls.append(dict(js_object))
        if self.fetch_raises:
            raise RuntimeError("private Engine unavailable")
        if self.fetch_response is None:
            return FakeResponse(status=404, body=engine_error("not_found", "gone"))
        return self.fetch_response


class FakeRequest:
    """A workerd Request: the binding receives the JS object, never the Python wrapper."""

    def __init__(self, url: str, **options) -> None:
        self.js_object = {"url": url, **options}


def request(url: str, **options) -> FakeRequest:
    return FakeRequest(url, **options)


def binary_client(binding, *, caller_id=CALLER_ID, credential=CREDENTIAL, factory=True):
    return CloudflareDriveCaseFolderEngineClient(
        binding,
        caller_id=caller_id,
        credential=credential,
        request_factory=(lambda url, **kwargs: request(url, **kwargs)) if factory else None,
    )


def read(client=None, binding=None, **kwargs):
    client = client or binary_client(binding)
    return run(client.read_pdf(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID, file_id=FILE_ID, **kwargs))


def response_for(body: bytes, *, status: int = 200, content_type=OCTET_STREAM) -> FakeResponse:
    return FakeResponse(status=status, body=body, content_type=content_type)


def refusal(code: str, status: int) -> FakeResponse:
    """One bounded Engine JSON refusal, exactly as the deny-by-default route answers."""
    return FakeResponse(status=status, body=engine_error(code), content_type=JSON)


def error(code: str, action) -> DriveCaseFolderEngineError:
    with pytest.raises(DriveCaseFolderEngineError) as caught:
        action()
    return caught.value


# --- happy path -------------------------------------------------------------


def test_byte_route_reads_the_pdf_without_touching_the_rpc() -> None:
    binding = FakeEngineBinding(fetch_response=response_for(frame(header())))
    body = read(binding=binding)

    assert binding.rpc_calls == []
    assert len(binding.fetch_calls) == 1
    call = binding.fetch_calls[0]
    assert call["url"] == f"https://padiem-ai-engine.internal{PDF_BINARY_READ_PATH}"
    assert call["method"] == "POST"
    assert json.loads(call["body"]) == {
        "app_id": PDF_BINARY_READ_APP_ID,
        "workspace_ref": WORKSPACE_REF,
        "project_id": PROJECT_ID,
        "file_id": FILE_ID,
    }
    headers = call["headers"]
    assert headers["x-padiem-engine-caller"] == CALLER_ID
    assert headers["x-padiem-engine-credential"] == CREDENTIAL
    assert headers["accept"] == "application/octet-stream"
    assert base64.b64decode(body["content_base64"], validate=True) == PDF_BYTES
    assert body["byte_size"] == len(PDF_BYTES)
    assert body["version_evidence"] == VERSION_EVIDENCE
    assert body["authorization"] == {"direct_parent_proof": True, "source_type": "drive"}


def test_binary_and_rpc_paths_answer_identically() -> None:
    byte_body = read(binding=FakeEngineBinding(fetch_response=response_for(frame(header()))))
    rpc_body = read(
        CloudflareDriveCaseFolderEngineClient(FakeEngineBinding()),
    )
    assert byte_body == rpc_body


def test_payload_that_is_not_text_survives_byte_for_byte() -> None:
    payload = b"%PDF-1.7\n" + bytes(range(256)) + b"\n%%EOF"
    binding = FakeEngineBinding(
        fetch_response=response_for(
            frame(header(byte_size=len(payload), sha256=hashlib.sha256(payload).hexdigest()), payload)
        )
    )
    body = read(binding=binding)
    assert base64.b64decode(body["content_base64"], validate=True) == payload
    assert body["byte_size"] == len(payload)


def test_streamed_chunks_are_reassembled_under_the_same_bound() -> None:
    encoded = frame(header())
    middle = len(encoded) // 2
    binding = FakeEngineBinding()
    binding.fetch_response = FakeResponse(status=200, content_type=OCTET_STREAM)
    binding.fetch_response.body = _Stream([encoded[:middle], encoded[middle:]])
    body = read(binding=binding)
    assert base64.b64decode(body["content_base64"], validate=True) == PDF_BYTES


# --- legacy fallback --------------------------------------------------------


def test_absent_route_falls_back_to_the_rpc_exactly_once() -> None:
    binding = FakeEngineBinding(fetch_response=refusal("not_found", 404))
    body = read(binding=binding)

    assert len(binding.fetch_calls) == 1
    assert binding.rpc_calls == [
        (PDF_READ_OPERATION, {"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID, "file_id": FILE_ID})
    ]
    assert base64.b64decode(body["content_base64"], validate=True) == PDF_BYTES


def test_binding_without_a_trusted_transport_stays_on_the_rpc() -> None:
    binding = FakeEngineBinding()
    body = read(CloudflareDriveCaseFolderEngineClient(binding))
    assert binding.fetch_calls == []
    assert [operation for operation, _ in binding.rpc_calls] == [PDF_READ_OPERATION]
    assert base64.b64decode(body["content_base64"], validate=True) == PDF_BYTES


@pytest.mark.parametrize(
    "overrides",
    [
        {"caller_id": None},
        {"credential": None},
        {"caller_id": ""},
        {"credential": ""},
        {"factory": False},
    ],
)
def test_a_partial_transport_never_sends_a_partial_identity(overrides: dict) -> None:
    binding = FakeEngineBinding(fetch_response=response_for(frame(header())))
    kwargs = {"caller_id": CALLER_ID, "credential": CREDENTIAL, "factory": True}
    kwargs.update(overrides)
    body = read(binary_client(binding, **kwargs))
    assert binding.fetch_calls == []
    assert [operation for operation, _ in binding.rpc_calls] == [PDF_READ_OPERATION]
    assert body["byte_size"] == len(PDF_BYTES)


def test_404_without_the_not_found_contract_does_not_retry() -> None:
    binding = FakeEngineBinding(fetch_response=refusal("drive_not_connected", 404))
    failure = error("drive_not_connected", lambda: read(binding=binding))
    assert failure.status_code == 409
    assert binding.rpc_calls == []


def test_unparsable_404_body_does_not_retry() -> None:
    binding = FakeEngineBinding(
        fetch_response=FakeResponse(status=404, body=b"gateway blob", content_type=JSON)
    )
    failure = error("drive_case_pdf_response_invalid", lambda: read(binding=binding))
    assert failure.status_code == 502
    assert binding.rpc_calls == []


# --- refusals and faults ----------------------------------------------------


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("execution_fallback_required", 413),
        ("pdf_integrity_mismatch", 502),
        ("pdf_signature_mismatch", 415),
        ("drive_case_pdf_unavailable", 503),
        ("drive_workspace_mismatch", 403),
    ],
)
def test_engine_refusals_keep_the_existing_bounded_taxonomy(code: str, status: int) -> None:
    binding = FakeEngineBinding(fetch_response=refusal(code, status))
    failure = error(code, lambda: read(binding=binding))
    assert failure.status_code == status
    assert "raw provider internal detail" not in str(failure)
    assert binding.rpc_calls == []


def test_an_unknown_engine_code_never_reaches_a_product() -> None:
    binding = FakeEngineBinding(fetch_response=refusal("totally_injected", 400))
    failure = error("drive_case_folder_failed", lambda: read(binding=binding))
    assert failure.status_code == 502
    assert "totally_injected" not in str(failure)


def test_transport_fault_is_bounded_and_not_retried() -> None:
    binding = FakeEngineBinding(fetch_raises=True)
    failure = error("drive_case_folder_engine_failed", lambda: read(binding=binding))
    assert failure.status_code == 502
    assert "private Engine unavailable" not in str(failure)
    assert binding.rpc_calls == []


@pytest.mark.parametrize(
    "content_type",
    [JSON, "text/plain", None, "application/octet-stream; charset=utf-8"],
)
def test_only_the_bare_octet_stream_type_is_a_byte_response(content_type) -> None:
    """A 200 that is not exactly the declared byte type is never frame-parsed."""

    binding = FakeEngineBinding(
        fetch_response=FakeResponse(status=200, body=frame(header()), content_type=content_type)
    )
    failure = error("drive_case_pdf_response_invalid", lambda: read(binding=binding))
    assert failure.status_code == 502
    assert binding.rpc_calls == []


def test_an_oversize_stream_is_refused_at_the_existing_pdf_ceiling() -> None:
    payload = b"%PDF-1.7" + b"x" * MAX_BINARY_PDF_FRAME_BYTES
    binding = FakeEngineBinding(
        fetch_response=response_for(
            frame(
                header(byte_size=len(payload), sha256=hashlib.sha256(payload).hexdigest()),
                payload,
            )
        )
    )
    failure = error("drive_case_folder_engine_failed", lambda: read(binding=binding))
    assert failure.status_code == 502
    assert binding.rpc_calls == []
    assert binding.fetch_response.body.reader.cancelled is True


# --- frame validation -------------------------------------------------------


@pytest.mark.parametrize(
    ("mutated", "expected"),
    [
        ({"byte_size": len(PDF_BYTES) + 1}, "length mismatch"),
        ({"sha256": "f" * 64}, "digest mismatch"),
        ({"sha256": "NOT-A-DIGEST"}, "digest shape"),
        ({"contract_version": "engine-b67-case-pdf.v1"}, "contract drift"),
        ({"file": {**FILE_PROJECTION, "intake_state": "size_unverified"}}, "intake state"),
        ({"file": {**FILE_PROJECTION, "resource_key": "leak"}}, "extra file field"),
        ({"authorization": {"direct_parent_proof": False, "source_type": "drive"}}, "proof"),
        ({"version_evidence": {**VERSION_EVIDENCE, "version": "7.7"}}, "revision type"),
    ],
)
def test_a_mismatched_frame_is_untrusted(mutated: dict, expected: str) -> None:
    binding = FakeEngineBinding(fetch_response=response_for(frame(header(**mutated))))
    failure = error("drive_case_pdf_response_invalid", lambda: read(binding=binding))
    assert failure.status_code == 502, expected
    assert binding.rpc_calls == []


def test_payload_swapped_after_a_valid_header_fails_the_digest() -> None:
    other = b"%PDF-1.7\ncompletely different bytes\n%%EOF"
    binding = FakeEngineBinding(fetch_response=response_for(frame(header(), other)))
    failure = error("drive_case_pdf_response_invalid", lambda: read(binding=binding))
    assert failure.status_code == 502
    assert binding.rpc_calls == []


def test_a_non_pdf_payload_is_rejected_before_the_body_is_returned() -> None:
    payload = b"MZ\x90\x00not a pdf"
    binding = FakeEngineBinding(
        fetch_response=response_for(
            frame(header(byte_size=len(payload), sha256=hashlib.sha256(payload).hexdigest()), payload)
        )
    )
    failure = error("drive_case_pdf_response_invalid", lambda: read(binding=binding))
    assert failure.status_code == 502


def test_extra_or_missing_header_keys_are_denied() -> None:
    for mutated in (
        {**header(), "object_key": "drive/raw/path"},
        {k: v for k, v in header().items() if k != "sha256"},
    ):
        binding = FakeEngineBinding(fetch_response=response_for(frame(mutated)))
        failure = error("drive_case_pdf_response_invalid", lambda: read(binding=binding))
        assert failure.status_code == 502
        assert "drive/raw/path" not in str(failure)


def test_truncated_frames_are_denied() -> None:
    for raw in (b"", b"\x00\x00\x00\x02{}" + PDF_BYTES, frame(header())[:6]):
        binding = FakeEngineBinding(fetch_response=response_for(raw))
        failure = error("drive_case_pdf_response_invalid", lambda: read(binding=binding))
        assert failure.status_code == 502


def test_legacy_rpc_shares_the_revision_grammar() -> None:
    """The fallback path runs before Engine deploys, so it must be as strict.

    Drive sends ``version`` as an integer: a real integer revision is accepted
    and a string revision is refused on the Base64 RPC exactly as on the byte
    route.
    """

    integer_binding = FakeEngineBinding()
    body = read(CloudflareDriveCaseFolderEngineClient(integer_binding))
    assert body["version_evidence"]["version"] == 7

    for mutated in ({"version": "7.7"}, {"version": True}, {"version": -1}):
        payload = {
            "ok": True,
            "file": dict(FILE_PROJECTION),
            "content_base64": base64.b64encode(PDF_BYTES).decode("ascii"),
            "byte_size": len(PDF_BYTES),
            "version_evidence": {**VERSION_EVIDENCE, **mutated},
            "authorization": dict(AUTHORIZATION),
            "contract_version": "engine-b67-case-pdf.v1",
        }
        binding = FakeEngineBinding(responses={PDF_READ_OPERATION: payload})
        failure = error(
            "drive_case_pdf_response_invalid",
            lambda: read(CloudflareDriveCaseFolderEngineClient(binding)),
        )
        assert failure.status_code == 502


def test_binary_response_never_echoes_private_refs() -> None:
    binding = FakeEngineBinding(fetch_response=response_for(frame(header())))
    rendered = json.dumps(read(binding=binding))
    assert WORKSPACE_REF not in rendered
    assert PROJECT_ID not in rendered
    assert "object_key" not in rendered


def test_other_operations_still_use_their_own_rpcs() -> None:
    binding = FakeEngineBinding(fetch_response=response_for(frame(header())))
    run(binding.b67_case_pdf_candidates({"workspace_ref": WORKSPACE_REF, "project_id": PROJECT_ID}))
    client = binary_client(binding)
    body = run(client.pdf_candidates(workspace_ref=WORKSPACE_REF, project_id=PROJECT_ID))
    assert body["files"][0]["file_id"] == FILE_ID
    assert binding.fetch_calls == []


# --- seam posture -----------------------------------------------------------


def test_snapshot_declares_the_byte_route_without_claiming_activation() -> None:
    snapshot = drive_case_folder_engine_seam_snapshot()
    assert snapshot["pdf_read_binary_route"] == PDF_BINARY_READ_PATH
    assert snapshot["pdf_read_binary_transport_composed_by_default"] is False
    assert snapshot["pdf_read_app_id_is_canonical_drive_reader"] is True
    assert snapshot["legacy_base64_rpc_fallback_requires_missing_route"] is True
    assert snapshot["production_binding_activated"] is False


def test_the_seam_declares_no_second_engine_binding_authority() -> None:
    import app.drive_case_folder_engine as engine_module

    source = pathlib.Path(engine_module.__file__).read_text(encoding="utf-8")
    assert "P01_ENGINE_SERVICE_BINDING_NAME" in source
    assert '"PADIEM_AI_ENGINE"' not in source
    assert "PADIEM_AI_ENGINE_BINDING_NAME" in source
    assert PDF_BINARY_READ_APP_ID in source


def test_worker_composition_passes_the_existing_p01_caller() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    worker_source = (root / "worker.py").read_text(encoding="utf-8")
    assert "CloudflareDriveCaseFolderEngineClient" in worker_source
    assert "drive_p01_config" in worker_source
    assert "request_factory=Request" in worker_source
