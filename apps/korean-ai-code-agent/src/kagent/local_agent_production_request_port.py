"""#4139 — the production Request Port factory for the Windows Local Agent.

This module is the *client-side wiring description* for the already-existing
canonical Broker. It deliberately creates no transport, no TLS policy, no
broker, no account system and no credential store:

* the transport is the existing
  :class:`~kagent.local_agent_control_plane_https.StdlibPinnedHttpsJsonRequestPort`
  (TLS via ``ssl.create_default_context``, redirects refused, JSON only,
  bounded request/response, no caller endpoint override) and the existing
  :class:`~kagent.local_agent_control_plane_runtime.RuntimeStdlibPinnedHttpsJsonRequestPort`
  which adds the canonical ``/heartbeat`` route;
* the broker is the existing canonical device HTTP surface
  (``packages/padiem-control-plane/local_agent_broker_device_http.py``,
  ``DEVICE_HTTP_ROUTES``);
* the authority is the existing PADIEM public origin
  (``https://chat.padiem.net``), the same origin the Claw web product and the
  Claw Connect package already use.

What this module adds is the missing *production* pieces LOCAL2/CENTRAL need to
mount the real Windows connection:

1. an importable module:factory (``build_production_request_port`` /
   ``build_production_transport_config``) instead of every caller hand-rolling
   ``OutboundTransportConfig(OutboundBrokerEndpoint(...))``;
2. the explicit operation -> existing endpoint mapping
   (``PRODUCTION_BROKER_OPERATION_PATHS``) with a runtime guard that proves the
   port really addresses the canonical route for every operation;
3. the authority / Broker URL / configuration contract as data
   (``production_broker_configuration_contract``) so a reviewer can compare the
   intended authority against what is actually deployed;
4. the closed wire contract for the one new canonical device route introduced
   for the first PC TXT read, ``/file-result`` (see #4139 / #4687), including a
   client-side guard that produces the exact payload the broker accepts.

Deployment state is *not* claimed here: the production route attachment of the
edge Worker is still ``PRODUCTION_ROUTE_CONFIGURED = False`` in the canonical
broker source, so ``PRODUCTION_BROKER_MOUNT_DEPLOYED`` stays ``False`` until
CENTRAL verifies the deployed mount. The factory pins the authority and refuses
any caller-supplied authority; only the mount path is a declared, validated
part of the contract.
"""

from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Any
from urllib.parse import urlsplit

from .contracts import ContractError
from .local_agent_control_plane_https import ControlPlaneHttpsOperation
from .local_agent_control_plane_runtime import RuntimeStdlibPinnedHttpsJsonRequestPort
from .local_agent_secure_transport import OutboundBrokerEndpoint, OutboundTransportConfig, OutboundTransportMode

#: The existing PADIEM public origin (the same one `apps/claw-connect` opens and
#: the same one the production workers are attached to). The Broker authority is
#: never taken from a caller, a query parameter or the environment.
PRODUCTION_BROKER_AUTHORITY = "chat.padiem.net"

#: The mount the canonical device edge serves the closed device routes under.
#: #4139 (2026-10-14 KST) observed the operational attempt at
#: `https://chat.padiem.net/api/claw/connector/gateway/session` returning HTTP
#: 404 because the route was not deployed yet; the path is therefore the declared
#: contract value, not a verified deployment fact.
PRODUCTION_BROKER_MOUNT_PATH = "/api/claw/connector/gateway"

#: The exact, closed canonical device route surface. Mirrored from the canonical
#: broker source; `tests/test_local_agent_production_request_port.py` re-reads
#: that source so this copy cannot silently drift.
CANONICAL_DEVICE_ROUTES = (
    "/acknowledge",
    "/file-result",
    "/heartbeat",
    "/material",
    "/office-part",
    "/poll",
    "/reconcile",
    "/session",
)

_MAX_CONTENT_BYTES = 768
_MAX_REQUEST_BYTES = 262_144
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


class ProductionBrokerFileResultOperation(str, Enum):
    """The one canonical device route the base operation enum does not carry."""

    FILE_RESULT = "file-result"


class ProductionBrokerOperation(str, Enum):
    """Every operation the production Windows resident addresses."""

    SESSION = ControlPlaneHttpsOperation.OPEN_SESSION.value
    POLL = ControlPlaneHttpsOperation.POLL.value
    MATERIAL = ControlPlaneHttpsOperation.MATERIAL.value
    ACKNOWLEDGE = ControlPlaneHttpsOperation.ACKNOWLEDGE.value
    RECONCILE = ControlPlaneHttpsOperation.RECONCILE.value
    HEARTBEAT = "heartbeat"
    FILE_RESULT = ProductionBrokerFileResultOperation.FILE_RESULT.value


