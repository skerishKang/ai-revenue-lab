"""#4139 — the production Request Port factory must match the canonical Broker.

The first half of this file is a cross-contract check: the client-side operation
map is compared against the *canonical broker source* (the closed
``_DEVICE_HTTP_ROUTES`` set in ``packages/padiem-control-plane``) rather than
against a copy of itself. The second half fixes the `/file-result` wire contract
LOCAL2/CENTRAL integrate against.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from kagent.contracts import ContractError
from kagent.local_agent_control_plane_https import ControlPlaneHttpsOperation
from kagent.local_agent_control_plane_runtime import RuntimeStdlibPinnedHttpsJsonRequestPort
from kagent.local_agent_production_request_port import (
    CANONICAL_DEVICE_ROUTES,
    FILE_RESULT_KIND,
    PRODUCTION_BROKER_AUTHORITY,
    PRODUCTION_BROKER_MOUNT_PATH,
    PRODUCTION_BROKER_OPERATION_PATHS,
    ProductionBrokerFileResultOperation,
    ProductionBrokerOperation,
    ProductionRequestPort,
    build_production_request_port,
    build_production_transport_config,
    canonical_operation_path,
    canonical_session_relative_paths,
    parse_file_result_submission_response,
    production_broker_configuration_contract,
    production_broker_url,
    verified_file_result_payload,
    verify_operation_path_mapping,
)
from kagent.local_agent_secure_transport import OutboundBrokerEndpoint, OutboundTransportMode

_BROKER_DEVICE_HTTP = (
    Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane" / "local_agent_broker_device_http.py"
)


def _canonical_broker_routes() -> tuple[str, ...]:
    """Read the closed route set from the canonical broker source."""

    source = _BROKER_DEVICE_HTTP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_DEVICE_HTTP_ROUTES" for target in node.targets
        ):
            value = node.value
            if isinstance(value, ast.Call):  # frozenset({...})
                value = value.args[0]
            routes = ast.literal_eval(value)
            return tuple(sorted(routes))
    raise AssertionError("canonical broker device route source was not found")


def test_operation_map_matches_canonical_broker_routes():
    canonical = frozenset(_canonical_broker_routes())
    assert frozenset(CANONICAL_DEVICE_ROUTES) == canonical

    mapped = frozenset(PRODUCTION_BROKER_OPERATION_PATHS.values())
    assert mapped <= canonical
    # `/office-part` is the #3580 opt-in byte staging route, not a Windows
    # resident operation, and is the only canonical route without a mapping.
    assert canonical - mapped == {"/office-part"}
    for operation, path in PRODUCTION_BROKER_OPERATION_PATHS.items():
        assert path == f"/{operation.value}"
        assert canonical_operation_path(operation) == path


def test_every_resident_operation_maps_to_an_existing_endpoint():
    assert canonical_session_relative_paths() == {
        "acknowledge": "/acknowledge",
        "file-result": "/file-result",
        "heartbeat": "/heartbeat",
        "material": "/material",
        "poll": "/poll",
        "reconcile": "/reconcile",
        "session": "/session",
    }
    assert canonical_operation_path(ProductionBrokerOperation.SESSION) == "/session"
    assert canonical_operation_path(ProductionBrokerOperation.HEARTBEAT) == "/heartbeat"
    with pytest.raises(ContractError):
        canonical_operation_path("not-an-operation")


def test_authority_and_url_are_pinned_to_the_existing_public_origin():
    assert PRODUCTION_BROKER_AUTHORITY == "chat.padiem.net"
    assert production_broker_url() == f"https://{PRODUCTION_BROKER_AUTHORITY}{PRODUCTION_BROKER_MOUNT_PATH}"
    assert production_broker_url("/api/claw/connector/gateway/") == production_broker_url()
    for bad_mount in ("connector/gateway", "/api/../etc", ""):
        with pytest.raises(ContractError):
            production_broker_url(bad_mount)


def test_factory_reuses_the_existing_pinned_port_and_config_contract():
    port = build_production_request_port()
    assert isinstance(port, RuntimeStdlibPinnedHttpsJsonRequestPort)
    assert isinstance(port, ProductionRequestPort)

    config = build_production_transport_config()
    assert config.endpoint.mode is OutboundTransportMode.HTTPS_LONG_POLL
    assert config.endpoint.url == production_broker_url()
    safe = config.safe_dict()
    assert safe["endpoint"]["host"] == PRODUCTION_BROKER_AUTHORITY
    assert safe["endpoint"]["port"] == 443
    assert safe["caller_endpoint_override"] is False
    assert safe["public_inbound_port"] is False

    mount = PRODUCTION_BROKER_MOUNT_PATH
    observed = verify_operation_path_mapping(port, config)
    assert observed == {
        operation: f"{mount}{route}" for operation, route in canonical_session_relative_paths().items()
    }
    assert all(path.startswith(mount) for path in observed.values())


def test_port_refuses_any_authority_that_is_not_the_pinned_production_one():
    port = build_production_request_port()
    foreign = build_production_transport_config()
    object.__setattr__(
        foreign,
        "endpoint",
        OutboundBrokerEndpoint(
            endpoint_ref="endpoint.foreign",
            url="https://attacker.example",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
    )
    with pytest.raises(ContractError):
        verify_operation_path_mapping(port, foreign)
    # The port itself trusts the config it is handed (that is the existing
    # design); the authority is pinned where the config is built and where the
    # deployed integration verifies the mapping.
    assert port._path(build_production_transport_config(), ControlPlaneHttpsOperation.POLL)[0] == PRODUCTION_BROKER_AUTHORITY


def test_file_result_payload_is_the_exact_closed_upload_contract():
    content = "오늘 PC의 실제 테스트 파일입니다.\n"
    payload = verified_file_result_payload(
        session_id="session.1",
        binding_ref="binding.1",
        credential_b64="Y3JlZA==",
        command_id="command.1",
        revision_ref="revision.1",
        request_id="request.1",
        evidence_ref="evidence.1",
        content_utf8=content,
        now="2026-10-15T00:00:00Z",
    )
    assert set(payload) == {
        "session_id", "binding_ref", "credential_b64", "command_id", "revision_ref",
        "request_id", "evidence_ref", "kind", "content_utf8", "content_sha256", "now",
    }
    assert payload["kind"] == FILE_RESULT_KIND
    assert payload["content_sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()

    pending = verified_file_result_payload(
        session_id="session.1", binding_ref="binding.1", credential_b64="Y3JlZA==",
        command_id="command.1", revision_ref="revision.1", request_id="request.1",
        evidence_ref="evidence.1", content_utf8=None, now="2026-10-15T00:00:00Z",
    )
    assert pending["content_utf8"] is None and pending["content_sha256"] is None

    other = verified_file_result_payload(
        session_id="session.1", binding_ref="binding.1", credential_b64="Y3JlZA==",
        command_id="command.1", revision_ref="revision.1", request_id="request.1",
        evidence_ref="evidence.1", content_utf8=None, now="2026-10-15T00:00:00Z",
        kind="other",
    )
    assert other["kind"] == "other"

    with pytest.raises(ContractError):
        verified_file_result_payload(
            session_id="session.1", binding_ref="binding.1", credential_b64="Y3JlZA==",
            command_id="command.1", revision_ref="revision.1", request_id="request.1",
            evidence_ref="evidence.1", content_utf8="text", now="2026-10-15T00:00:00Z",
            kind="other",
        )
    with pytest.raises(ContractError):
        verified_file_result_payload(
            session_id="session.1", binding_ref="binding.1", credential_b64="Y3JlZA==",
            command_id="command.1", revision_ref="revision.1", request_id="request.1",
            evidence_ref="evidence.1", content_utf8="bad\x00text", now="2026-10-15T00:00:00Z",
        )
    with pytest.raises(ContractError):
        verified_file_result_payload(
            session_id="session.1", binding_ref="binding.1", credential_b64="",
            command_id="command.1", revision_ref="revision.1", request_id="request.1",
            evidence_ref="evidence.1", content_utf8=None, now="2026-10-15T00:00:00Z",
        )


def test_file_result_response_parse_is_closed():
    stored = {
        "command_id": "command.1",
        "binding_ref": "binding.1",
        "kind": FILE_RESULT_KIND,
        "content_bytes": 12,
        "content_sha256": "a" * 64,
        "stored_at": "2026-10-15T00:00:00Z",
        "raw_device_credential": False,
    }
    assert parse_file_result_submission_response(
        {"ok": True, "file_result": stored}, expected_command_id="command.1"
    ) == stored
    with pytest.raises(ContractError):
        parse_file_result_submission_response(
            {"ok": False, "error": {"code": "local_agent_file_result_refused", "message": "no"}},
            expected_command_id="command.1",
        )
    for broken in (
        {"ok": True, "file_result": {**stored, "command_id": "other"}},
        {"ok": True, "file_result": {**stored, "extra": 1}},
        {"ok": True, "file_result": {key: value for key, value in stored.items() if key != "kind"}},
        {"ok": True, "file_result": {**stored, "raw_device_credential": True}},
    ):
        with pytest.raises(ContractError):
            parse_file_result_submission_response(broken, expected_command_id="command.1")


def test_configuration_contract_reports_the_exact_integration_facts():
    contract = production_broker_configuration_contract()
    assert contract["authority"] == PRODUCTION_BROKER_AUTHORITY
    assert contract["broker_url"] == production_broker_url()
    assert contract["port"] == 443 and contract["method"] == "POST"
    assert contract["caller_authority_override"] is False
    assert contract["unmapped_canonical_routes"] == ["/office-part"]
    assert contract["production_mount_deployed"] is False
    assert contract["production_connection_verified"] is False
    assert contract["file_result_max_content_bytes"] == 768
    assert contract["operation_paths"] == canonical_session_relative_paths()

    endpoint = build_production_transport_config().endpoint
    assert endpoint.safe_dict()["host"] == PRODUCTION_BROKER_AUTHORITY
    # The one operation the base enum does not carry is still an existing route.
    assert canonical_operation_path(ProductionBrokerFileResultOperation.FILE_RESULT) == "/file-result"
