"""#2936: provider-neutral Worker isolated parser client/transport contract.

These tests prove the contract itself, not a live service:

* callers can supply only the canonical bounded document identity and payload
  (no endpoint/host/command/parser/timeout inputs);
* request and response ceilings derive from existing Core document bounds;
* a success response is only canonical bounded normalized-document material;
* a failure response is only a bounded reason code;
* raw exception text, traceback, host paths and credential-shaped values
  never cross the boundary;
* the transport authority is injected by trusted composition and exercised
  only through an in-memory fake (no live network, no new dependency);
* the production Worker fail-closed default in ``document_parser_boundary``
  is unchanged and this module is not wired into that authority decision.
"""

from __future__ import annotations

import ast
import base64
import inspect
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import padiem_ai_core.isolated_parser_client as client_module
from padiem_ai_core.document_normalization import (
    MAX_BINARY_DOCUMENT_BYTES,
    MAX_DOCUMENT_CHARS,
    NormalizedDocument,
)
from padiem_ai_core.document_parser_boundary import (
    DOCUMENT_PARSER_ISOLATION_UNAVAILABLE,
    PRODUCTION_WORKER_PLATFORM,
    DocumentParserAuthorityUnavailable,
    resolve_binary_document_parser_authority,
)
from padiem_ai_core.document_semantics import DocumentNormalizationError, ExtractionStatus
from padiem_ai_core.isolated_parser_client import (
    ISOLATED_PARSER_MAX_REQUEST_BYTES,
    ISOLATED_PARSER_MAX_RESPONSE_BYTES,
    ISOLATED_PARSER_RESPONSE_INVALID,
    ISOLATED_PARSER_RESPONSE_UNBOUNDED,
    ISOLATED_PARSER_TRANSPORT_FAILED,
    IsolatedParserClient,
    IsolatedParserTransport,
)

CLIENT_SOURCE = Path(client_module.__file__).read_text(encoding="utf-8")
CLIENT_TREE = ast.parse(CLIENT_SOURCE, filename=str(client_module.__file__))
BOUNDARY_PATH = Path(sys.modules["padiem_ai_core.document_parser_boundary"].__file__)

VALID_NAME = "report.pdf"
VALID_MEDIA = "application/pdf"
VALID_PAYLOAD = b"%PDF-1.7 isolated-parser-contract-fixture"

FORBIDDEN_IMPORT_ROOTS = {
    "asyncio",
    "concurrent",
    "httpx",
    "multiprocessing",
    "os",
    "requests",
    "signal",
    "socket",
    "ssl",
    "subprocess",
    "threading",
    "urllib",
}
FORBIDDEN_PARAMETER_NAMES = {
    "base_url",
    "baseurl",
    "command",
    "deadline",
    "endpoint",
    "headers",
    "host",
    "parser",
    "runtime_mode",
    "timeout",
    "timeout_seconds",
    "url",
}
FORBIDDEN_REFERENCES = {
    "Popen",
    "Process",
    "ProcessPoolExecutor",
    "Thread",
    "ThreadPoolExecutor",
    "create_subprocess_exec",
    "environ",
    "fork",
    "getenv",
    "shell",
    "spawn",
    "urlopen",
    "wait_for",
}


def _success_envelope(**overrides: object) -> bytes:
    envelope: dict[str, object] = {
        "type": "document",
        "name": VALID_NAME,
        "media_type": VALID_MEDIA,
        "text": "bounded extracted text",
        "byte_size": len(VALID_PAYLOAD),
        "source_kind": "binary",
        "status": "complete",
        "warnings": [],
    }
    envelope.update(overrides)
    return json.dumps(envelope).encode("utf-8")


def _error_envelope(code: str, **extra: object) -> bytes:
    envelope: dict[str, object] = {"type": "error", "code": code}
    envelope.update(extra)
    return json.dumps(envelope).encode("utf-8")


