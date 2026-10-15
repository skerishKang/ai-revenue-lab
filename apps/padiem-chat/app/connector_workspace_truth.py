"""#2830 B-1B: private connector workspace truth composition (B62 Chat).

Composition owner is **PADIEM_CHAT / B62**. This module is the only place that
joins the two private Control Plane authorities, and it joins them in exactly
one direction:

    trusted B62 server session_id
        -> IDENTITY_AUTHORITY_SERVICE.resolve_connector_workspace
        -> canonical workspace_ref
        -> CONTROL_PLANE_GOOGLE_OAUTH.workspace_connector_state
        -> bounded internal connector truth

Authority ownership is never mixed:

* the Identity Authority resolves *who the workspace is*, and never calls
  Google OAuth — ``IDENTITY_TO_GOOGLE_OAUTH_DIRECT_BINDING=NO``;
* the Google OAuth authority resolves *whether the connector is usable*, and
  never resolves identity;
* Padiem Chat composes the two results and nothing else.

No new workspace authority and no new credential authority is introduced.
B-1A (``resolve_connector_workspace``) resolves the workspace once. The existing
B-0 (``workspace_connector_state``) RPC supplies Gmail / Drive truth, and the
existing dedicated ``workspace_calendar_connector_state`` RPC supplies Calendar
truth for that same trusted workspace. Neither authority is reimplemented.

The output is bounded to the reviewed B-0 state contract —
``connector_id / state / usable / expires_present / ambiguous`` — and is rebuilt
key by key, so an upstream response can never widen the projection. No
``binding_ref``, ``actor_ref``, ``account_ref``, ``workspace_ref``, scope or
sealed credential material is ever projected, and no access lease is issued.

This slice is PRIVATE COMPOSITION ONLY. It does not mutate
``/api/connectors/status`` (B-1C owns that) and it does not activate a
Production Service Binding (``wrangler.toml`` is untouched).
"""

from __future__ import annotations

import inspect
from typing import Any

from .control_plane_identity import IdentityBridgeError

# B-1B consumes two existing bounded Google OAuth reads for one trusted
# workspace: the default Gmail / Drive B-0 RPC plus the dedicated Calendar
# presence RPC. Telegram and Slack remain outside this authority.
_DEFAULT_WORKSPACE_TRUTH_CONNECTORS = frozenset({"gmail", "google-drive"})
_CALENDAR_WORKSPACE_TRUTH_CONNECTORS = frozenset({"google-calendar"})
_B66_GOOGLE_DRIVE_FILE_CONNECTOR = "b66-google-drive-file"
_B66_GOOGLE_DRIVE_FULL_CONNECTOR = "b66-google-drive-full"
_B66_GOOGLE_DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
_B66_GOOGLE_DRIVE_FULL_SCOPE = "https://www.googleapis.com/auth/drive"
_B66_GOOGLE_DRIVE_OIDC_SCOPES = ("openid", "profile", "email")
_B66_DRIVE_SCOPES = {
    _B66_GOOGLE_DRIVE_FILE_CONNECTOR: (_B66_GOOGLE_DRIVE_FILE_SCOPE,) + _B66_GOOGLE_DRIVE_OIDC_SCOPES,
    _B66_GOOGLE_DRIVE_FULL_CONNECTOR: (_B66_GOOGLE_DRIVE_FULL_SCOPE,) + _B66_GOOGLE_DRIVE_OIDC_SCOPES,
}
_BEGIN_CONNECT_KEYS = frozenset({"connect_ticket"})
_AUTHORIZATION_KEYS = frozenset({"authorization_url", "connector_id", "expires_at"})
_B66_SELECTION_ABSENT_KEYS = frozenset({"status", "connector_id", "workspace_ref"})
_B66_SELECTION_RESOLVED_KEYS = frozenset({
    "status", "connector_id", "workspace_ref", "binding_ref", "actor_ref",
    "provider_subject", "provider_email",
})
_B66_CONNECTION_KEYS = frozenset({
    "binding_ref", "connector_id", "actor_ref", "account_ref", "workspace_ref",
    "scopes", "connected_at", "expires_at", "refresh_token_persisted_sealed",
    "access_token_discarded", "raw_authorization_code", "raw_access_token",
    "raw_refresh_token", "raw_client_secret", "verified_destination_subject",
    "verified_destination_account",
})
REVIEWED_WORKSPACE_TRUTH_CONNECTORS = (
    _DEFAULT_WORKSPACE_TRUTH_CONNECTORS | _CALENDAR_WORKSPACE_TRUTH_CONNECTORS
)
_REVIEWED_WORKSPACE_TRUTH_CONNECTORS = (
    _DEFAULT_WORKSPACE_TRUTH_CONNECTORS | _CALENDAR_WORKSPACE_TRUTH_CONNECTORS
)