#: operation -> the existing canonical endpoint path. Derived from the closed
#: `CANONICAL_DEVICE_ROUTES` set, so an operation that has no canonical route
#: cannot be mapped at all.
PRODUCTION_BROKER_OPERATION_PATHS: dict[ProductionBrokerOperation, str] = {
    operation: f"/{operation.value}" for operation in ProductionBrokerOperation
}

_UNMAPPED_ROUTES = tuple(
    route for route in CANONICAL_DEVICE_ROUTES if route not in PRODUCTION_BROKER_OPERATION_PATHS.values()
)

FILE_RESULT_CONTRACT_VERSION = "claw-verified-file-result.v1"
FILE_RESULT_KIND = "file_read_text"
FILE_RESULT_OTHER_KIND = "other"


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ContractError(f"{field_name} must be an exact lowercase SHA-256 digest")
    return value


def canonical_operation_path(operation: ProductionBrokerOperation) -> str:
    """The existing endpoint of one operation, or a fail-closed refusal."""

    try:
        mapped = PRODUCTION_BROKER_OPERATION_PATHS[ProductionBrokerOperation(operation)]
    except (KeyError, ValueError) as exc:
        raise ContractError("operation has no canonical broker endpoint") from exc
    if mapped not in CANONICAL_DEVICE_ROUTES:
        raise ContractError("operation maps to a path outside the canonical device route surface")
    return mapped


def canonical_session_relative_paths() -> dict[str, str]:
    """Oldest-first copy of the whole mapping for reporting/tests."""

    return {operation.value: path for operation, path in sorted(PRODUCTION_BROKER_OPERATION_PATHS.items(), key=lambda item: item[0].value)}


def production_broker_url(mount_path: str | None = None) -> str:
    """The pinned production Broker URL (authority fixed, mount declared)."""

    mount = PRODUCTION_BROKER_MOUNT_PATH if mount_path is None else mount_path
    if not isinstance(mount, str) or not mount.startswith("/") or ".." in mount.split("/"):
        raise ContractError("production broker mount path must be an absolute, traversal-free path")
    trimmed = mount.rstrip("/")
    return f"https://{PRODUCTION_BROKER_AUTHORITY}{trimmed}"


class ProductionRequestPort(RuntimeStdlibPinnedHttpsJsonRequestPort):
    """The existing pinned HTTPS source, widened by the two canonical routes."""

    def _path(self, config: OutboundTransportConfig, operation: Any) -> tuple[str, int, str]:
        if operation is ProductionBrokerFileResultOperation.FILE_RESULT:
            # Reuse the existing pinned authority/HTTPS validation, then swap
            # only the canonical route segment for the /file-result route.
            host, port, base_path = super()._path(config, ControlPlaneHttpsOperation.POLL)
            base = base_path[: -len(ControlPlaneHttpsOperation.POLL.value) - 1]
            return host, port, f"{base}{canonical_operation_path(ProductionBrokerOperation.FILE_RESULT)}"
        return super()._path(config, operation)


def build_production_broker_endpoint(*, endpoint_ref: str, mount_path: str | None = None) -> OutboundBrokerEndpoint:
    """The pinned production endpoint. No caller may name the authority."""

    endpoint_ref = _safe_ref(endpoint_ref, "endpoint_ref")
    url = production_broker_url(mount_path)
    parsed = urlsplit(url)
    if parsed.hostname != PRODUCTION_BROKER_AUTHORITY:
        raise ContractError("production broker endpoint escaped the pinned production authority")
    return OutboundBrokerEndpoint(endpoint_ref=endpoint_ref, url=url, mode=OutboundTransportMode.HTTPS_LONG_POLL)


def build_production_transport_config(
    *,
    endpoint_ref: str = "endpoint.padiem.local-agent-broker.production.v1",
    mount_path: str | None = None,
    heartbeat_seconds: int = 30,
    poll_timeout_seconds: int = 30,
    max_response_bytes: int = _MAX_REQUEST_BYTES,
) -> OutboundTransportConfig:
    """The production outbound configuration contract for the Windows resident.

    Bounds are the canonical ones: heartbeat 5..300s, poll timeout 1..60s,
    response bound 1KiB..1MiB, TLS required, no public inbound port. The caller
    chooses only the bounded timing values; the authority and mount are the
    pinned contract.
    """

    return OutboundTransportConfig(
        endpoint=build_production_broker_endpoint(endpoint_ref=endpoint_ref, mount_path=mount_path),
        heartbeat_seconds=heartbeat_seconds,
        poll_timeout_seconds=poll_timeout_seconds,
        max_response_bytes=max_response_bytes,
    )


