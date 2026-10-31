"""COM2-only connector gateway composition.

The edge must strip client-supplied proof headers and sign its own TLS evidence.
The Cloudflare edge signer and staged deployment are separate work.
"""
from __future__ import annotations

from starlette.websockets import WebSocket

from .canonical_connector_gateway_source_composition import (
    CONNECTOR_GATEWAY_WSS_PATH,
    create_review_only_connector_gateway_app,
)
from .local_service_bridge import HttpRpcBinding, _require_secret


_IDENTITY_METHODS = frozenset({
    "resolve_connector_enrollment_consent_for_device",
    "bind_connector_enrollment_challenge",
    "authorize_connector_enrollment_redeem",
})
_BROKER_METHODS = frozenset({
    "gateway_bootstrap_rpc", "get_enrollment_binding",
    "verify_enrollment_bootstrap", "redeem_enrollment", "revoke_binding",
})


class LoopbackRpcBinding(HttpRpcBinding):
    """Binding-shaped service-proof RPC, restricted to a fixed COM2 port."""

    def __init__(
        self, *, port: int, secret: str, methods: frozenset[str], client=None,
        sign_request_id: bool = True,
    ):
        if port not in (8799, 8802):
            raise ValueError("unapproved COM2 RPC port")
        self._origin = f"http://127.0.0.1:{port}"
        self._secret = _require_secret(secret, name="COM2 RPC service secret")
        self._client = client
        self._timeout = 8.0
        self._methods = methods
        self._sign_request_id = bool(sign_request_id)

    def __getattr__(self, method):
        if method not in self._methods:
            raise AttributeError(method)
        return super().__getattr__(method)


class _VerifiedIngress:
    async def verify(self, websocket):
        # Only the wrapping ASGI application can put this marker into scope.
        return websocket.scope.get("com2_edge_verified") is self


def create_com2_gateway(*, verifier, identity_binding, broker_binding):
    """Create a host-only ASGI application; verify before accepting any socket."""
    ingress = _VerifiedIngress()
    inner = create_review_only_connector_gateway_app(
        identity_binding=identity_binding, broker_binding=broker_binding,
        trusted_tls_ingress=ingress, source_test_authorized=True,
    )

    async def gateway(scope, receive, send):
        if scope["type"] != "websocket" or scope.get("path") != CONNECTOR_GATEWAY_WSS_PATH:
            await inner(scope, receive, send)
            return
        websocket = WebSocket(scope, receive=receive, send=send)
        # Duplicate proof headers are ambiguous at the trust boundary.
        names = [name.lower() for name, _ in scope.get("headers", ())]
        proof_names = (b"x-padiem-edge-at", b"x-padiem-edge-id",
                       b"x-padiem-edge-tls", b"x-padiem-edge-proof")
        if (scope.get("query_string") or any(names.count(name) != 1 for name in proof_names)
            or (scope.get("com2_edge_verified_verifier") is not verifier and not verifier.verify(method="GET", path=scope["path"], headers=websocket.headers))):
            await websocket.close(code=1008)
            return
        trusted_scope = dict(scope)
        trusted_scope["scheme"] = "wss"
        trusted_scope["com2_edge_verified"] = ingress
        await inner(trusted_scope, receive, send)

    return gateway