# The B-0 bounded state contract. Anything else is a malformed response.
_CONNECTOR_STATE_KEYS = frozenset(
    {"connector_id", "state", "usable", "expires_present", "ambiguous"}
)
_CONNECTOR_STATES = frozenset({"connected", "not_connected", "ambiguous"})

_GOOGLE_OAUTH_UNAVAILABLE = "connector_workspace_truth_unavailable"
_GOOGLE_OAUTH_INVALID = "connector_workspace_truth_invalid"
_NO_CANONICAL_WORKSPACE = "canonical_connector_workspace_not_resolved"
_INVALID_SESSION = "canonical_connector_session_invalid"

# Identity failures cross this private composition boundary only after being
# reclassified into provenance-tagged internal codes. This prevents a Google
# OAuth/provider error that happens to reuse the same upstream code string from
# being mistaken for an identity-authority failure by the public projection.
_IDENTITY_ERROR_TO_COMPOSITION_CODE = {
    "canonical_auth_session_not_found": "identity_workspace_session_not_found",
    "inactive_auth_session": "identity_workspace_session_inactive",
    "connector_context_session_mismatch": "identity_workspace_session_mismatch",
    "invalid_identity_authority": "identity_workspace_session_reference_invalid",
    "control_plane_identity_unavailable": "identity_workspace_service_unavailable",
    "control_plane_rpc_invalid": "identity_workspace_rpc_invalid",
    "invalid_identity_authority_rpc": "identity_workspace_rpc_invalid",
    "identity_authority_storage_error": "identity_workspace_storage_unavailable",
    "connector_context_storage_error": "identity_workspace_context_storage_unavailable",
    "invalid_connector_context": "identity_workspace_context_invalid",
    "connector_context_product_mismatch": "identity_workspace_context_product_mismatch",
}

_UNAVAILABLE_MESSAGE = "Connector workspace truth is unavailable."
_INVALID_MESSAGE = "Connector workspace truth returned invalid data."


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        converted = dict(value)
    except (TypeError, ValueError):
        return None
    return converted


def _unavailable(code: str = _GOOGLE_OAUTH_UNAVAILABLE) -> IdentityBridgeError:
    return IdentityBridgeError(503, code, _UNAVAILABLE_MESSAGE)


def _identity_failure(exc: IdentityBridgeError) -> IdentityBridgeError:
    return IdentityBridgeError(
        exc.status_code,
        _IDENTITY_ERROR_TO_COMPOSITION_CODE.get(
            exc.code, "identity_workspace_unclassified"
        ),
        _UNAVAILABLE_MESSAGE,
    )


def _invalid() -> IdentityBridgeError:
    return IdentityBridgeError(503, _GOOGLE_OAUTH_INVALID, _INVALID_MESSAGE)