class FakeInMemoryTransport:
    """In-memory transport fake: records requests, returns canned bytes."""

    def __init__(self, response: bytes | Exception | None = None) -> None:
        self.requests: list[bytes] = []
        self._response = response

    def exchange(self, request: bytes) -> bytes:
        if not isinstance(request, (bytes, bytearray)):
            raise AssertionError("request must be bytes")
        self.requests.append(bytes(request))
        if isinstance(self._response, Exception):
            raise self._response
        if self._response is None:
            raise AssertionError("fake response missing")
        return self._response


def _client(response: bytes | Exception) -> tuple[IsolatedParserClient, FakeInMemoryTransport]:
    transport = FakeInMemoryTransport(response)
    return IsolatedParserClient(transport=transport), transport


def _parse(
    client: IsolatedParserClient,
    *,
    name: object = VALID_NAME,
    media_type: object = VALID_MEDIA,
    payload: object = VALID_PAYLOAD,
) -> NormalizedDocument:
    return client.parse_binary_document(name=name, media_type=media_type, payload=payload)


# --- A: caller surface is identity + payload only ------------------------------


def test_public_parse_surface_is_keyword_only_identity_and_payload() -> None:
    signature = inspect.signature(IsolatedParserClient.parse_binary_document)
    assert set(signature.parameters) == {"self", "name", "media_type", "payload"}
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
        if parameter.name != "self"
    )
    constructor = inspect.signature(IsolatedParserClient.__init__)
    assert set(constructor.parameters) == {"self", "transport"}


def test_endpoint_host_command_parser_and_timeout_inputs_are_rejected() -> None:
    client, _ = _client(_success_envelope())
    rejected: list[dict[str, object]] = [
        {"endpoint": "https://evil.example"},
        {"host": "127.0.0.1"},
        {"url": "http://parser.internal"},
        {"command": ["parser", "--run"]},
        {"parser": "pypdf"},
        {"timeout": 30.0},
        {"timeout_seconds": 5},
    ]
    for extras in rejected:
        with pytest.raises(TypeError):
            client.parse_binary_document(  # type: ignore[call-arg]
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
                **extras,
            )


def test_transport_requires_injected_exchange_port() -> None:
    with pytest.raises(ValueError):
        IsolatedParserClient(transport=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        IsolatedParserClient(transport=object())  # type: ignore[arg-type]
    assert isinstance(FakeInMemoryTransport(_success_envelope()), IsolatedParserTransport)


# --- B: request bounds derive from Core ----------------------------------------


def test_request_bounds_derive_from_core_document_limits() -> None:
    assert ISOLATED_PARSER_MAX_REQUEST_BYTES == (
        ((MAX_BINARY_DOCUMENT_BYTES + 2) // 3) * 4 + 4096
    )
    assert ISOLATED_PARSER_MAX_RESPONSE_BYTES == 256 * 1024
    # worst-case UTF-8 expansion of the full text budget stays under the ceiling
    assert MAX_DOCUMENT_CHARS * 4 < ISOLATED_PARSER_MAX_RESPONSE_BYTES


def test_oversized_payload_fails_before_the_transport() -> None:
    client, transport = _client(_success_envelope())
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client, payload=b"x" * (MAX_BINARY_DOCUMENT_BYTES + 1))
    assert info.value.code == "binary_too_large"
    assert transport.requests == []


def test_non_bytes_and_empty_payload_fail_before_the_transport() -> None:
    client, transport = _client(_success_envelope())
    with pytest.raises(DocumentNormalizationError) as invalid:
        _parse(client, payload="not-bytes")
    assert invalid.value.code == "invalid_binary_payload"
    with pytest.raises(DocumentNormalizationError) as empty:
        _parse(client, payload=b"")
    assert empty.value.code == "empty_document"
    assert transport.requests == []


def test_non_binary_identity_fails_before_the_transport() -> None:
    client, transport = _client(_success_envelope())
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client, name="notes.txt", media_type="text/plain")
    assert transport.requests == []


