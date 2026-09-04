from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from typing import Any, Callable

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_auth import StateBackedLocalAgentBindingAuthenticator
from padiem_control_plane.local_agent_broker_http import (
    MAX_LOCAL_AGENT_HTTP_BODY_BYTES,
    LocalAgentBrokerHttpHandler,
    LocalAgentBrokerHttpResponse,
    TrustedLocalAgentHttpAuthContext,
)

_DEVICE_HTTP_ROUTES = frozenset({"/session", "/poll", "/material", "/heartbeat", "/acknowledge"})
_ENVELOPE_KEYS = frozenset({"method", "route", "content_type", "body_b64", "tls_verified"})
_MAX_BODY_B64_CHARS = ((MAX_LOCAL_AGENT_HTTP_BODY_BYTES + 2) // 3) * 4


def _closed_mapping(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != keys:
        raise ValueError(f"{label} schema mismatch")
    return value


def _error(status: int, code: str, message: str) -> LocalAgentBrokerHttpResponse:
    return LocalAgentBrokerHttpResponse(
        status=status,
        body={"ok": False, "error": {"code": code, "message": message}},
    )


def _structured_response(response: LocalAgentBrokerHttpResponse) -> dict[str, Any]:
    return {
        "status": response.status,
        "headers": response.headers,
        "body": response.body,
    }


def _decode_body(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("device HTTP body_b64 must be non-empty text")
    if len(value) > _MAX_BODY_B64_CHARS:
        raise OverflowError("device HTTP body exceeds size bound")
    try:
        body = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("device HTTP body_b64 is invalid") from exc
    if not body:
        raise ValueError("device HTTP body must be non-empty")
    if len(body) > MAX_LOCAL_AGENT_HTTP_BODY_BYTES:
        raise OverflowError("device HTTP body exceeds size bound")
    return body


def _credential(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("credential_b64 must be non-empty text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("credential_b64 is invalid") from exc
    if not decoded:
        raise ValueError("credential_b64 must decode to non-empty bytes")
    return decoded


def _content_type_is_json(value: Any) -> bool:
    return isinstance(value, str) and value.split(";", 1)[0].strip().lower() == "application/json"


class LocalAgentBrokerDeviceHttpService:
    """Private service-bound composition for the five outbound Local Agent routes.

    Public callers never provide the trusted auth context. The service derives
    account/workspace identity from the canonical persisted device binding after
    verifying the raw credential with the existing broker authority, then invokes
    the already-closed M2e HTTP handler.
    """

    def __init__(
        self,
        *,
        state_port,
        pepper: bytes,
        authority_ref: str,
        rpc_factory: Callable[[], Any],
        http_state,
        material_resolver,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(rpc_factory):
            raise ValueError("rpc_factory must be callable")
        if not callable(clock) and clock is not None:
            raise ValueError("clock must be callable")
        self._authenticator = StateBackedLocalAgentBindingAuthenticator(
            pepper=pepper,
            authority_ref=authority_ref,
            state_port=state_port,
        )
        self._rpc_factory = rpc_factory
        self._http_state = http_state
        self._material_resolver = material_resolver
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _server_now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("device HTTP server clock must return timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def handle(self, envelope: dict[str, Any]) -> dict[str, Any]:
        try:
            envelope = _closed_mapping(envelope, _ENVELOPE_KEYS, "device HTTP envelope")
        except (TypeError, ValueError):
            return _structured_response(_error(400, "local_agent_edge_invalid_envelope", "Local Agent edge request envelope is invalid"))

        if envelope["tls_verified"] is not True:
            return _structured_response(_error(403, "local_agent_http_tls_required", "trusted TLS termination is required"))
        if envelope["method"] != "POST":
            return _structured_response(_error(405, "local_agent_http_post_required", "Local Agent broker routes accept POST only"))
        route = envelope["route"]
        if not isinstance(route, str) or route not in _DEVICE_HTTP_ROUTES:
            return _structured_response(_error(404, "local_agent_http_route_not_found", "Local Agent broker route was not found"))
        if not _content_type_is_json(envelope["content_type"]):
            return _structured_response(_error(415, "local_agent_http_json_required", "Local Agent broker routes require application/json"))

        try:
            body = _decode_body(envelope["body_b64"])
        except OverflowError:
            return _structured_response(_error(413, "local_agent_http_body_too_large", "Local Agent broker request body exceeds size bound"))
        except (TypeError, ValueError):
            return _structured_response(_error(400, "local_agent_http_invalid_json", "Local Agent broker request body is invalid"))

        try:
            decoded = json.loads(body.decode("utf-8"))
            if type(decoded) is not dict:
                raise ValueError("body must be a JSON object")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return _structured_response(_error(400, "local_agent_http_invalid_json", "Local Agent broker request body is invalid"))

        try:
            binding_ref = decoded["binding_ref"]
            credential = _credential(decoded["credential_b64"])
            server_now = self._server_now()
            binding = self._authenticator.authenticate(
                binding_ref=binding_ref,
                credential=credential,
                now=server_now,
            )
        except (ControlPlaneContractError, KeyError, TypeError, ValueError):
            return _structured_response(
                _error(401, "local_agent_http_auth_required", "authenticated Local Agent broker access is required")
            )

        auth = TrustedLocalAgentHttpAuthContext(
            principal_ref=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            authenticated=True,
            tls_verified=True,
        )
        handler = LocalAgentBrokerHttpHandler(
            rpc=self._rpc_factory(),
            state=self._http_state,
            material_resolver=self._material_resolver,
            clock=lambda: server_now,
        )
        response = handler.handle(
            method=envelope["method"],
            route=route,
            content_type=envelope["content_type"],
            body=body,
            auth=auth,
        )
        return _structured_response(response)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "device_http_routes": sorted(_DEVICE_HTTP_ROUTES),
            "private_service_boundary": True,
            "canonical_binding_auth_reused": True,
            "self_asserted_account_workspace_authority": False,
            "m2e_handler_reused": True,
            "second_credential_verifier": False,
            "admin_broker_rpc_public": False,
            "raw_device_secret_logged": False,
            "production_route_configured": False,
            "production_deployment": False,
            "production_ready": False,
        }


DEVICE_HTTP_ROUTES = tuple(sorted(_DEVICE_HTTP_ROUTES))
PRIVATE_SERVICE_BOUNDARY = True
CANONICAL_BINDING_AUTH_REUSED = True
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
M2E_HANDLER_REUSED = True
SECOND_CREDENTIAL_VERIFIER = False
ADMIN_BROKER_RPC_PUBLIC = False
RAW_DEVICE_SECRET_LOGGED = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_READY = False