def _bounded_connector(
    value: Any,
    *,
    allowed_connector_ids: frozenset[str],
) -> dict[str, Any]:
    """Validate one state row and rebuild it from the reviewed keys only.

    The B-0 canonical semantics are enforced as two exact equivalences:

        ``usable == (state == "connected")``
        ``ambiguous == (state == "ambiguous")``

    so the three reviewed states are total and mutually exclusive, and
    ``ambiguous`` is never promoted to ``connected``. Any other combination —
    including ``connected`` with ``usable=False``, ``not_connected`` with
    ``usable=True``, or ``ambiguous`` with ``ambiguous=False`` — is malformed
    and fails closed.
    """

    row = _as_dict(value)
    if row is None or set(row) != _CONNECTOR_STATE_KEYS:
        raise _invalid()
    connector_id = row["connector_id"]
    state = row["state"]
    usable = row["usable"]
    expires_present = row["expires_present"]
    ambiguous = row["ambiguous"]

    if not isinstance(connector_id, str) or not connector_id:
        raise _invalid()
    if state not in _CONNECTOR_STATES:
        raise _invalid()
    if (
        not isinstance(usable, bool)
        or not isinstance(expires_present, bool)
        or not isinstance(ambiguous, bool)
    ):
        raise _invalid()
    # Scope lock: each private RPC has its own exact reviewed connector set.
    if connector_id not in allowed_connector_ids:
        raise _invalid()
    # B-0 canonical state semantics. The three reviewed states are total and
    # mutually exclusive, so both derived flags are fully determined by
    # ``state``. A row that disagrees with either equivalence is malformed and
    # fails closed:
    #
    #   connected      -> usable=True,  ambiguous=False
    #   not_connected  -> usable=False, ambiguous=False
    #   ambiguous      -> usable=False, ambiguous=True
    #
    # This also keeps ambiguity from ever being promoted to connected, because
    # ``ambiguous=True`` is only consistent with ``state="ambiguous"``.
    if usable != (state == "connected"):
        raise _invalid()
    if ambiguous != (state == "ambiguous"):
        raise _invalid()

    return {
        "connector_id": connector_id,
        "state": state,
        "usable": usable,
        "expires_present": expires_present,
        "ambiguous": ambiguous,
    }


