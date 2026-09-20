"""#2830 B-1B private connector workspace truth composition contract.

Composition owner is PADIEM_CHAT / B62 and the direction is fixed:

    trusted session_id
        -> IDENTITY_AUTHORITY_SERVICE.resolve_connector_workspace
        -> canonical workspace_ref
        -> CONTROL_PLANE_GOOGLE_OAUTH.workspace_connector_state
        -> bounded connector truth

Identity Authority must never call Google OAuth, and Padiem Chat must never
call Google directly. The composed output is bounded to the reviewed B-0 state
contract (connector_id / state / usable / expires_present / ambiguous); no
workspace_ref, binding_ref, actor_ref, account_ref, scope or credential
material may ever appear in it.

This slice is private composition only: /api/connectors/status is untouched and
no Production Service Binding is activated.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from app import connector_workspace_truth as truth
from app.connector_workspace_truth import (
    CloudflareGoogleOAuthWorkspaceTruth,
    REVIEWED_WORKSPACE_TRUTH_CONNECTORS,
    compose_workspace_connector_truth,
)
from app.control_plane_identity import IdentityBridgeError

SESSION_ID = "authsession:b62:b1b-test"
WORKSPACE_REF = "workspace_b1b_test"

GMAIL_CONNECTED = {
    "connector_id": "gmail",
    "state": "connected",
    "usable": True,
    "expires_present": True,
    "ambiguous": False,
}
DRIVE_NOT_CONNECTED = {
    "connector_id": "google-drive",
    "state": "not_connected",
    "usable": False,
    "expires_present": False,
    "ambiguous": False,
}


class _IdentityBinding:
    """Fake Identity Authority binding honouring the B-1A private contract."""

    def __init__(self, *, present: bool = True, workspace_ref: str | None = WORKSPACE_REF) -> None:
        self.present = present
        self.workspace_ref = workspace_ref

    async def resolve_connector_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("session_id") is None:
            raise AssertionError("identity RPC requires session_id")
        if self.present is False:
            return {"ok": True, "workspace": {"present": False}}
        return {
            "ok": True,
            "workspace": {"present": True, "workspace_ref": self.workspace_ref},
        }


class _OAuthBinding:
    """Fake Google OAuth binding honouring the B-0 private contract."""

    def __init__(self, connectors: list[dict[str, Any]] | None = None, error: dict | None = None) -> None:
        self.connectors = connectors if connectors is not None else [GMAIL_CONNECTED, DRIVE_NOT_CONNECTED]
        self.error = error
        self.seen_payloads: list[dict[str, Any]] = []

    async def workspace_connector_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.seen_payloads.append(dict(payload))
        if self.error is not None:
            return {"ok": False, "error": self.error}
        return {"ok": True, "connectors": self.connectors}


def _identity(*, present: bool = True, workspace_ref: str | None = WORKSPACE_REF):
    from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority

    return CloudflareControlPlaneIdentityAuthority(_IdentityBinding(present=present, workspace_ref=workspace_ref))


def _oauth(connectors=None, error=None):
    return CloudflareGoogleOAuthWorkspaceTruth(_OAuthBinding(connectors, error))


FORBIDDEN_KEYS = (
    "workspace_ref",
    "binding_ref",
    "actor_ref",
    "account_ref",
    "subject_id",
    "tenant_id",
    "scopes",
    "scope",
    "refresh_token",
    "access_token",
    "sealed_refresh_token",
    "client_secret",
    "token",
    "credential",
)


def _assert_no_leak(payload: Any) -> None:
    """Recursively prove no raw identity/credential material was projected."""

    if isinstance(payload, dict):
        for key in payload:
            assert key not in FORBIDDEN_KEYS, f"leaked key: {key}"
        for value in payload.values():
            _assert_no_leak(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            _assert_no_leak(item)
    elif isinstance(payload, str):
        assert WORKSPACE_REF not in payload, "canonical workspace_ref leaked"


# --------------------------------------------------------------------------
# 1-2. canonical session -> canonical workspace -> Gmail / Drive truth
# --------------------------------------------------------------------------


async def test_gmail_workspace_truth_is_composed():
    result = await compose_workspace_connector_truth(
        identity_authority=_identity(),
        google_oauth_authority=_oauth([GMAIL_CONNECTED]),
        session_id=SESSION_ID,
    )
    assert result["available"] is True
    row = result["connectors"][0]
    assert row["connector_id"] == "gmail"
    assert row["state"] == "connected"
    assert row["usable"] is True
    _assert_no_leak(result)


async def test_drive_workspace_truth_is_composed():
    result = await compose_workspace_connector_truth(
        identity_authority=_identity(),
        google_oauth_authority=_oauth([DRIVE_NOT_CONNECTED]),
        session_id=SESSION_ID,
    )
    assert result["available"] is True
    row = result["connectors"][0]
    assert row["connector_id"] == "google-drive"
    assert row["state"] == "not_connected"
    assert row["usable"] is False
    _assert_no_leak(result)


# --------------------------------------------------------------------------
# 3-5. state preservation and ambiguity fail-closed
# --------------------------------------------------------------------------


async def test_connected_state_is_preserved():
    result = await compose_workspace_connector_truth(
        identity_authority=_identity(),
        google_oauth_authority=_oauth([GMAIL_CONNECTED]),
        session_id=SESSION_ID,
    )
    assert result["connectors"][0] == {
        "connector_id": "gmail",
        "state": "connected",
        "usable": True,
        "expires_present": True,
        "ambiguous": False,
    }


async def test_not_connected_state_is_preserved():
    result = await compose_workspace_connector_truth(
        identity_authority=_identity(),
        google_oauth_authority=_oauth([DRIVE_NOT_CONNECTED]),
        session_id=SESSION_ID,
    )
    assert result["connectors"][0]["state"] == "not_connected"
    assert result["connectors"][0]["usable"] is False


async def test_ambiguous_is_preserved_and_never_promoted():
    ambiguous = {
        "connector_id": "gmail",
        "state": "ambiguous",
        "usable": False,
        "expires_present": True,
        "ambiguous": True,
    }
    result = await compose_workspace_connector_truth(
        identity_authority=_identity(),
        google_oauth_authority=_oauth([ambiguous]),
        session_id=SESSION_ID,
    )
    row = result["connectors"][0]
    assert row["state"] == "ambiguous"
    assert row["usable"] is False
    assert row["ambiguous"] is True
    assert row["state"] != "connected"


async def test_ambiguous_marked_usable_is_rejected():
    binding = _OAuthBinding(
        [
            {
                "connector_id": "gmail",
                "state": "ambiguous",
                "usable": True,
                "expires_present": True,
                "ambiguous": True,
            }
        ]
    )
    with pytest.raises(IdentityBridgeError):
        await CloudflareGoogleOAuthWorkspaceTruth(binding).workspace_connector_state(
            workspace_ref=WORKSPACE_REF
        )


async def test_connected_marked_ambiguous_is_rejected():
    binding = _OAuthBinding(
        [
            {
                "connector_id": "gmail",
                "state": "connected",
                "usable": True,
                "expires_present": True,
                "ambiguous": True,
            }
        ]
    )
    with pytest.raises(IdentityBridgeError):
        await CloudflareGoogleOAuthWorkspaceTruth(binding).workspace_connector_state(
            workspace_ref=WORKSPACE_REF
        )


# --------------------------------------------------------------------------
# 6-8. no raw material leaks
# --------------------------------------------------------------------------


async def test_no_raw_identity_refs_are_projected():
    result = await compose_workspace_connector_truth(
        identity_authority=_identity(),
        google_oauth_authority=_oauth([GMAIL_CONNECTED, DRIVE_NOT_CONNECTED]),
        session_id=SESSION_ID,
    )
    _assert_no_leak(result)
    for row in result["connectors"]:
        assert set(row) == {
            "connector_id",
            "state",
            "usable",
            "expires_present",
            "ambiguous",
        }


async def test_no_scope_material_is_projected():
    result = await compose_workspace_connector_truth(
        identity_authority=_identity(),
        google_oauth_authority=_oauth([GMAIL_CONNECTED]),
        session_id=SESSION_ID,
    )
    serialized = repr(result)
    assert "scope" not in serialized.lower()


async def test_no_token_or_credential_material_is_projected():
    result = await compose_workspace_connector_truth(
        identity_authority=_identity(),
        google_oauth_authority=_oauth([GMAIL_CONNECTED]),
        session_id=SESSION_ID,
    )
    serialized = repr(result).lower()
    for term in ("token", "secret", "credential", "refresh"):
        assert term not in serialized


# --------------------------------------------------------------------------
# 9-10. malformed RPC responses fail closed
# --------------------------------------------------------------------------


async def test_identity_rpc_malformed_fails_closed():
    class _Broken:
        async def resolve_connector_workspace(self, *, session_id: str):
            return {"ok": True, "workspace": {"present": "yes"}}

    with pytest.raises(IdentityBridgeError):
        await compose_workspace_connector_truth(
            identity_authority=_Broken(),
            google_oauth_authority=_oauth(),
            session_id=SESSION_ID,
        )


async def test_oauth_rpc_malformed_fails_closed():
    broken = _OAuthBinding(
        [{"connector_id": "gmail", "state": "connected", "usable": True}]
    )
    with pytest.raises(IdentityBridgeError):
        await compose_workspace_connector_truth(
            identity_authority=_identity(),
            google_oauth_authority=CloudflareGoogleOAuthWorkspaceTruth(broken),
            session_id=SESSION_ID,
        )


async def test_oauth_rpc_unknown_extra_key_fails_closed():
    extra = _OAuthBinding(
        [
            {
                "connector_id": "gmail",
                "state": "connected",
                "usable": True,
                "expires_present": True,
                "ambiguous": False,
                "binding_ref": "binding_should_not_survive",
            }
        ]
    )
    with pytest.raises(IdentityBridgeError):
        await compose_workspace_connector_truth(
            identity_authority=_identity(),
            google_oauth_authority=CloudflareGoogleOAuthWorkspaceTruth(extra),
            session_id=SESSION_ID,
        )


async def test_oauth_error_envelope_is_not_echoed():
    failing = CloudflareGoogleOAuthWorkspaceTruth(
        _OAuthBinding(error={"code": "google_oauth_unavailable", "message": "internal detail"})
    )
    with pytest.raises(IdentityBridgeError) as excinfo:
        await compose_workspace_connector_truth(
            identity_authority=_identity(),
            google_oauth_authority=failing,
            session_id=SESSION_ID,
        )
    assert excinfo.value.code == "google_oauth_unavailable"
    assert "internal detail" not in str(excinfo.value)


# --------------------------------------------------------------------------
# 11. missing Service Binding -> unavailable
# --------------------------------------------------------------------------


async def test_missing_identity_binding_fails_closed():
    with pytest.raises(IdentityBridgeError):
        await compose_workspace_connector_truth(
            identity_authority=None,
            google_oauth_authority=_oauth(),
            session_id=SESSION_ID,
        )


async def test_missing_google_oauth_binding_fails_closed():
    with pytest.raises(IdentityBridgeError):
        await compose_workspace_connector_truth(
            identity_authority=_identity(),
            google_oauth_authority=None,
            session_id=SESSION_ID,
        )


async def test_session_without_canonical_workspace_fails_closed():
    result = await compose_workspace_connector_truth(
        identity_authority=_identity(present=False),
        google_oauth_authority=_oauth(),
        session_id=SESSION_ID,
    )
    assert result["available"] is False
    assert result["connectors"] == ()
    assert result["reason"] == "canonical_connector_workspace_not_resolved"


async def test_invalid_session_fails_closed():
    with pytest.raises(IdentityBridgeError):
        await compose_workspace_connector_truth(
            identity_authority=_identity(),
            google_oauth_authority=_oauth(),
            session_id="",
        )


# --------------------------------------------------------------------------
# 12. client cannot assert workspace_ref
# --------------------------------------------------------------------------


def test_composition_cannot_accept_a_client_workspace_ref():
    params = inspect.signature(compose_workspace_connector_truth).parameters
    assert "workspace_ref" not in params
    assert set(params) == {"identity_authority", "google_oauth_authority", "session_id"}


async def test_workspace_ref_is_only_used_for_the_private_read():
    oauth = _oauth([GMAIL_CONNECTED])
    await compose_workspace_connector_truth(
        identity_authority=_identity(),
        google_oauth_authority=oauth,
        session_id=SESSION_ID,
    )
    binding = oauth._binding
    assert binding.seen_payloads == [{"workspace_ref": WORKSPACE_REF}]


# --------------------------------------------------------------------------
# Scope + governance pins
# --------------------------------------------------------------------------


def test_reviewed_connector_scope_is_gmail_and_drive_only():
    assert REVIEWED_WORKSPACE_TRUTH_CONNECTORS == {"gmail", "google-drive"}


async def test_unreviewed_connector_is_rejected():
    telegram = {
        "connector_id": "telegram",
        "state": "connected",
        "usable": True,
        "expires_present": False,
        "ambiguous": False,
    }
    with pytest.raises(IdentityBridgeError):
        await compose_workspace_connector_truth(
            identity_authority=_identity(),
            google_oauth_authority=_oauth([telegram]),
            session_id=SESSION_ID,
        )


def test_governance_pins_hold():
    assert truth.GOOGLE_OAUTH_AUTHORITY_DUPLICATION is False
    assert truth.IDENTITY_TO_GOOGLE_OAUTH_DIRECT_BINDING is False
    assert truth.NEW_WORKSPACE_AUTHORITY is False
    assert truth.NEW_CREDENTIAL_AUTHORITY is False
    assert truth.CLIENT_ASSERTED_WORKSPACE_AUTHORITY is False
    assert truth.WORKSPACE_REF_PROJECTED is False
    assert truth.RAW_IDENTITY_REF_PROJECTED is False
    assert truth.RAW_CREDENTIAL_MATERIAL_PROJECTED is False
    assert truth.SCOPE_MATERIAL_PROJECTED is False
    assert truth.PUBLIC_CONNECTOR_STATUS_MUTATED is False
    assert truth.PRODUCTION_BINDING_ACTIVATION is False


def test_public_connector_status_projection_is_unchanged():
    from app.connector_status_projection import (
        WORKSPACE_REASON_NO_TRUSTED_AUTHORITY,
        WORKSPACE_STATE_UNVERIFIED,
        build_connector_status_projection,
    )

    projection = build_connector_status_projection()
    assert projection["workspace_state_authority"] is False
    for row in projection["connectors"]:
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_NO_TRUSTED_AUTHORITY