def build_production_request_port() -> ProductionRequestPort:
    """The importable factory LOCAL2/CENTRAL mount for the production connection."""

    return ProductionRequestPort()


def verify_operation_path_mapping(
    port: ProductionRequestPort,
    config: OutboundTransportConfig,
) -> dict[str, str]:
    """Prove the port addresses the canonical endpoint for every operation.

    Calls the existing (private) path resolver of the reused port instead of
    re-implementing it, so the verification cannot drift from what is actually
    requested. No request is sent: this only compares the resolved request path
    (pinned mount + canonical route) and the resolved HTTPS/443 authority.
    """

    if not isinstance(port, RuntimeStdlibPinnedHttpsJsonRequestPort):
        raise ContractError("port must be the existing pinned stdlib HTTPS request port")
    if not isinstance(config, OutboundTransportConfig):
        raise ContractError("config must be OutboundTransportConfig")
    observed: dict[str, str] = {}
    for operation in ProductionBrokerOperation:
        if operation is ProductionBrokerOperation.FILE_RESULT:
            host, port_number, path = port._path(  # noqa: SLF001 - verified contract, not behaviour
                config, ProductionBrokerFileResultOperation.FILE_RESULT
            )
        else:
            host, port_number, path = port._path(  # noqa: SLF001 - verified contract, not behaviour
                config,
                ControlPlaneHttpsOperation(operation.value)
                if operation is not ProductionBrokerOperation.HEARTBEAT
                else _heartbeat_operation(),
            )
        if host != PRODUCTION_BROKER_AUTHORITY or port_number != 443:
            raise ContractError("production request port escaped the pinned HTTPS/443 authority")
        mount = (urlsplit(config.endpoint.url).path or "/").rstrip("/")
        route = canonical_operation_path(operation)
        if path != f"{mount}{route}":
            raise ContractError(f"production request port path mismatch for {operation.value}")
        observed[operation.value] = path
    return observed


def _heartbeat_operation() -> Any:
    # Imported lazily so this module keeps working when the runtime extension is
    # the only place that knows the heartbeat operation.
    from .local_agent_control_plane_runtime import ControlPlaneRuntimeHttpsOperation

    return ControlPlaneRuntimeHttpsOperation.HEARTBEAT


def verified_file_result_payload(
    *,
    session_id: str,
    binding_ref: str,
    credential_b64: str,
    command_id: str,
    revision_ref: str,
    request_id: str,
    evidence_ref: str,
    content_utf8: str | None,
    now: str,
    kind: str = FILE_RESULT_KIND,
) -> dict[str, Any]:
    """The exact closed upload payload for the canonical `/file-result` route.

    The caller resolves `credential_b64` from the existing protected device
    credential store at request time exactly like the transport does; this
    function never reads, stores or logs credential material.

    `content_utf8` is the real Windows READ result. `None` submits a
    declaration only (a text-file read whose verified content is not readable
    yet); the broker then answers the Claw read as *pending* instead of
    consuming the conversation message slot. Non-text-file commands are declared
    with `kind="other"`.
    """

    if not isinstance(credential_b64, str) or not credential_b64:
        raise ContractError("credential_b64 must be non-empty text")
    kind = _safe_ref(kind, "kind")
    if kind not in {FILE_RESULT_KIND, FILE_RESULT_OTHER_KIND}:
        raise ContractError("file result kind must be file_read_text or other")
    content_digest: str | None = None
    if content_utf8 is not None:
        if kind != FILE_RESULT_KIND:
            raise ContractError("only a text-file read result may carry content")
        if type(content_utf8) is not str:
            raise ContractError("file result content must be text or null")
        raw = content_utf8.encode("utf-8")
        if len(raw) > _MAX_CONTENT_BYTES:
            raise ContractError("file result content exceeds the bounded text size")
        if any(ord(character) < 32 and character not in "\n\r\t" for character in content_utf8):
            raise ContractError("file result content must not contain control characters")
        content_digest = hashlib.sha256(raw).hexdigest()
    payload = {
        "session_id": _safe_ref(session_id, "session_id"),
        "binding_ref": _safe_ref(binding_ref, "binding_ref"),
        "credential_b64": credential_b64,
        "command_id": _safe_ref(command_id, "command_id"),
        "revision_ref": _safe_ref(revision_ref, "revision_ref"),
        "request_id": _safe_ref(request_id, "request_id"),
        "evidence_ref": _safe_ref(evidence_ref, "evidence_ref"),
        "kind": kind,
        "content_utf8": content_utf8,
        "content_sha256": content_digest,
        "now": now,
    }
    if not isinstance(now, str) or not now:
        raise ContractError("now must be ISO-8601 text")
    return payload