class CloudflareGoogleOAuthWorkspaceTruth:
    """B62 adapter over the private Control Plane Google OAuth Service Binding.

    Calls exactly one reviewed RPC — ``workspace_connector_state`` — with a
    payload closed to ``workspace_ref``. The binding is supplied by trusted
    Worker composition, never by a request, and an absent binding makes every
    call fail closed.
    """

    def __init__(self, binding: Any) -> None:
        if binding is None:
            raise ValueError("Google OAuth Service Binding is required")
        self._binding = binding

    async def workspace_connector_state(
        self,
        *,
        workspace_ref: str,
    ) -> tuple[dict[str, Any], ...]:
        method = getattr(self._binding, "workspace_connector_state", None)
        if not callable(method):
            raise _unavailable()
        try:
            result = _as_dict(
                await _maybe_await(method({"workspace_ref": workspace_ref}))
            )
        except IdentityBridgeError:
            raise
        except Exception as exc:  # noqa: BLE001 - never leak a driver error
            raise _unavailable() from exc

        if result is None or not isinstance(result.get("ok"), bool):
            raise _invalid()
        if result["ok"] is False:
            if set(result) != {"ok", "error"}:
                raise _invalid()
            error = _as_dict(result.get("error"))
            if (
                error is None
                or set(error) != {"code", "message"}
                or not isinstance(error.get("code"), str)
            ):
                raise _invalid()
            # Only the reviewed code crosses the boundary; the upstream message
            # is dropped so nothing internal can be echoed outward.
            raise IdentityBridgeError(503, error["code"], _UNAVAILABLE_MESSAGE)
        if set(result) != {"ok", "connectors"}:
            raise _invalid()
        connectors = result["connectors"]
        if not isinstance(connectors, list):
            raise _invalid()
        return tuple(
            _bounded_connector(
                row,
                allowed_connector_ids=_DEFAULT_WORKSPACE_TRUTH_CONNECTORS,
            )
            for row in connectors
        )

    async def workspace_calendar_connector_state(
        self,
        *,
        workspace_ref: str,
    ) -> tuple[dict[str, Any], ...]:
        """Read the existing dedicated, identity-free Calendar presence RPC."""

        method = getattr(self._binding, "workspace_calendar_connector_state", None)
        if not callable(method):
            raise _unavailable()
        try:
            result = _as_dict(
                await _maybe_await(method({"workspace_ref": workspace_ref}))
            )
        except IdentityBridgeError:
            raise
        except Exception as exc:  # noqa: BLE001 - never leak a driver error
            raise _unavailable() from exc

        if result is None or not isinstance(result.get("ok"), bool):
            raise _invalid()
        if result["ok"] is False:
            if set(result) != {"ok", "error"}:
                raise _invalid()
            error = _as_dict(result.get("error"))
            if (
                error is None
                or set(error) != {"code", "message"}
                or not isinstance(error.get("code"), str)
            ):
                raise _invalid()
            raise IdentityBridgeError(503, error["code"], _UNAVAILABLE_MESSAGE)
        if set(result) != {"ok", "connectors"}:
            raise _invalid()
        connectors = result["connectors"]
        if not isinstance(connectors, list) or len(connectors) != 1:
            raise _invalid()
        return (
            _bounded_connector(
                connectors[0],
                allowed_connector_ids=_CALENDAR_WORKSPACE_TRUTH_CONNECTORS,
            ),
        )

    async def disconnect_drive(self, *, workspace_ref: str) -> bool:
        """Forward a trusted workspace-only revocation to the canonical OAuth authority.

        No credential, account, scope or provider token can be supplied by the browser.
        """
        method = getattr(self._binding, "disconnect_drive", None)
        if not callable(method):
            raise _unavailable()
        try:
            result = _as_dict(await _maybe_await(method({"workspace_ref": workspace_ref})))
        except Exception as exc:
            raise _unavailable() from exc
        if result is None or not isinstance(result.get("ok"), bool):
            raise _invalid()
        if result["ok"] is False:
            if set(result) != {"ok", "error"}:
                raise _invalid()
            raise _unavailable()
        if set(result) != {"ok", "revoked"} or type(result["revoked"]) is not bool:
            raise _invalid()
        return result["revoked"]

    async def begin_b66_drive_connect(
        self,
        *,
        connect_ticket: str,
        connector_id: str = _B66_GOOGLE_DRIVE_FILE_CONNECTOR,
    ) -> dict[str, Any]:
        """Start a server-issued B66 Drive-file ticket over private RPC."""

        if connector_id not in _B66_DRIVE_SCOPES:
            raise _invalid()
        if not isinstance(connect_ticket, str) or not connect_ticket or len(connect_ticket) > 24_576:
            raise _invalid()
        method = getattr(self._binding, "begin_connect", None)
        if not callable(method):
            raise _unavailable()
        try:
            result = _as_dict(
                await _maybe_await(method({"connect_ticket": connect_ticket}))
            )
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise _unavailable() from exc
        if result is None or result.get("ok") is not True:
            raise _unavailable()
        if set(result) != {"ok", "authorization"}:
            raise _invalid()
        authorization = _as_dict(result.get("authorization"))
        if authorization is None or set(authorization) != _AUTHORIZATION_KEYS:
            raise _invalid()
        if any(not isinstance(authorization.get(key), str) or not authorization.get(key) for key in _AUTHORIZATION_KEYS):
            raise _invalid()
        if authorization["connector_id"] != connector_id:
            raise _invalid()
        return {
            "authorization_url": authorization["authorization_url"],
            "connector_id": authorization["connector_id"],
            "expires_at": authorization["expires_at"],
        }

    async def begin_b66_drive_full_connect(self, *, connect_ticket: str) -> dict[str, Any]:
        """Start a server-issued B66 full-Drive ticket over private RPC."""

        return await self.begin_b66_drive_connect(
            connect_ticket=connect_ticket,
            connector_id=_B66_GOOGLE_DRIVE_FULL_CONNECTOR,
        )

    async def complete_b66_drive_callback(
        self,
        *,
        state_ref: str,
        authorization_code: str | None,
        provider_error: str | None,
        connector_id: str = _B66_GOOGLE_DRIVE_FILE_CONNECTOR,
    ) -> dict[str, Any]:
        """Complete one B66 Drive callback over private CP RPC."""

        if connector_id not in _B66_DRIVE_SCOPES:
            raise _invalid()
        if not isinstance(state_ref, str) or not state_ref:
            raise _invalid()
        method = getattr(self._binding, "complete_callback", None)
        if not callable(method):
            raise _unavailable()
        try:
            result = _as_dict(
                await _maybe_await(
                    method({
                        "state_ref": state_ref,
                        "authorization_code": authorization_code,
                        "provider_error": provider_error,
                    })
                )
            )
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise _unavailable() from exc
        if result is None or result.get("ok") is not True:
            raise _unavailable()
        if set(result) != {"ok", "connection"}:
            raise _invalid()
        connection = _as_dict(result.get("connection"))
        if connection is None or set(connection) != _B66_CONNECTION_KEYS:
            raise _invalid()
        if connection.get("connector_id") != connector_id:
            raise _invalid()
        if connection.get("scopes") != list(_B66_DRIVE_SCOPES[connector_id]):
            raise _invalid()
        if connection.get("refresh_token_persisted_sealed") is not True:
            raise _invalid()
        if connection.get("access_token_discarded") is not True:
            raise _invalid()
        if connection.get("raw_authorization_code") is not False:
            raise _invalid()
        if connection.get("verified_destination_subject") is None:
            raise _invalid()
        if connection.get("verified_destination_account") is None:
            raise _invalid()
        return dict(connection)

    async def complete_b66_drive_full_callback(
        self,
        *,
        state_ref: str,
        authorization_code: str | None,
        provider_error: str | None,
    ) -> dict[str, Any]:
        """Complete one B66 full-Drive callback over private CP RPC."""

        return await self.complete_b66_drive_callback(
            state_ref=state_ref,
            authorization_code=authorization_code,
            provider_error=provider_error,
            connector_id=_B66_GOOGLE_DRIVE_FULL_CONNECTOR,
        )

    async def select_b66_drive_binding(
        self,
        *,
        workspace_ref: str,
        connector_id: str = _B66_GOOGLE_DRIVE_FILE_CONNECTOR,
        binding_method: str = "select_b66_drive_binding",
    ) -> dict[str, Any]:
        """Read a trusted workspace's B66 Drive binding selection."""

        if connector_id not in _B66_DRIVE_SCOPES:
            raise _invalid()
        if not isinstance(workspace_ref, str) or not workspace_ref:
            raise _invalid()
        method = getattr(self._binding, binding_method, None)
        if not callable(method):
            raise _unavailable()
        try:
            result = _as_dict(
                await _maybe_await(method({"workspace_ref": workspace_ref}))
            )
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise _unavailable() from exc
        if result is None or result.get("ok") is not True:
            raise _unavailable()
        if set(result) != {"ok", "selection"}:
            raise _invalid()
        selection = _as_dict(result.get("selection"))
        if selection is None:
            raise _invalid()
        keys = set(selection)
        status = selection.get("status")
        if keys == _B66_SELECTION_ABSENT_KEYS:
            if status != "not_connected" or selection.get("connector_id") != connector_id:
                raise _invalid()
            if selection.get("workspace_ref") != workspace_ref:
                raise _invalid()
        elif keys == _B66_SELECTION_RESOLVED_KEYS:
            if status != "resolved" or selection.get("connector_id") != connector_id:
                raise _invalid()
            if any(
                not isinstance(selection.get(key), str) or not selection.get(key)
                for key in ("workspace_ref", "binding_ref", "actor_ref", "provider_subject")
            ):
                raise _invalid()
            if selection.get("workspace_ref") != workspace_ref:
                raise _invalid()
            provider_email = selection.get("provider_email")
            if provider_email is not None and (
                not isinstance(provider_email, str) or "@" not in provider_email or len(provider_email) > 320
            ):
                raise _invalid()
        else:
            raise _invalid()
        return selection

    async def select_b66_drive_full_binding(self, *, workspace_ref: str) -> dict[str, Any]:
        """Read a trusted workspace's B66 full-Drive binding selection."""

        return await self.select_b66_drive_binding(
            workspace_ref=workspace_ref,
            connector_id=_B66_GOOGLE_DRIVE_FULL_CONNECTOR,
            binding_method="select_b66_drive_full_binding",
        )

    async def disconnect_b66_drive(
        self,
        *,
        workspace_ref: str,
        binding_method: str = "disconnect_b66_drive",
    ) -> bool:
        """Revoke only the trusted workspace's B66 Drive-file credential."""

        if not isinstance(workspace_ref, str) or not workspace_ref:
            raise _invalid()
        method = getattr(self._binding, binding_method, None)
        if not callable(method):
            raise _unavailable()
        try:
            result = _as_dict(await _maybe_await(method({"workspace_ref": workspace_ref})))
        except IdentityBridgeError:
            raise
        except Exception as exc:
            raise _unavailable() from exc
        if result is None or result.get("ok") is not True:
            raise _unavailable()
        if set(result) != {"ok", "revoked"} or type(result["revoked"]) is not bool:
            raise _invalid()
        return result["revoked"]

    async def disconnect_b66_drive_full(self, *, workspace_ref: str) -> bool:
        """Revoke only the trusted workspace's B66 full-Drive credential."""

        return await self.disconnect_b66_drive(
            workspace_ref=workspace_ref,
            binding_method="disconnect_b66_drive_full",
        )