def test_request_envelope_is_bounded_json_with_identity_and_payload_only() -> None:
    client, transport = _client(_success_envelope())
    _parse(client)
    assert len(transport.requests) == 1
    request = json.loads(transport.requests[0].decode("utf-8"))
    assert set(request) == {"type", "name", "media_type", "payload_b64"}
    assert request["type"] == "isolated_parser_request"
    assert request["name"] == VALID_NAME
    assert request["media_type"] == VALID_MEDIA
    assert base64.b64decode(request["payload_b64"]) == VALID_PAYLOAD
    assert len(transport.requests[0]) <= ISOLATED_PARSER_MAX_REQUEST_BYTES
    lowered = transport.requests[0].lower()
    for leaked in (b"endpoint", b"http://", b"https://", b"timeout", b"command"):
        assert leaked not in lowered


# --- C: success response is canonical bounded document material ----------------


def test_success_round_trip_returns_normalized_document() -> None:
    client, _ = _client(_success_envelope())
    document = _parse(client)
    assert isinstance(document, NormalizedDocument)
    assert document.name == VALID_NAME
    assert document.media_type == VALID_MEDIA
    assert document.source_kind == "binary"
    assert document.byte_size == len(VALID_PAYLOAD)
    assert document.text == "bounded extracted text"
    assert document.status is ExtractionStatus.COMPLETE


def test_response_identity_and_byte_size_must_match_the_request() -> None:
    client, _ = _client(_success_envelope(name="other.pdf"))
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == ISOLATED_PARSER_RESPONSE_INVALID

    client, _ = _client(_success_envelope(byte_size=1))
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == ISOLATED_PARSER_RESPONSE_INVALID


def test_response_must_declare_binary_source_kind() -> None:
    client, _ = _client(_success_envelope(source_kind="text"))
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == ISOLATED_PARSER_RESPONSE_INVALID


def test_response_field_whitelist_rejects_extra_keys() -> None:
    client, _ = _client(_success_envelope(endpoint="https://parser.internal", credential="Bearer abc"))
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == ISOLATED_PARSER_RESPONSE_INVALID


# --- D: response ceiling and structural bounds --------------------------------


def test_oversized_response_is_rejected_as_unbounded() -> None:
    client, _ = _client(b"x" * (ISOLATED_PARSER_MAX_RESPONSE_BYTES + 1))
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == ISOLATED_PARSER_RESPONSE_UNBOUNDED


def test_non_bytes_non_json_and_non_object_responses_are_invalid() -> None:
    for bad in (b"", b"not-json", json.dumps([1, 2, 3]).encode("utf-8"), json.dumps("ok").encode("utf-8")):
        client, _ = _client(bad)
        with pytest.raises(DocumentNormalizationError) as info:
            _parse(client)
        assert info.value.code == ISOLATED_PARSER_RESPONSE_INVALID


def test_unknown_response_kind_is_invalid() -> None:
    client, _ = _client(json.dumps({"type": "service_metadata", "host": "parser-1"}).encode("utf-8"))
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == ISOLATED_PARSER_RESPONSE_INVALID


# --- E: failure envelope is a bounded reason code only -------------------------


def test_bounded_error_code_crosses_as_document_normalization_error() -> None:
    client, _ = _client(_error_envelope("pdf_encrypted"))
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == "pdf_encrypted"
    assert "Traceback" not in str(info.value)


@pytest.mark.parametrize(
    "hostile_code",
    [
        "Traceback (most recent call last)",
        "C:\\Users\\operator\\secrets.env",
        "credential=super-secret-value",
        "UPPER_CASE_CODE",
        "",
        "a" * 65,
    ],
)
def test_hostile_error_codes_are_rejected(hostile_code: str) -> None:
    client, _ = _client(_error_envelope(hostile_code))
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == ISOLATED_PARSER_RESPONSE_INVALID


