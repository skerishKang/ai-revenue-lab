"""#4139 — the production request-port factory for the Windows Resident.

``PADIEM_AGENT_REQUEST_PORT`` is a ``module:factory`` string that the Resident's
own ``BrokerEntry.from_environment()`` imports and calls with no arguments. Until
now the only published factory was
``kagent.local_agent_broker_pairing_handoff_entry:make_request_port`` — the
**non-Production #3140 loopback evidence** port. That port builds a
``BrokerClientPort`` from ``PADIEM_AGENT_BROKER_URL`` and ignores the
``OutboundTransportConfig`` it is handed, while every other outbound call the
Resident makes resolves its authority from ``config.endpoint`` through the pinned
``StdlibPinnedHttpsJsonRequestPort``.

Two independent authorities in one process is the defect this module closes. A
session, heartbeat and poll cross the boundary named by ``config.endpoint``; the
credential-bearing pairing redemption crossed a *second*, separately configured
URL, and without the pinned transport's guarantees — no exact HTTPS/443, no
redirect refusal, no ``no-store``. When the two disagree, the possession proof is
presented at one canonical broker and the session opened at another.

This factory publishes the production shape and adds no transport of its own:

    SECOND_TRANSPORT=0         (delegates to the existing canonical pairing port)
    SECOND_BROKER_ORIGIN=0     (refuses while the two configured origins disagree)
    RAW_DEVICE_CREDENTIAL_LOGGED=0
    PRODUCTION_MUTATION=0

The declared origin is validated *before* any transport is constructed, against
the same rules ``OutboundBrokerEndpoint`` already enforces for ``config.endpoint``
(exact ``https``, an exact host, no URL credentials, port 443, no query or
fragment), so the two values are compared on equal terms. A value that fails is a
bounded ``ContractError``: this factory never falls back to a default broker,
because a defaulted boundary is a boundary no deployment configured.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from .contracts import ContractError

#: The same variable ``kagent.local_agent_resident_process`` reads for the
#: request-port factory. One name, one authority — no second spelling here.
BROKER_URL_ENV = "PADIEM_AGENT_BROKER_URL"

#: The deployment value an operator sets for the Resident's
#: ``PADIEM_AGENT_REQUEST_PORT``.
PRODUCTION_REQUEST_PORT_FACTORY = (
    "kagent.local_agent_broker_production_entry:make_production_request_port"
)

PINNED_HTTPS_PORT = 443
_MAX_URL_CHARS = 2048


def _pinned_broker_origin(value: Any) -> tuple[str, str, int, str]:
    """Validate one broker URL and return its pinned ``(scheme, host, port, path)``.

    Mirrors ``OutboundBrokerEndpoint.__post_init__`` deliberately: the two values
    this module compares are compared on the same terms, so a URL this accepts
    can only ever be one the Resident's own transport configuration could also
    have accepted.
    """

    if not isinstance(value, str) or not value.strip():
        raise ContractError("the canonical broker origin must be a URL")
    url = value.strip()
    if len(url) > _MAX_URL_CHARS:
        raise ContractError("the canonical broker origin URL is too long")
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https":
        raise ContractError("the canonical broker origin must use exact HTTPS")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ContractError("the canonical broker origin must name an exact host and carry no URL credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ContractError("the canonical broker origin port is invalid") from exc
    if port not in (None, PINNED_HTTPS_PORT):
        raise ContractError("the canonical broker origin is restricted to port 443")
    if parsed.query or parsed.fragment:
        raise ContractError("the canonical broker origin must not use query or fragment data")
    path = parsed.path or ""
    if path and (not path.startswith("/") or ".." in path.split("/")):
        raise ContractError("the canonical broker origin path is invalid")
    return "https", parsed.hostname.lower(), PINNED_HTTPS_PORT, path.rstrip("/")


class PinnedBrokerOriginJsonRequestPort:
    """The canonical pairing transport, bound to the one declared Broker origin.

    The transport is the existing
    ``StdlibPinnedHttpsBrokerPairingJsonRequestPort`` — TLS verified, no redirect
    followed, response bounded and required to be JSON. This class contributes
    exactly one thing: on every call it asserts that the ``config`` it is handed
    still names the canonical Broker origin the deployment declared, and refuses
    **before** any bytes leave the process when it does not.
    """

    def __init__(self, *, declared_origin: str, transport: Any = None) -> None:
        self._declared = _pinned_broker_origin(declared_origin)
        if transport is None:
            # Imported lazily so the tray path does not pull the broker client
            # stack in at import time, exactly as the enrollment stack is kept
            # out of ``claw_connect.resident_launch``.
            from .local_agent_broker_pairing_client import (
                StdlibPinnedHttpsBrokerPairingJsonRequestPort,
            )

            transport = StdlibPinnedHttpsBrokerPairingJsonRequestPort()
        if not callable(getattr(transport, "post", None)):
            raise ContractError("the canonical pairing transport must implement post")
        self._transport = transport

    def _assert_one_boundary(self, config: Any) -> None:
        endpoint = getattr(config, "endpoint", None)
        url = getattr(endpoint, "url", None)
        if not isinstance(url, str) or not url.strip():
            raise ContractError("the transport configuration must name the canonical broker endpoint")
        scheme, host, port, path = _pinned_broker_origin(url)
        declared_scheme, declared_host, declared_port, declared_path = self._declared
        if (scheme, host, port) != (declared_scheme, declared_host, declared_port):
            raise ContractError(
                "the transport configuration names a different canonical broker origin"
            )
        # A declared URL only pins a base path when it actually states one; the
        # transport configuration owns the mount point otherwise, so a path-less
        # deployment value cannot silently relocate the pinned transport.
        if declared_path and declared_path != path:
            raise ContractError(
                "the canonical broker base path disagrees with the transport configuration"
            )

    def post(
        self,
        *,
        config: Any,
        operation: Any,
        payload: dict[str, Any],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        self._assert_one_boundary(config)
        return self._transport.post(
            config=config,
            operation=operation,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "production_request_port": True,
            "canonical_broker_origin_pinned": True,
            "broker_origin_configured": True,
            "broker_origin_exposed": False,
            "broker_host_exposed": False,
            "transport": type(self._transport).__name__,
            "transport_reused": True,
            "second_transport": False,
            "second_broker_origin": False,
            "raw_device_credential": False,
            "raw_device_credential_logged": False,
        }


def make_production_request_port(environ: Mapping[str, str] | None = None) -> PinnedBrokerOriginJsonRequestPort:
    """The factory an operator names in ``PADIEM_AGENT_REQUEST_PORT``.

    Called with no arguments by ``BrokerEntry.from_environment()``; the optional
    ``environ`` is for tests and for a caller that already resolved its own
    deployment environment. Nothing is defaulted: a missing or non-pinned value
    refuses here, before the Resident can present a credential at a boundary no
    deployment selected.
    """

    env = os.environ if environ is None else environ
    declared = env.get(BROKER_URL_ENV)
    if not declared:
        raise ContractError("PADIEM_AGENT_BROKER_URL must name the canonical broker origin")
    return PinnedBrokerOriginJsonRequestPort(declared_origin=declared)


PRODUCTION_REQUEST_PORT = True
CANONICAL_TRANSPORT_REUSED = True
DECLARED_ORIGIN_PINNED = True
DEFAULT_BROKER_ORIGIN = False
SECOND_TRANSPORT = False
SECOND_BROKER_ORIGIN = False
TLS_REQUIRED = True
REDIRECT_REFUSED = True
RAW_DEVICE_CREDENTIAL_LOGGED = False
PUBLIC_INBOUND_PORT = False
PRODUCTION_MUTATION = False

__all__ = [
    "BROKER_URL_ENV",
    "CANONICAL_TRANSPORT_REUSED",
    "DECLARED_ORIGIN_PINNED",
    "DEFAULT_BROKER_ORIGIN",
    "PINNED_HTTPS_PORT",
    "PRODUCTION_REQUEST_PORT",
    "PRODUCTION_REQUEST_PORT_FACTORY",
    "PinnedBrokerOriginJsonRequestPort",
    "PUBLIC_INBOUND_PORT",
    "RAW_DEVICE_CREDENTIAL_LOGGED",
    "REDIRECT_REFUSED",
    "SECOND_BROKER_ORIGIN",
    "SECOND_TRANSPORT",
    "TLS_REQUIRED",
    "make_production_request_port",
]
