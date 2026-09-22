from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from workers import DurableObject, Response, WorkerEntrypoint

from padiem_control_plane.connector_connect_ticket import ConnectorConnectTicketAuthority
from padiem_control_plane.contracts import ControlPlaneContractError

from google_oauth_access_lease import (
    CloudflareGoogleOAuthRefreshPort,
    GoogleOAuthAccessLeaseRuntime,
)
from google_oauth_persisted_store import CloudflareDurableGoogleOAuthStore
from google_oauth_ingress_runtime import (
    CloudflareGoogleOAuthTokenExchangePort,
    GoogleOAuthIngressConfig,
    GoogleOAuthIngressRuntime,
    _decode_key_secret,
)
from google_oauth_random import production_google_oauth_token
from google_oauth_webcrypto_sealer import GoogleOAuthWebCryptoSealer


_AUTHORITY_REF_FALLBACK = "control-plane.google-oauth.production.v1"
_CONNECT_KEYS = frozenset({"connect_ticket"})
_CALLBACK_KEYS = frozenset({"state_ref", "authorization_code", "provider_error"})
_ACCESS_LEASE_KEYS = frozenset({"binding_ref", "connector_id"})
_WORKSPACE_CONNECTOR_STATE_KEYS = frozenset({"workspace_ref"})
# #2010: the Calendar credential-presence read accepts exactly the same closed
# payload. The connector itself is fixed in code, never supplied by the caller.
_WORKSPACE_CALENDAR_CONNECTOR_STATE_KEYS = frozenset({"workspace_ref"})
WORKSPACE_CALENDAR_CONNECTOR_ID = "google-calendar"


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
        sealer = GoogleOAuthWebCryptoSealer(
            key_secret_b64url=_required_env(env, "GOOGLE_OAUTH_SEAL_KEY"),
        )
        config = GoogleOAuthIngressConfig(
            client_id=_required_env(env, "GOOGLE_OAUTH_CLIENT_ID"),
            client_secret=_required_env(env, "GOOGLE_OAUTH_CLIENT_SECRET"),
            redirect_uri=_required_env(env, "GOOGLE_OAUTH_REDIRECT_URI"),
        )
        self._runtime = GoogleOAuthIngressRuntime(
            store=self._store,
            sealer=sealer,
            ticket_authority=ConnectorConnectTicketAuthority(
                signing_key=_decode_key_secret(
                    _required_env(env, "GOOGLE_CONNECT_TICKET_KEY"),
                    "GOOGLE_CONNECT_TICKET_KEY",
                )
            ),
            config=config,
            token_exchange=CloudflareGoogleOAuthTokenExchangePort(),
            random_token=production_google_oauth_token,
        )
        self._access_lease_runtime = GoogleOAuthAccessLeaseRuntime(
            store=self._store,
            sealer=sealer,
            config=config,
            refresh_port=CloudflareGoogleOAuthRefreshPort(),
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

    async def issue_access_lease(self, payload: dict) -> dict:
        """Return one short-lived access credential over private RPC only.

        The long-lived refresh credential is loaded, unsealed and refreshed
        inside this Durable Object. It never appears in the RPC response.
        """
        try:
            payload = _closed_payload(
                payload,
                _ACCESS_LEASE_KEYS,
                "Google OAuth access-lease RPC",
            )
            lease = await self._access_lease_runtime.issue(
                binding_ref=payload["binding_ref"],
                connector_id=payload["connector_id"],
            )
            return {"ok": True, "lease": lease.to_private_rpc_dict()}
        except ControlPlaneContractError as exc:
            return _safe_rpc_error(exc)

    async def workspace_connector_state(self, payload: dict) -> dict:
        """Return bounded, identity-free Google connector truth for one workspace.

        Phase B-0 (#2830) read slice. The payload is closed to exactly
        ``workspace_ref``. The response carries only connector_id / state /
        usable / expires_present / ambiguous. No binding_ref, actor_ref,
        account_ref, workspace_ref echo, scopes or sealed material is returned,
        no refresh credential is unsealed and no access lease is issued.
        """
        try:
            payload = _closed_payload(
                payload,
                _WORKSPACE_CONNECTOR_STATE_KEYS,
                "Google OAuth workspace connector-state RPC",
            )
            states = self._store.list_workspace_connector_state(
                workspace_ref=payload["workspace_ref"],
                now=datetime.now(timezone.utc),
            )
            return {
                "ok": True,
                "connectors": [state.to_bounded_dict() for state in states],
            }
        except ControlPlaneContractError as exc:
            return _safe_rpc_error(exc)

    async def workspace_calendar_connector_state(self, payload: dict) -> dict:
        """Return bounded, identity-free Calendar credential presence (#2010).

        Pre-connect observation authority: before any Calendar OAuth connect is
        approved, this read answers exactly one question per workspace - does an
        existing reviewed ``google-calendar`` durable credential exist - without
        mutating anything.

        The payload is closed to exactly ``workspace_ref``. The connector is
        fixed in code to the reviewed ``google-calendar`` OAuth authority, so a
        caller can never select a connector, scope, binding_ref, actor_ref,
        account_ref or provider identifier. The response reuses the existing
        bounded workspace-state projection: connector_id / state / usable /
        expires_present / ambiguous only. No binding_ref, actor_ref, account_ref,
        workspace_ref echo, scopes or sealed material is returned, no refresh
        credential is unsealed and no access lease is issued.
        """
        try:
            payload = _closed_payload(
                payload,
                _WORKSPACE_CALENDAR_CONNECTOR_STATE_KEYS,
                "Google OAuth Calendar connector-presence RPC",
            )
            states = self._store.list_workspace_connector_state(
                workspace_ref=payload["workspace_ref"],
                now=datetime.now(timezone.utc),
                connector_ids=(WORKSPACE_CALENDAR_CONNECTOR_ID,),
            )
            return {
                "ok": True,
                "connectors": [state.to_bounded_dict() for state in states],
            }
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

    async def issue_access_lease(self, payload: dict) -> dict:
        return await self._stub().issue_access_lease(payload)

    async def workspace_connector_state(self, payload: dict) -> dict:
        return await self._stub().workspace_connector_state(payload)

    async def workspace_calendar_connector_state(self, payload: dict) -> dict:
        return await self._stub().workspace_calendar_connector_state(payload)

    async def fetch(self, request):
        del request
        return Response("Not Found", status=404, headers={"cache-control": "no-store"})


GOOGLE_OAUTH_PRIVATE_STATE_WORKER_SOURCE = True
SQLITE_BACKED_DURABLE_OBJECT = True
PRIVATE_SERVICE_BINDING_RPC = True
PUBLIC_FETCH = False
PRODUCTION_RANDOM_SOURCE_HARDENED = True
CONNECT_TICKET_RAW_RPC_RESPONSE = False
AUTHORIZATION_CODE_RAW_RPC_RESPONSE = False
# Kept for onboarding-RPC compatibility. The access token is exposed only by
# the dedicated private issue_access_lease RPC and never by public fetch or
# onboarding callback projections.
ACCESS_TOKEN_RAW_RPC_RESPONSE = False
ACCESS_TOKEN_PRIVATE_LEASE_RPC = True
REFRESH_TOKEN_RAW_RPC_RESPONSE = False
LOCAL_AGENT_INGRESS_CHANGED = False
PRODUCTION_ROUTE_CONFIGURED = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
# Phase B-0 (#2830): workspace-scoped connector truth read RPC.
# Private service-binding RPC only; never reachable through public fetch().
WORKSPACE_CONNECTOR_STATE_RPC = True
WORKSPACE_CONNECTOR_STATE_PUBLIC_ROUTE = False
WORKSPACE_CONNECTOR_STATE_PAYLOAD_CLOSED = True
WORKSPACE_CONNECTOR_STATE_LEAKS_BINDING_REF = False
WORKSPACE_CONNECTOR_STATE_LEAKS_ACTOR_REF = False
WORKSPACE_CONNECTOR_STATE_LEAKS_ACCOUNT_REF = False
WORKSPACE_CONNECTOR_STATE_ECHOES_WORKSPACE_REF = False
WORKSPACE_CONNECTOR_STATE_LEAKS_SCOPES = False
WORKSPACE_CONNECTOR_STATE_LEAKS_SEALED_CREDENTIAL = False
WORKSPACE_CONNECTOR_STATE_UNSEALS_REFRESH_TOKEN = False
WORKSPACE_CONNECTOR_STATE_ISSUES_ACCESS_LEASE = False
WORKSPACE_CONNECTOR_STATE_WRITE_AUTHORITY = False
WORKSPACE_CONNECTOR_STATE_DUPLICATE_POLICY = "ambiguous_fail_closed"
# #2010 Calendar existing-credential presence read (source-only slice).
# Same private authority and same bounded projection; the connector is fixed to
# google-calendar and neither refs nor tokens are ever exported.
CALENDAR_CREDENTIAL_PRESENCE_READ_RPC = True
CALENDAR_CREDENTIAL_PRESENCE_READ_CONNECTOR = "google-calendar"
CALENDAR_CREDENTIAL_PRESENCE_READ_PAYLOAD_CLOSED = True
CALENDAR_CREDENTIAL_PRESENCE_READ_PUBLIC_ROUTE = False
CALENDAR_CREDENTIAL_PRESENCE_READ_CONNECTOR_FIXED_IN_CODE = True
CALENDAR_CREDENTIAL_EXISTENCE_READ = True
CALENDAR_REF_OUTPUT = False
CALENDAR_TOKEN_OUTPUT = False
CALENDAR_CREDENTIAL_READ_UNSEALS_REFRESH_TOKEN = False
CALENDAR_CREDENTIAL_READ_ISSUES_ACCESS_LEASE = False
CALENDAR_CREDENTIAL_READ_WRITE_AUTHORITY = False
DEFAULT_WORKSPACE_STATUS_INCLUDES_CALENDAR = False
B62_PUBLIC_CALENDAR_TRUTH_WIDENED = False