def parse_file_result_submission_response(response: Any, *, expected_command_id: str) -> dict[str, Any]:
    """Closed parse of the canonical `/file-result` response envelope."""

    if type(response) is not dict or type(response.get("ok")) is not bool:
        raise ContractError("file result submission response is invalid")
    if response["ok"] is False:
        error = response.get("error")
        if type(error) is not dict or set(error) != {"code", "message"}:
            raise ContractError("file result submission error response schema mismatch")
        code = _safe_ref(error["code"], "broker_error_code")
        raise ContractError(f"broker refused the file result submission: {code}")
    if set(response) != {"ok", "file_result"}:
        raise ContractError("file result submission success response schema mismatch")
    stored = response["file_result"]
    if type(stored) is not dict or set(stored) != {
        "command_id", "binding_ref", "kind", "content_bytes", "content_sha256",
        "stored_at", "raw_device_credential",
    }:
        raise ContractError("file result submission receipt schema mismatch")
    if _safe_ref(stored["command_id"], "command_id") != _safe_ref(expected_command_id, "command_id"):
        raise ContractError("file result submission receipt command mismatch")
    if stored["kind"] not in {FILE_RESULT_KIND, FILE_RESULT_OTHER_KIND}:
        raise ContractError("file result submission receipt kind is invalid")
    if stored["content_bytes"] is not None:
        if isinstance(stored["content_bytes"], bool) or not isinstance(stored["content_bytes"], int) or stored["content_bytes"] < 0:
            raise ContractError("file result submission receipt byte length is invalid")
    if stored["content_sha256"] is not None:
        _digest(stored["content_sha256"], "content_sha256")
    if stored["raw_device_credential"] is not False:
        raise ContractError("file result submission receipt must not carry device credential material")
    return stored


def production_broker_configuration_contract() -> dict[str, Any]:
    """The exact config contract handed to LOCAL2/CENTRAL for integration."""

    return {
        "contract_version": "padiem-local-agent-production-broker.v1",
        "authority": PRODUCTION_BROKER_AUTHORITY,
        "broker_url": production_broker_url(),
        "mount_path": PRODUCTION_BROKER_MOUNT_PATH,
        "scheme": "https",
        "port": 443,
        "method": "POST",
        "request_content_type": "application/json",
        "transport_source": "stdlib_https_long_poll",
        "tls_default_context": True,
        "redirect_auto_follow": False,
        "caller_authority_override": False,
        "caller_endpoint_override": False,
        "operation_paths": canonical_session_relative_paths(),
        "unmapped_canonical_routes": list(_UNMAPPED_ROUTES),
        "file_result_contract_version": FILE_RESULT_CONTRACT_VERSION,
        "file_result_kind": FILE_RESULT_KIND,
        "file_result_max_content_bytes": _MAX_CONTENT_BYTES,
        "heartbeat_seconds_bounds": (5, 300),
        "poll_timeout_seconds_bounds": (1, 60),
        "max_response_bytes_bounds": (1024, 1048576),
        "raw_device_credential_source": "windows_dpapi_current_user",
        "raw_device_credential_in_payload_contract": False,
        "production_mount_deployed": PRODUCTION_BROKER_MOUNT_DEPLOYED,
        "production_connection_verified": PRODUCTION_BROKER_CONNECTION_VERIFIED,
    }


#: The declared mount is a contract value. The deployment and a real Windows
#: round trip are separate facts; neither is claimed by this module.
PRODUCTION_BROKER_MOUNT_DEPLOYED = False
PRODUCTION_BROKER_CONNECTION_VERIFIED = False
PRODUCTION_BROKER_CONFIGURED = True
EXISTING_REQUEST_PORT_REUSED = True
SECOND_HTTP_OR_TLS_STACK = False
SECOND_BROKER_AUTHORITY = False
SECOND_ACCOUNT_OR_AUTH_SYSTEM = False
RAW_DEVICE_CREDENTIAL_IN_SAFE_STATE = False
PUBLIC_INBOUND_PORT = False
REAL_REMOTE_EXECUTION = False
PRODUCTION_READY = False