def _no_workspace_result() -> dict[str, Any]:
    """Fail-closed result for an active session with no canonical workspace."""

    return {
        "available": False,
        "workspace_connector_truth": False,
        "reason": _NO_CANONICAL_WORKSPACE,
        "connectors": (),
    }


def _available_result(connectors: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    return {
        "available": True,
        "workspace_connector_truth": True,
        "reason": None,
        "connectors": connectors,
    }


async def compose_workspace_connector_truth(
    *,
    identity_authority: Any,
    google_oauth_authority: Any,
    session_id: str,
) -> dict[str, Any]:
    """Compose bounded private workspace truth for one canonical session.

    ``session_id`` is the trusted server-side canonical session id. There is no
    ``workspace_ref`` parameter on purpose: a caller cannot assert, supply or
    override the workspace, so ``CLIENT_ASSERTED_WORKSPACE_AUTHORITY=NO`` holds
    by construction. The resolved reference is used for the existing default
    Google connector-state read and the dedicated Calendar presence read, then
    discarded — it never leaves this function.

    Returns a bounded result:

    * ``{"available": True, "connectors": (...)}`` — composed truth;
    * ``{"available": False, "reason": "canonical_connector_workspace_not_resolved"}``
      — the session is valid but has no canonical workspace yet.

    Every other failure (missing binding, malformed response, upstream error)
    raises :class:`IdentityBridgeError` with a reviewed code only.
    """

    if not isinstance(session_id, str) or not session_id:
        raise IdentityBridgeError(401, _INVALID_SESSION, _UNAVAILABLE_MESSAGE)
    if identity_authority is None:
        raise _unavailable()
    if google_oauth_authority is None:
        raise _unavailable()

    resolver = getattr(identity_authority, "resolve_connector_workspace", None)
    if not callable(resolver):
        raise _unavailable()
    try:
        workspace_ref = await _maybe_await(resolver(session_id=session_id))
    except IdentityBridgeError as exc:
        raise _identity_failure(exc) from exc
    except Exception as exc:  # noqa: BLE001 - never leak a driver error
        raise IdentityBridgeError(
            503,
            "identity_workspace_service_unavailable",
            _UNAVAILABLE_MESSAGE,
        ) from exc

    if workspace_ref is None:
        return _no_workspace_result()
    if not isinstance(workspace_ref, str) or not workspace_ref:
        raise _invalid()

    reader = getattr(google_oauth_authority, "workspace_connector_state", None)
    calendar_reader = getattr(
        google_oauth_authority,
        "workspace_calendar_connector_state",
        None,
    )
    if not callable(reader) or not callable(calendar_reader):
        raise _unavailable()
    try:
        connectors = await _maybe_await(reader(workspace_ref=workspace_ref))
        calendar_connectors = await _maybe_await(
            calendar_reader(workspace_ref=workspace_ref)
        )
    except IdentityBridgeError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak a driver error
        raise _unavailable() from exc

    if not isinstance(connectors, tuple) or not isinstance(calendar_connectors, tuple):
        raise _invalid()
    combined = connectors + calendar_connectors
    connector_ids = [row.get("connector_id") for row in combined if isinstance(row, dict)]
    if len(connector_ids) != len(combined) or len(set(connector_ids)) != len(connector_ids):
        raise _invalid()
    if set(connector_ids) - REVIEWED_WORKSPACE_TRUTH_CONNECTORS:
        raise _invalid()
    return _available_result(combined)


# Reviewed governance pins. These are asserted by the contract tests so the
# composition cannot drift into authority widening.
GOOGLE_OAUTH_AUTHORITY_DUPLICATION = False
IDENTITY_TO_GOOGLE_OAUTH_DIRECT_BINDING = False
NEW_WORKSPACE_AUTHORITY = False
NEW_CREDENTIAL_AUTHORITY = False
CLIENT_ASSERTED_WORKSPACE_AUTHORITY = False
WORKSPACE_REF_PROJECTED = False
RAW_IDENTITY_REF_PROJECTED = False
RAW_CREDENTIAL_MATERIAL_PROJECTED = False
SCOPE_MATERIAL_PROJECTED = False
PUBLIC_CONNECTOR_STATUS_MUTATED = False
PRODUCTION_BINDING_ACTIVATION = False
