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

No new workspace authority and no new credential authority is introduced. Both
B-1A (``resolve_connector_workspace``) and B-0 (``workspace_connector_state``)
private contracts are consumed exactly as shipped; neither is reimplemented.

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

# B-1B inherits the reviewed connector scope from B-0 verbatim. Telegram, Slack
# and Calendar workspace truth is NOT composed here; they stay on the Phase-A
# platform-support axis until a trusted workspace authority exists for them.
REVIEWED_WORKSPACE_TRUTH_CONNECTORS = frozenset({"gmail", "google-drive"})

# The B-0 bounded state contract. Anything else is a malformed response.
_CONNECTOR_STATE_KEYS = frozenset(
    {"connector_id", "state", "usable", "expires_present", "ambiguous"}
)
_CONNECTOR_STATES = frozenset({"connected", "not_connected", "ambiguous"})

_GOOGLE_OAUTH_UNAVAILABLE = "connector_workspace_truth_unavailable"
_GOOGLE_OAUTH_INVALID = "connector_workspace_truth_invalid"
_NO_CANONICAL_WORKSPACE = "canonical_connector_workspace_not_resolved"
_INVALID_SESSION = "canonical_connector_session_invalid"

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


def _invalid() -> IdentityBridgeError:
    return IdentityBridgeError(503, _GOOGLE_OAUTH_INVALID, _INVALID_MESSAGE)


def _bounded_connector(value: Any) -> dict[str, Any]:
    """Validate one B-0 state row and rebuild it from the reviewed keys only.

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
    # Scope lock: only the reviewed Google connectors carry workspace truth.
    if connector_id not in REVIEWED_WORKSPACE_TRUTH_CONNECTORS:
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
        return tuple(_bounded_connector(row) for row in connectors)


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
    by construction. The resolved reference is used for the single private
    Google OAuth read and is then discarded — it never leaves this function.

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
    except IdentityBridgeError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak a driver error
        raise _unavailable() from exc

    if workspace_ref is None:
        return _no_workspace_result()
    if not isinstance(workspace_ref, str) or not workspace_ref:
        raise _invalid()

    reader = getattr(google_oauth_authority, "workspace_connector_state", None)
    if not callable(reader):
        raise _unavailable()
    try:
        connectors = await _maybe_await(
            reader(workspace_ref=workspace_ref)
        )
    except IdentityBridgeError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak a driver error
        raise _unavailable() from exc

    if not isinstance(connectors, tuple):
        raise _invalid()
    return _available_result(connectors)


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
