"""#2824: trusted server composition foundation for the Worker isolated parser.

These tests prove the composition seam itself — not a live service:

* importing the composition module installs nothing (Worker stays fail-closed);
* trusted composition may install the existing client as the single Worker
  authority through the one existing resolver;
* local CPython keeps its reviewed local parser even when composition exists;
* no caller/request input can install, replace or clear the composition;
* the install/compose surface accepts no endpoint/host/command/credential/
  timeout/parser-selection parameters;
* no network or process primitive exists on either new/changed surface;
* Chat and Engine still call only the shared authority entry point;
* SECOND_BINARY_PARSER_AUTHORITY stays 0 (one resolver, one Worker answer).
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path
from unittest import mock

import pytest

import padiem_ai_core.document_parser_boundary as boundary
import padiem_ai_core.isolated_parser_composition as composition_module
from padiem_ai_core.document_normalization import NormalizedDocument
from padiem_ai_core.document_parser_boundary import (
    DOCUMENT_PARSER_ISOLATION_UNAVAILABLE,
    PRODUCTION_WORKER_PLATFORM,
    DocumentParserAuthorityUnavailable,
    parse_binary_document_via_authority,
    resolve_binary_document_parser_authority,
)
from padiem_ai_core.document_semantics import DocumentNormalizationError
from padiem_ai_core.isolated_parser_client import (
    ISOLATED_PARSER_TRANSPORT_FAILED,
    IsolatedParserClient,
)
from padiem_ai_core.isolated_parser_composition import (
    compose_worker_isolated_parser_authority,
    reset_worker_isolated_parser_composition,
)

BOUNDARY_PATH = Path(boundary.__file__)
BOUNDARY_SOURCE = BOUNDARY_PATH.read_text(encoding="utf-8")
BOUNDARY_TREE = ast.parse(BOUNDARY_SOURCE, filename=str(BOUNDARY_PATH))
COMPOSITION_PATH = Path(composition_module.__file__)
COMPOSITION_SOURCE = COMPOSITION_PATH.read_text(encoding="utf-8")
COMPOSITION_TREE = ast.parse(COMPOSITION_SOURCE, filename=str(COMPOSITION_PATH))

VALID_NAME = "report.pdf"
VALID_MEDIA = "application/pdf"
VALID_PAYLOAD = b"%PDF-1.7 composition-foundation-fixture"

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
    "credential",
    "deadline",
    "endpoint",
    "headers",
    "host",
    "parser",
    "runtime_mode",
    "secret",
    "timeout",
    "timeout_seconds",
    "token",
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


@pytest.fixture(autouse=True)
def _composition_isolation():
    """Never leak the server-owned composition slot across tests."""

    reset_worker_isolated_parser_composition()
    yield
    reset_worker_isolated_parser_composition()


def _worker_runtime():
    return mock.patch.object(sys, "platform", PRODUCTION_WORKER_PLATFORM)


def _success_envelope() -> bytes:
    import json

    envelope = {
        "type": "document",
        "name": VALID_NAME,
        "media_type": VALID_MEDIA,
        "text": "bounded extracted text",
        "byte_size": len(VALID_PAYLOAD),
        "source_kind": "binary",
        "status": "complete",
        "warnings": [],
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")


class FakeInMemoryTransport:
    def __init__(self, response: bytes | Exception) -> None:
        self.requests: list[bytes] = []
        self._response = response

    def exchange(self, request: bytes) -> bytes:
        self.requests.append(bytes(request))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _CoreParserSpy:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *, name: object, media_type: object, payload: object) -> NormalizedDocument:
        self.calls += 1
        raise AssertionError("Core binary parser must not run on the composed path")


# --- import does not arm composition (fail-closed default preserved) -----------


def test_importing_the_composition_module_installs_nothing() -> None:
    assert boundary._WORKER_ISOLATED_PARSER_COMPOSITION is None
    with _worker_runtime(), pytest.raises(DocumentParserAuthorityUnavailable) as info:
        resolve_binary_document_parser_authority()
    assert info.value.code == DOCUMENT_PARSER_ISOLATION_UNAVAILABLE


def test_default_worker_fail_closed_is_unchanged_without_composition() -> None:
    spy = _CoreParserSpy()
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(DocumentParserAuthorityUnavailable):
            parse_binary_document_via_authority(
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
            )
    assert spy.calls == 0


# --- Q1/Q3: trusted composition seam wires the existing client into resolve ----


def test_composed_worker_resolves_to_the_installed_client() -> None:
    transport = FakeInMemoryTransport(_success_envelope())
    installed = compose_worker_isolated_parser_authority(transport=transport)
    assert isinstance(installed, IsolatedParserClient)
    with _worker_runtime():
        authority = resolve_binary_document_parser_authority()
    assert authority is installed
    assert authority is boundary._WORKER_ISOLATED_PARSER_COMPOSITION


def test_composed_worker_parse_goes_through_the_injected_transport() -> None:
    transport = FakeInMemoryTransport(_success_envelope())
    compose_worker_isolated_parser_authority(transport=transport)
    spy = _CoreParserSpy()
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        document = parse_binary_document_via_authority(
            name=VALID_NAME,
            media_type=VALID_MEDIA,
            payload=VALID_PAYLOAD,
        )
    assert spy.calls == 0
    assert isinstance(document, NormalizedDocument)
    assert document.source_kind == "binary"
    assert document.text == "bounded extracted text"
    assert len(transport.requests) == 1


def test_composed_worker_transport_failure_stays_bounded_and_fail_closed() -> None:
    transport = FakeInMemoryTransport(OSError("connection refused"))
    compose_worker_isolated_parser_authority(transport=transport)
    spy = _CoreParserSpy()
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(DocumentNormalizationError) as info:
            parse_binary_document_via_authority(
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
            )
    assert spy.calls == 0
    assert info.value.code == ISOLATED_PARSER_TRANSPORT_FAILED
    projection = " ".join((str(info.value), repr(info.value), repr(info.value.args)))
    assert "connection refused" not in projection
    assert "Traceback" not in projection
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def test_reset_restores_worker_fail_closed_default() -> None:
    compose_worker_isolated_parser_authority(
        transport=FakeInMemoryTransport(_success_envelope())
    )
    with _worker_runtime():
        assert resolve_binary_document_parser_authority() is not None
    reset_worker_isolated_parser_composition()
    with _worker_runtime(), pytest.raises(DocumentParserAuthorityUnavailable):
        resolve_binary_document_parser_authority()


# --- Q4: one resolver, local authority unchanged, no second parser authority ---


def test_local_authority_ignores_worker_composition() -> None:
    compose_worker_isolated_parser_authority(
        transport=FakeInMemoryTransport(_success_envelope())
    )
    authority = resolve_binary_document_parser_authority()
    assert authority is boundary._LOCAL_REVIEWED_PARSER
    assert not isinstance(authority, IsolatedParserClient)


def test_single_resolver_entry_point_is_preserved() -> None:
    assert set(inspect.signature(resolve_binary_document_parser_authority).parameters) == set()
    entry = inspect.signature(parse_binary_document_via_authority)
    assert set(entry.parameters) == {"name", "media_type", "payload"}
    compose = inspect.signature(compose_worker_isolated_parser_authority)
    assert set(compose.parameters) == {"transport"}
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in compose.parameters.values()
    )
    install = inspect.signature(
        boundary.install_worker_isolated_parser_composition
    )
    assert set(install.parameters) == {"authority"}


def test_second_parser_authority_symbols_are_not_introduced() -> None:
    for source in (BOUNDARY_SOURCE, COMPOSITION_SOURCE):
        assert "SECOND_BINARY_PARSER_AUTHORITY" not in source
        assert "resolve_binary_document_parser_authority" in source or source is COMPOSITION_SOURCE
    # exactly one Worker resolver definition lives in the boundary module
    assert BOUNDARY_SOURCE.count("def resolve_binary_document_parser_authority") == 1
    assert "def resolve_binary_document_parser_authority" not in COMPOSITION_SOURCE


# --- caller/endpoint input rejection -------------------------------------------


def test_compose_rejects_non_transport_inputs() -> None:
    with pytest.raises(ValueError):
        compose_worker_isolated_parser_authority(transport=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        compose_worker_isolated_parser_authority(transport=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        compose_worker_isolated_parser_authority(  # type: ignore[call-arg]
            transport=FakeInMemoryTransport(_success_envelope()),
            endpoint="https://evil.example",
        )


def test_install_rejects_invalid_authority() -> None:
    with pytest.raises(ValueError):
        boundary.install_worker_isolated_parser_composition(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        boundary.install_worker_isolated_parser_composition(object())  # type: ignore[arg-type]
    assert boundary._WORKER_ISOLATED_PARSER_COMPOSITION is None


def test_hostile_parse_kwargs_still_rejected_on_composed_path() -> None:
    compose_worker_isolated_parser_authority(
        transport=FakeInMemoryTransport(_success_envelope())
    )
    with _worker_runtime():
        with pytest.raises(TypeError):
            parse_binary_document_via_authority(
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
                endpoint="https://evil.example",  # type: ignore[call-arg]
            )
        with pytest.raises(TypeError):
            parse_binary_document_via_authority(
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
                parser="local",  # type: ignore[call-arg]
            )


def test_request_metadata_cannot_install_or_select_composition() -> None:
    spy = _CoreParserSpy()
    with _worker_runtime(), mock.patch.object(boundary, "extract_binary_document", spy):
        with pytest.raises(DocumentParserAuthorityUnavailable):
            parse_binary_document_via_authority(
                name="../../etc/worker.pdf",
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
            )
        with pytest.raises(TypeError):
            parse_binary_document_via_authority(
                name=VALID_NAME,
                media_type=VALID_MEDIA,
                payload=VALID_PAYLOAD,
                runtime_mode="cpython",  # type: ignore[call-arg]
            )
    assert spy.calls == 0
    assert boundary._WORKER_ISOLATED_PARSER_COMPOSITION is None


# --- AST authority scan: no network/process/endpoint surface --------------------


def _ast_surface(tree: ast.AST) -> tuple[set[str], set[str], set[str]]:
    imported: set[str] = set()
    referenced: set[str] = set()
    parameter_names: set[str] = set()
    for node in ast.walk(tree):
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
    return imported, referenced, parameter_names


def test_composition_module_has_no_network_process_or_endpoint_surface() -> None:
    imported, referenced, parameter_names = _ast_surface(COMPOSITION_TREE)
    assert imported & FORBIDDEN_IMPORT_ROOTS == set()
    assert referenced & FORBIDDEN_REFERENCES == set()
    assert parameter_names & FORBIDDEN_PARAMETER_NAMES == set()
    assert parameter_names <= {"transport", "self"}
    assert "fetch(" not in COMPOSITION_SOURCE
    assert "os.environ" not in COMPOSITION_SOURCE
    assert "httpx" not in COMPOSITION_SOURCE


def test_boundary_changed_surface_stays_off_network_process_and_endpoint() -> None:
    imported, referenced, parameter_names = _ast_surface(BOUNDARY_TREE)
    assert imported & FORBIDDEN_IMPORT_ROOTS == set()
    assert referenced & FORBIDDEN_REFERENCES == set()
    assert parameter_names & FORBIDDEN_PARAMETER_NAMES == set()
    assert "isolated_parser_client" not in BOUNDARY_SOURCE
    assert "IsolatedParserClient" not in BOUNDARY_SOURCE


def test_no_endpoint_credential_or_timeout_literal_appears_on_new_surface() -> None:
    for source in (COMPOSITION_SOURCE,):
        for forbidden in (
            "https://",
            "http://",
            "endpoint=",
            "base_url",
            "API_KEY",
            "password",
            "timeout=",
        ):
            assert forbidden not in source


# --- Chat/Engine still use only the single shared authority entry point ---------


def test_chat_and_engine_call_sites_do_not_touch_the_composition_seam() -> None:
    root = Path(__file__).resolve().parents[3]
    call_sites = [
        root / "apps" / "padiem-chat" / "app" / "binary_documents.py",
        root / "apps" / "padiem-ai-engine" / "app" / "trusted_document_resolver.py",
    ]
    for path in call_sites:
        source = path.read_text(encoding="utf-8")
        assert "parse_binary_document_via_authority" in source
        assert "install_worker_isolated_parser_composition" not in source
        assert "compose_worker_isolated_parser_authority" not in source
        assert "isolated_parser_composition" not in source
        assert "extract_binary_document(" not in source


# --- non-claims: no live binding, no package-root export, no new dependency -----


def test_composition_module_declares_no_live_binding() -> None:
    assert not hasattr(composition_module, "DEFAULT_TRANSPORT")
    assert not hasattr(composition_module, "LIVE_TRANSPORT")
    assert "LIVE_PARSER_SERVICE_BOUND" not in COMPOSITION_SOURCE
    assert "LIVE_NETWORK_CALLS" not in COMPOSITION_SOURCE
    for name in ("base64", "binascii", "json", "re"):
        assert not hasattr(composition_module, name)


def test_package_root_does_not_export_the_composition_symbols() -> None:
    import padiem_ai_core as package_root

    for name in (
        "compose_worker_isolated_parser_authority",
        "reset_worker_isolated_parser_composition",
        "IsolatedParserClient",
        "install_worker_isolated_parser_composition",
    ):
        assert not hasattr(package_root, name)