def test_error_envelope_field_whitelist_rejects_service_metadata() -> None:
    client, _ = _client(
        json.dumps(
            {
                "type": "error",
                "code": "pdf_invalid",
                "host": "parser.internal",
                "detail": "raw upstream text",
            }
        ).encode("utf-8")
    )
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == ISOLATED_PARSER_RESPONSE_INVALID


# --- F: raw exceptions never cross the boundary -------------------------------


def test_transport_exception_is_sanitized_without_chained_cause() -> None:
    hostile = RuntimeError(r"C:\Users\operator\payroll-2026.pdf traceback credential=abc")
    client, _ = _client(hostile)
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    error = info.value
    assert error.code == ISOLATED_PARSER_TRANSPORT_FAILED
    projection = " ".join((str(error), error.code, error.safe_message, repr(error), repr(error.args)))
    for leaked in (
        "Traceback",
        "C:\\",
        "payroll",
        "credential=abc",
        "RuntimeError",
        "isolated_parser_client.py",
    ):
        assert leaked not in projection
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is False


def test_document_normalization_errors_from_transport_pass_through() -> None:
    client, _ = _client(DocumentNormalizationError("pdf_encrypted", "Encrypted PDF documents are not supported."))
    with pytest.raises(DocumentNormalizationError) as info:
        _parse(client)
    assert info.value.code == "pdf_encrypted"


# --- G: trusted server composition only ----------------------------------------


def test_client_has_no_network_or_process_surface() -> None:
    assert not hasattr(client_module, "httpx")
    assert not hasattr(client_module, "requests")
    assert "fetch(" not in CLIENT_SOURCE
    assert "shell=True" not in CLIENT_SOURCE
    assert "os.environ" not in CLIENT_SOURCE
    assert not hasattr(client_module, "http")


def test_ast_imports_and_references_stay_off_network_and_process_authority() -> None:
    imported: set[str] = set()
    referenced: set[str] = set()
    parameter_names: set[str] = set()
    for node in ast.walk(CLIENT_TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        if isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.Name):
            referenced.add(node.id)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parameter_names.update(arg.arg for arg in node.args.args)
            parameter_names.update(arg.arg for arg in node.args.kwonlyargs)
    assert imported & FORBIDDEN_IMPORT_ROOTS == set()
    assert referenced & FORBIDDEN_REFERENCES == set()
    assert parameter_names & FORBIDDEN_PARAMETER_NAMES == set()


def test_no_new_runtime_dependency_is_declared_for_this_contract() -> None:
    assert set(client_module.__dict__)  # module imported from package path only
    for name in ("base64", "binascii", "json", "re"):
        assert name in sys.stdlib_module_names


# --- H: production Worker fail-closed default is unchanged --------------------


def test_production_worker_authority_still_fails_closed() -> None:
    with mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM):
        with pytest.raises(DocumentParserAuthorityUnavailable) as info:
            resolve_binary_document_parser_authority()
    assert info.value.code == DOCUMENT_PARSER_ISOLATION_UNAVAILABLE


def test_boundary_module_does_not_reference_the_new_client() -> None:
    boundary_source = BOUNDARY_PATH.read_text(encoding="utf-8")
    assert "isolated_parser_client" not in boundary_source
    assert "IsolatedParserClient" not in boundary_source
    assert "parse_binary_document_via_authority" in boundary_source


def test_importing_the_client_does_not_bind_a_live_transport() -> None:
    client = IsolatedParserClient(transport=FakeInMemoryTransport(_success_envelope()))
    assert isinstance(client.transport, FakeInMemoryTransport)
    # no default transport exists on the module
    assert not hasattr(client_module, "DEFAULT_TRANSPORT")
    assert not hasattr(client_module, "LIVE_TRANSPORT")
    assert "LIVE_PARSER_SERVICE_BOUND" not in CLIENT_SOURCE
