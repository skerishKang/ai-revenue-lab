"""Canonical production request-port factory for the Windows Resident.

Reuses the existing pinned HTTPS transport. The Broker TXT result is sent
through ControlPlaneHttpsOperation.TEXT_RESULT, never a second /file-result route.
No network call is made by importing or constructing this factory.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from .contracts import ContractError
from .local_agent_control_plane_https import ControlPlaneHttpsOperation
from .local_agent_control_plane_runtime import (
    ControlPlaneRuntimeHttpsOperation,
    RuntimeStdlibPinnedHttpsJsonRequestPort,
)
from .local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
)

PRODUCTION_BROKER_AUTHORITY = "chat.padiem.net"
PRODUCTION_BROKER_MOUNT_PATH = "/api/claw/connector/gateway"
PRODUCTION_BROKER_OPERATION_PATHS = {
    "session": "/session",
    "poll": "/poll",
    "material": "/material",
    "acknowledge": "/acknowledge",
    "reconcile": "/reconcile",
    "heartbeat": "/heartbeat",
    "text-result": "/text-result",
}
# A configured endpoint is not evidence that the edge is deployed or usable.
PRODUCTION_BROKER_MOUNT_DEPLOYED = False
PRODUCTION_BROKER_CONNECTION_VERIFIED = False
PRODUCTION_READY = False


def production_broker_url(mount_path: str | None = None) -> str:
    mount = PRODUCTION_BROKER_MOUNT_PATH if mount_path is None else mount_path
    if (not isinstance(mount, str) or not mount.startswith("/")
            or "//" in mount or "?" in mount or "#" in mount
            or ".." in mount.split("/")):
        raise ContractError("production broker mount must be a safe absolute path")
    return f"https://{PRODUCTION_BROKER_AUTHORITY}{mount.rstrip('/')}"


def build_production_broker_endpoint(
    *, endpoint_ref: str = "endpoint.padiem.local-agent-broker.production.v1",
    mount_path: str | None = None,
) -> OutboundBrokerEndpoint:
    if not isinstance(endpoint_ref, str) or not endpoint_ref.strip():
        raise ContractError("endpoint_ref must be nonempty")
    url = production_broker_url(mount_path)
    if urlsplit(url).hostname != PRODUCTION_BROKER_AUTHORITY:
        raise ContractError("production broker authority mismatch")
    return OutboundBrokerEndpoint(
        endpoint_ref=endpoint_ref, url=url,
        mode=OutboundTransportMode.HTTPS_LONG_POLL,
    )


def build_production_transport_config(
    *, endpoint_ref: str = "endpoint.padiem.local-agent-broker.production.v1",
    mount_path: str | None = None, heartbeat_seconds: int = 30,
    poll_timeout_seconds: int = 30, max_response_bytes: int = 262_144,
) -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=build_production_broker_endpoint(
            endpoint_ref=endpoint_ref, mount_path=mount_path,
        ),
        heartbeat_seconds=heartbeat_seconds,
        poll_timeout_seconds=poll_timeout_seconds,
        max_response_bytes=max_response_bytes,
    )


def build_production_request_port() -> RuntimeStdlibPinnedHttpsJsonRequestPort:
    return RuntimeStdlibPinnedHttpsJsonRequestPort()


def verify_operation_path_mapping(
    port: RuntimeStdlibPinnedHttpsJsonRequestPort,
    config: OutboundTransportConfig,
) -> dict[str, str]:
    """Validate host, TLS port, and actual transport route without I/O."""
    if not isinstance(port, RuntimeStdlibPinnedHttpsJsonRequestPort):
        raise ContractError("production port must reuse pinned HTTPS transport")
    if not isinstance(config, OutboundTransportConfig):
        raise ContractError("expected outbound transport config")
    actual = {}
    operations = {
        "session": ControlPlaneHttpsOperation.OPEN_SESSION,
        "poll": ControlPlaneHttpsOperation.POLL,
        "material": ControlPlaneHttpsOperation.MATERIAL,
        "acknowledge": ControlPlaneHttpsOperation.ACKNOWLEDGE,
        "reconcile": ControlPlaneHttpsOperation.RECONCILE,
        "heartbeat": ControlPlaneRuntimeHttpsOperation.HEARTBEAT,
        "text-result": ControlPlaneHttpsOperation.TEXT_RESULT,
    }
    mount = urlsplit(config.endpoint.url).path.rstrip("/")
    for name, operation in operations.items():
        host, number, path = port._path(config, operation)
        expected = mount + PRODUCTION_BROKER_OPERATION_PATHS[name]
        if host != PRODUCTION_BROKER_AUTHORITY or number != 443 or path != expected:
            raise ContractError(f"production transport route mismatch: {name}")
        actual[name] = path
    return actual
