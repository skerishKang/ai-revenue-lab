from __future__ import annotations

from typing import Any

from workers import DurableObject, Response, WorkerEntrypoint

from padiem_control_plane.connector_connect_ticket import ConnectorConnectTicketAuthority
from padiem_control_plane.contracts import ControlPlaneContractError

from google_oauth_durable_store import CloudflareDurableGoogleOAuthStore
from google_oauth_ingress_runtime import (
    CloudflareGoogleOAuthTokenExchangePort,
    GoogleOAuthIngressConfig,
    GoogleOAuthIngressRuntime,
    _decode_key_secret,
)
from google_oauth_webcrypto_sealer import GoogleOAuthWebCryptoSealer


_AUTHORITY_REF_FALLBACK = "control-plane.google-oauth.production.v1"
_CONNECT_KEYS = frozenset({"connect_ticket"})
_CALLBACK_KEYS = frozenset({"state_ref", "authorization_code", "provider_error"})


def _closed_payload(payload: Any, keys: frozenset[str], field_name: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != keys:
        raise ControlPlaneContractError(
            "invalid_google_oauth_ingress",
            f"{field_name} must contain exactly the reviewed fields",
        )
    return payload


def _required_env(env: Any, name: str) -> str:
    value = getattr(env, name, None)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"required Google OAuth Worker binding {name} is missing")
    return value.strip()


def _safe_rpc_error(error: ControlPlaneContractError) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": error.code,
            "message": "Google connector request was rejected",
        },
    }


class GoogleOAuthDurableObject(DurableObject):
    """Private SQLite Durable Object owning Google OAuth state and credentials."""

    def __init__(self, ctx, env):
        super().__init__(ctx, env)
        self._store = CloudflareDurableGoogleOAuthStore(ctx.storage)
        self._runtime = GoogleOAuthIngressRuntime(
            store=self._store,
            sealer=GoogleOAuthWebCryptoSealer(
                key_secret_b64url=_required_env(env, "GOOGLE_OAUTH_SEAL_KEY"),
            ),
            ticket_authority=ConnectorConnectTicketAuthority(
                signing_key=_decode_key_secret(
                    _required_env(env, "GOOGLE_CONNECT_TICKET_KEY"),
                    "GOOGLE_CONNECT_TICKET_KEY",
                )
            ),
            config=GoogleOAuthIngressConfig(
                client_id=_required_env(env, "GOOGLE_OAUTH_CLIENT_ID"),
                client_secret=_required_env(env, "GOOGLE_OAUTH_CLIENT_SECRET"),
                redirect_uri=_required_env(env, "GOOGLE_OAUTH_REDIRECT_URI"),
            ),
            token_exchange=CloudflareGoogleOAuthTokenExchangePort(),
        )

    async def begin_connect(self, payload: dict) -> dict:
        try:
            payload = _closed_payload(payload, _CONNECT_KEYS, "Google OAuth connect RPC")
            receipt = await self._runtime.begin(connect_ticket=payload["connect_ticket"])
            return {"ok": True, "authorization": receipt.safe_dict()}
        except ControlPlaneContractError as exc:
            return _safe_rpc_error(exc)

    async def complete_callback(self, payload: dict) -> dict:
        try:
            payload = _closed_payload(payload, _CALLBACK_KEYS, "Google OAuth callback RPC")
            receipt = await self._runtime.complete_callback(
                state_ref=payload["state_ref"],
                authorization_code=payload["authorization_code"],
                provider_error=payload["provider_error"],
            )
            return {"ok": True, "connection": receipt.safe_dict()}
        except ControlPlaneContractError as exc:
            return _safe_rpc_error(exc)

    async def fetch(self, request):
        del request
        return Response("Not Found", status=404, headers={"cache-control": "no-store"})


class Default(WorkerEntrypoint):
    """Private Service Binding gateway; no public HTTP route is configured."""

    def _authority_ref(self) -> str:
        value = getattr(self.env, "GOOGLE_OAUTH_AUTHORITY_REF", _AUTHORITY_REF_FALLBACK)
        if not isinstance(value, str) or value != _AUTHORITY_REF_FALLBACK:
            raise RuntimeError("Google OAuth authority ref must match the reviewed production authority")
        return value

    def _stub(self):
        namespace = self.env.GOOGLE_OAUTH_STATE
        object_id = namespace.idFromName(self._authority_ref())
        return namespace.get(object_id)

    async def begin_connect(self, payload: dict) -> dict:
        return await self._stub().begin_connect(payload)

    async def complete_callback(self, payload: dict) -> dict:
        return await self._stub().complete_callback(payload)

    async def fetch(self, request):
        del request
        return Response("Not Found", status=404, headers={"cache-control": "no-store"})


GOOGLE_OAUTH_PRIVATE_STATE_WORKER_SOURCE = True
SQLITE_BACKED_DURABLE_OBJECT = True
PRIVATE_SERVICE_BINDING_RPC = True
PUBLIC_FETCH = False
CONNECT_TICKET_RAW_RPC_RESPONSE = False
AUTHORIZATION_CODE_RAW_RPC_RESPONSE = False
ACCESS_TOKEN_RAW_RPC_RESPONSE = False
REFRESH_TOKEN_RAW_RPC_RESPONSE = False
LOCAL_AGENT_INGRESS_CHANGED = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
