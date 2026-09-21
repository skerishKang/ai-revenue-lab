"""#2824 S3-B: one parser-authority boundary for Worker binary document parsing.

These tests prove the shared Core boundary decision, not merely an error
string:

* the production Worker runtime resolves to ``PARSER_AUTHORITY=UNAVAILABLE``
  and fails closed with a bounded, deterministic code;
* the Core parser is **never invoked** on that path (spy/canary count == 0);
* the production Worker has no fallback to the in-process parser;
* no caller input can select a parser implementation or a runtime mode;
* no timeout/thread/process/network primitive is accepted as isolation;
* the error projection leaks no traceback, host path or document body.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from unittest import mock

import pytest

import padiem_ai_core.document_parser_boundary as boundary
from padiem_ai_core.document_normalization import NormalizedDocument
from padiem_ai_core.document_parser_boundary import (
    DOCUMENT_PARSER_ISOLATION_UNAVAILABLE,
    PRODUCTION_WORKER_PLATFORM,
    BinaryDocumentParserPort,
    DocumentParserAuthorityUnavailable,
    parse_binary_document_via_authority,
    production_worker_runtime,
    resolve_binary_document_parser_authority,
)

BOUNDARY_SOURCE = Path(boundary.__file__).read_text(encoding="utf-8")
BOUNDARY_TREE = ast.parse(BOUNDARY_SOURCE, filename=str(boundary.__file__))

FORBIDDEN_IMPORT_ROOTS = {
    "asyncio",
    "concurrent",
    "httpx",
    "multiprocessing",
    "requests",
    "signal",
    "socket",
    "subprocess",
    "threading",
}
FORBIDDEN_NAMES = {
    "Popen",
    "Process",
    "ProcessPoolExecutor",
    "Thread",
    "ThreadPoolExecutor",
    "alarm",
    "create_subprocess_exec",
    "fork",
    "setitimer",
    "spawn",
    "wait_for",
}

VALID_PAYLOAD = b"%PDF-1.7 minimal body"
VALID_NAME = "report.pdf"
VALID_MEDIA = "application/pdf"


def _worker_runtime():
    """Deterministic production Worker simulation: no network, no subprocess."""

    return mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM)


def _canned_document() -> NormalizedDocument:
    return NormalizedDocument(
        name=VALID_NAME,
        media_type=VALID_MEDIA,
        text="canned",
        byte_size=len(VALID_PAYLOAD),
        source_kind="binary",
    )


class _CoreParserSpy:
    """Canary for ``padiem_ai_core.document_normalization.extract_binary_document``."""

    def __init__(self, result: NormalizedDocument | None = None) -> None:
        self.calls = 0
        self._result = result

    def __call__(self, *, name: object, media_type: object, payload: object) -> NormalizedDocument:
        self.calls += 1
        if self._result is None:
            raise AssertionError("Core binary parser must not run on this path")
        return self._result


# --- A: runtime classification is server-derived -------------------------------


def test_runtime_classification_comes_from_the_interpreter() -> None:
    assert production_worker_runtime() is (sys.platform == PRODUCTION_WORKER_PLATFORM)
    with _worker_runtime():
        assert production_worker_runtime() is True
    assert production_worker_runtime() is False


# --- A/B: production Worker fails closed before the Core parser ----------------


def test_production_worker_authority_is_unavailable_with_a_bounded_code() -> None:
    with _worker_runtime(), pytest.raises(DocumentParserAuthorityUnavailable) as info:
        resolve_binary_document_parser_authority()
    assert info.value.code == DOCUMENT_PARSER_ISOLATION_UNAVAILABLE
    assert info.value.code == "document_parser_isolation_unavailable"
    assert info.value.safe_message == str(info.value)


def test_production_worker_never_invokes_the_core_parser() -> None:
    spy = _CoreParserSpy(result=_canned_document())
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(DocumentParserAuthorityUnavailable):
            parse_binary_document_via_authority(
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
            )
    assert spy.calls == 0


def test_production_worker_has_no_fallback_to_the_in_process_parser() -> None:
    canary = _CoreParserSpy(result=_canned_document())
    with _worker_runtime(), mock.patch.object(boundary, "_LOCAL_REVIEWED_PARSER", canary):
        with pytest.raises(DocumentParserAuthorityUnavailable):
            parse_binary_document_via_authority(
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
            )
    assert canary.calls == 0


# --- control: local CPython still uses the reviewed local parser ---------------


def test_local_runtime_uses_the_reviewed_local_parser() -> None:
    spy = _CoreParserSpy(result=_canned_document())
    with mock.patch.object(boundary, "extract_binary_document", spy):
        document = parse_binary_document_via_authority(
            name=VALID_NAME,
            media_type=VALID_MEDIA,
            payload=VALID_PAYLOAD,
        )
    assert spy.calls == 1
    assert isinstance(document, NormalizedDocument)
    assert document.source_kind == "binary"


# --- E: no caller input can select the parser or the runtime mode --------------


def test_authority_surface_accepts_document_identity_only() -> None:
    entry = inspect.signature(parse_binary_document_via_authority)
    assert set(entry.parameters) == {"name", "media_type", "payload"}
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in entry.parameters.values()
    )
    resolve = inspect.signature(resolve_binary_document_parser_authority)
    assert set(resolve.parameters) == set()
    port = inspect.signature(BinaryDocumentParserPort.parse_binary_document)
    assert set(port.parameters) == {"self", "name", "media_type", "payload"}


def test_unknown_parser_or_runtime_arguments_are_rejected() -> None:
    with _worker_runtime():
        with pytest.raises(TypeError):
            parse_binary_document_via_authority(
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
                parser="local",  # type: ignore[call-arg]
            )
        with pytest.raises(TypeError):
            parse_binary_document_via_authority(
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
                runtime_mode="cpython",  # type: ignore[call-arg]
            )


def test_request_metadata_cannot_change_the_decision() -> None:
    spy = _CoreParserSpy(result=_canned_document())
    hostile_name = "../../etc/worker-local.pdf"
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(DocumentParserAuthorityUnavailable):
            parse_binary_document_via_authority(
                name=hostile_name,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
            )
    assert spy.calls == 0
    assert production_worker_runtime() is False  # request input changed nothing


# --- J/K: bounded, sanitized error projection ----------------------------------


def test_error_projection_leaks_no_traceback_host_path_or_body() -> None:
    secret_name = r"C:\Users\operator\payroll-2026.pdf"
    secret_body = b"%PDF-SECRET-BODY-DO-NOT-ECHO"
    with _worker_runtime(), pytest.raises(DocumentParserAuthorityUnavailable) as info:
        parse_binary_document_via_authority(
            name=secret_name,
            media_type=VALID_MEDIA,
            payload=secret_body,
        )
    error = info.value
    projection = " ".join(
        (
            str(error),
            error.code,
            error.safe_message,
            repr(error),
            repr(error.args),
        )
    )
    for leaked in (
        "Traceback",
        "C:\\",
        "payroll",
        "SECRET-BODY",
        "extract_binary_document",
        "document_normalization",
    ):
        assert leaked not in projection
    assert projection.count(DOCUMENT_PARSER_ISOLATION_UNAVAILABLE) >= 1


# --- L/M6: no fake isolation, no new process/network authority ------------------


def test_boundary_imports_no_process_timeout_or_network_primitive() -> None:
    imported: set[str] = set()
    for node in ast.walk(BOUNDARY_TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported & FORBIDDEN_IMPORT_ROOTS == set()


def test_boundary_references_no_timeout_spawn_or_signal_primitive() -> None:
    referenced: set[str] = set()
    for node in ast.walk(BOUNDARY_TREE):
        if isinstance(node, ast.Attribute):
            referenced.add(node.attr)
        elif isinstance(node, ast.Name):
            referenced.add(node.id)
    assert referenced & FORBIDDEN_NAMES == set()


def test_availability_decision_uses_only_the_interpreter_platform() -> None:
    referenced: set[str] = set()
    for node in ast.walk(BOUNDARY_TREE):
        if isinstance(node, ast.Attribute):
            referenced.add(node.attr)
    assert "platform" in referenced
    # the module is import-light: it owns policy, not transport or storage
    assert not hasattr(boundary, "httpx")
    assert "fetch" not in BOUNDARY_SOURCE
