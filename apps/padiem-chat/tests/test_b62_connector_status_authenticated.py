"""#2830 B-1C authenticated B62 connector status composition contract.

The public ``GET /api/connectors/status`` keeps publishing the Phase-A platform
support truth unchanged. On top of it, a **signed B62 product session** may now
contribute canonical workspace truth for exactly Gmail and Google Drive:

    signed B62 product session
        -> current_user_id(request)
        -> existing identity_shadow_store -> canonical auth_session_id
        -> existing control_plane_identity_authority (B-1A)
        -> existing google_oauth_workspace_truth (B-0)
        -> compose_workspace_connector_truth (B-1B)
        -> bounded Gmail / Drive workspace truth
        -> /api/connectors/status response

No new workspace, identity or OAuth authority is introduced. The browser can
never assert ``workspace_ref`` or any canonical reference, and an operational
fault (missing binding, malformed RPC, unresolved session) must never be
projected as ``not_connected``.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from app import connector_status_projection as projection_module
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.connector_status_projection import (
    PROJECTION_VERSION,
    WORKSPACE_REASON_AMBIGUOUS,
    WORKSPACE_REASON_IDENTITY_NOT_LINKED,
    WORKSPACE_REASON_NO_CANONICAL_WORKSPACE,
    WORKSPACE_REASON_NO_TRUSTED_AUTHORITY,
    WORKSPACE_REASON_TRUTH_UNAVAILABLE,
    WORKSPACE_STATE_AMBIGUOUS,
    WORKSPACE_STATE_CONNECTED,
    WORKSPACE_STATE_NOT_CONNECTED,
    WORKSPACE_STATE_UNVERIFIED,
    build_connector_status_projection,
)
from app.connector_workspace_truth import (
    CloudflareGoogleOAuthWorkspaceTruth,
    compose_workspace_connector_truth,
)
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.main import create_app

STATUS_PATH = "/api/connectors/status"
BASE_URL = "https://chat.example.test"

USER_ID = "usr_b1c_test_user"
CANONICAL_SUBJECT_ID = "subject_b1c_canonical"
CANONICAL_SESSION_ID = "authsession:b62:b1c"
WORKSPACE_REF = "workspace_b1c_canonical"

GMAIL_ID = "connector:google:gmail@1"
DRIVE_ID = "connector:google:drive@1"
TELEGRAM_ID = "connector:telegram:bot@1"
SLACK_ID = "connector:slack:workspace@1"
CALENDAR_ID = "connector:google:calendar@1"

GMAIL_CONNECTED = {
    "connector_id": "gmail",
    "state": "connected",
    "usable": True,
    "expires_present": True,
    "ambiguous": False,
}
DRIVE_CONNECTED = {
    "connector_id": "google-drive",
    "state": "connected",
    "usable": True,
    "expires_present": False,
    "ambiguous": False,
}
GMAIL_NOT_CONNECTED = {
    "connector_id": "gmail",
    "state": "not_connected",
    "usable": False,
    "expires_present": False,
    "ambiguous": False,
}
DRIVE_AMBIGUOUS = {
    "connector_id": "google-drive",
    "state": "ambiguous",
    "usable": False,
    "expires_present": True,
    "ambiguous": True,
}

# The public response is a bounded projection. These key names may never appear
# anywhere in it, at any depth.
FORBIDDEN_KEYS = (
    "session_id",
    "auth_session_id",
    "canonical_session_id",
    "workspace_ref",
    "actor_ref",
    "account_ref",
    "subject_id",
    "canonical_subject_id",
    "tenant_id",
    "binding_ref",
    "credential",
    "credential_binding",
    "access_token",
    "refresh_token",
    "sealed_refresh_token",
    "scope",
    "scopes",
    "ticket",
    "client_secret",
    "password",
    "reason",
)


# --------------------------------------------------------------------------
# Fakes: the reviewed B-1A / B-0 Service Binding contracts, plus the shadow store
# --------------------------------------------------------------------------


class _IdentityBinding:
    """Fake Identity Authority Service Binding honouring the B-1A contract."""

    def __init__(self, *, present: bool = True, workspace_ref: str | None = WORKSPACE_REF) -> None:
        self.present = present
        self.workspace_ref = workspace_ref
        self.calls: list[dict[str, Any]] = []

    async def resolve_connector_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(payload))
        if self.present is False:
            return {"ok": True, "workspace": {"present": False}}
        return {
            "ok": True,
            "workspace": {"present": True, "workspace_ref": self.workspace_ref},
        }


class _OAuthBinding:
    """Fake Google OAuth Service Binding honouring the B-0 contract."""

    def __init__(
        self,
        connectors: list[dict[str, Any]] | None = None,
        *,
        error: dict[str, Any] | None = None,
    ) -> None:
        self.connectors = (
            connectors if connectors is not None else [GMAIL_CONNECTED, DRIVE_CONNECTED]
        )
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def workspace_connector_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(dict(payload))
        if self.error is not None:
            return {"ok": False, "error": self.error}
        return {"ok": True, "connectors": self.connectors}


class _ShadowStore:
    """Fake B62 identity shadow store; non-authoritative pointer only."""

    def __init__(self, *, linked: bool = True, session_id: str = CANONICAL_SESSION_ID) -> None:
        self.linked = linked
        self.session_id = session_id
        self.calls: list[str] = []

    async def load_projection(self, product_user_id: str) -> IdentityShadowRecord | None:
        self.calls.append(product_user_id)
        if not self.linked:
            return None
        now = datetime.now(timezone.utc)
        return IdentityShadowRecord(
            product_user_id=USER_ID,
            canonical_subject_id=CANONICAL_SUBJECT_ID,
            auth_session_id=self.session_id,
            session_revision=3,
            session_state="active",
            session_expires_at=now + timedelta(hours=1),
            observed_at=now,
        )


class _BoomShadowStore:
    async def load_projection(self, product_user_id: str) -> IdentityShadowRecord | None:
        raise RuntimeError("shadow backend exploded")


# Sentinel meaning "build the default fake", so an explicit ``None`` can still be
# passed to model a missing product user.
_SENTINEL_PROFILE = object()


class _Profile:
    """Minimal B62 product user profile (existence is what matters here)."""

    def __init__(self, user_id: str = USER_ID) -> None:
        self.user_id = user_id

    def public_dict(self) -> dict[str, Any]:
        return {"user_id": self.user_id}


class _HistoryStore:
    """Fake B62 product history store; the product authentication authority."""

    def __init__(self, *, profile: Any = _SENTINEL_PROFILE) -> None:
        self.profile = _Profile() if profile is _SENTINEL_PROFILE else profile
        self.calls: list[str] = []

    async def get_user(self, user_id: str) -> Any:
        self.calls.append(user_id)
        return self.profile


class _BoomHistoryStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_user(self, user_id: str) -> Any:
        self.calls.append(user_id)
        raise RuntimeError("history backend exploded")


def _settings(*, auth_mode: str = "google") -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode=auth_mode,
        public_base_url=BASE_URL,
        google_client_id="connector-status-b1c.apps.googleusercontent.com",
        google_client_secret="unit-test-only-google-secret",
        session_secret="connector-status-b1c-session-secret-not-real",
        session_max_age_seconds=3600,
    )


def _app(
    *,
    identity_binding: Any = None,
    oauth_binding: Any = None,
    shadow_store: Any = None,
    history_store: Any = _SENTINEL_PROFILE,
    auth_mode: str = "google",
):
    settings = _settings(auth_mode=auth_mode)
    store = _HistoryStore() if history_store is _SENTINEL_PROFILE else history_store
    app = create_app(settings, history_store=store)
    app.state.control_plane_identity_authority = (
        CloudflareControlPlaneIdentityAuthority(identity_binding)
        if identity_binding is not None
        else None
    )
    app.state.identity_shadow_store = shadow_store
    app.state.google_oauth_workspace_truth = (
        CloudflareGoogleOAuthWorkspaceTruth(oauth_binding) if oauth_binding is not None else None
    )
    return settings, app


def _client(settings: Settings, app, *, signed_in: bool = True) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)
    if signed_in:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, USER_ID))
    return client


def _wired(
    connectors=None,
    *,
    present: bool = True,
    linked: bool = True,
    shadow_store=None,
    error=None,
    history_store=_SENTINEL_PROFILE,
    auth_mode: str = "google",
):
    """Return (settings, app, identity_binding, oauth_binding, shadow_store)."""

    identity_binding = _IdentityBinding(present=present)
    oauth_binding = _OAuthBinding(connectors, error=error)
    store = shadow_store if shadow_store is not None else _ShadowStore(linked=linked)
    settings, app = _app(
        identity_binding=identity_binding,
        oauth_binding=oauth_binding,
        shadow_store=store,
        history_store=history_store,
        auth_mode=auth_mode,
    )
    return settings, app, identity_binding, oauth_binding, store


def _rows(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["connector_id"]: row for row in document["connectors"]}


def _assert_no_leak(document: dict[str, Any]) -> None:
    """Recursively prove no raw identity/session/credential material was projected."""

    def walk(payload: Any) -> None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                assert key not in FORBIDDEN_KEYS, f"leaked key: {key}"
                walk(value)
        elif isinstance(payload, (list, tuple)):
            for item in payload:
                walk(item)
        elif isinstance(payload, str):
            for secret in (CANONICAL_SESSION_ID, WORKSPACE_REF, USER_ID, CANONICAL_SUBJECT_ID):
                assert secret not in payload, f"leaked value: {secret}"

    walk(document)


# --------------------------------------------------------------------------
# 1-2. anonymous compatibility and zero private calls
# --------------------------------------------------------------------------


async def test_1_anonymous_get_returns_the_phase_a_projection():
    settings, app, identity_binding, oauth_binding, store = _wired()
    async with _client(settings, app, signed_in=False) as client:
        response = await client.get(STATUS_PATH)
    assert response.status_code == 200
    assert response.json() == build_connector_status_projection()
    assert response.json() == {
        **build_connector_status_projection(),
        "workspace_state_authority": False,
    }
    for row in response.json()["connectors"]:
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_NO_TRUSTED_AUTHORITY


async def test_2_anonymous_request_makes_no_private_call():
    settings, app, identity_binding, oauth_binding, store = _wired()
    async with _client(settings, app, signed_in=False) as client:
        await client.get(STATUS_PATH)
    assert identity_binding.calls == []
    assert oauth_binding.calls == []
    assert store.calls == []


# --------------------------------------------------------------------------
# 3-6. authenticated canonical composition
# --------------------------------------------------------------------------


async def test_3_authenticated_gmail_connected_is_projected():
    settings, app, identity_binding, oauth_binding, _ = _wired([GMAIL_CONNECTED])
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    assert response.status_code == 200
    document = response.json()
    gmail = _rows(document)[GMAIL_ID]
    assert gmail["workspace_state"] == WORKSPACE_STATE_CONNECTED
    assert gmail["workspace_reason"] is None
    assert document["workspace_state_authority"] is True


async def test_4_authenticated_drive_connected_is_projected():
    settings, app, identity_binding, oauth_binding, _ = _wired([DRIVE_CONNECTED])
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    document = response.json()
    drive = _rows(document)[DRIVE_ID]
    assert drive["workspace_state"] == WORKSPACE_STATE_CONNECTED
    assert drive["workspace_reason"] is None
    assert _rows(document)[GMAIL_ID]["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
    assert document["workspace_state_authority"] is True


async def test_5_authenticated_not_connected_is_exact():
    settings, app, identity_binding, oauth_binding, _ = _wired([GMAIL_NOT_CONNECTED])
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    document = response.json()
    gmail = _rows(document)[GMAIL_ID]
    assert gmail["workspace_state"] == WORKSPACE_STATE_NOT_CONNECTED
    assert gmail["workspace_reason"] is None
    assert gmail["workspace_state"] != WORKSPACE_STATE_UNVERIFIED
    assert gmail["workspace_state"] != WORKSPACE_STATE_CONNECTED


async def test_6_authenticated_ambiguous_is_exact_and_never_connected():
    settings, app, identity_binding, oauth_binding, _ = _wired([DRIVE_AMBIGUOUS])
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    document = response.json()
    drive = _rows(document)[DRIVE_ID]
    assert drive["workspace_state"] == WORKSPACE_STATE_AMBIGUOUS
    assert drive["workspace_reason"] == WORKSPACE_REASON_AMBIGUOUS
    assert drive["workspace_state"] != WORKSPACE_STATE_CONNECTED
    assert "usable" not in drive


# --------------------------------------------------------------------------
# 7-9. non-Google connectors never gain guessed workspace truth
# --------------------------------------------------------------------------


async def test_7_telegram_stays_unverified():
    settings, app, *_ = _wired([GMAIL_CONNECTED, DRIVE_CONNECTED])
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    row = _rows(document)[TELEGRAM_ID]
    assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
    assert row["workspace_reason"] == WORKSPACE_REASON_NO_TRUSTED_AUTHORITY


async def test_8_slack_stays_unverified():
    settings, app, *_ = _wired([GMAIL_CONNECTED, DRIVE_CONNECTED])
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    row = _rows(document)[SLACK_ID]
    assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
    assert row["workspace_reason"] == WORKSPACE_REASON_NO_TRUSTED_AUTHORITY


async def test_9_calendar_stays_unverified():
    settings, app, *_ = _wired([GMAIL_CONNECTED, DRIVE_CONNECTED])
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    row = _rows(document)[CALENDAR_ID]
    assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
    assert row["workspace_reason"] == WORKSPACE_REASON_NO_TRUSTED_AUTHORITY


# --------------------------------------------------------------------------
# 10-13. fail-closed failure semantics
# --------------------------------------------------------------------------


async def test_10_missing_identity_shadow_never_fabricates_a_state():
    settings, app, identity_binding, oauth_binding, _ = _wired(linked=False)
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    document = response.json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        row = _rows(document)[connector_id]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_IDENTITY_NOT_LINKED
    assert oauth_binding.calls == []


async def test_11_no_canonical_workspace_is_unverified_with_closed_reason():
    settings, app, identity_binding, oauth_binding, _ = _wired(present=False)
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        row = _rows(document)[connector_id]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_NO_CANONICAL_WORKSPACE
    assert oauth_binding.calls == []


async def test_12_missing_private_oauth_authority_fails_closed():
    """A missing private binding must never be disguised as ``not_connected``."""

    settings, app = _app(identity_binding=_IdentityBinding(), shadow_store=_ShadowStore())
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    assert response.status_code == 200
    document = response.json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        row = _rows(document)[connector_id]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_TRUTH_UNAVAILABLE
        assert row["workspace_state"] != WORKSPACE_STATE_NOT_CONNECTED


async def test_13_malformed_private_composition_fails_closed():
    settings, app, identity_binding, oauth_binding, _ = _wired(
        error={"code": "google_oauth_unavailable", "message": "internal detail"}
    )
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    assert response.status_code == 200
    document = response.json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        row = _rows(document)[connector_id]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_TRUTH_UNAVAILABLE
    assert "internal detail" not in response.text


async def test_13b_shadow_store_fault_fails_closed():
    settings, app = _app(
        identity_binding=_IdentityBinding(),
        oauth_binding=_OAuthBinding(),
        shadow_store=_BoomShadowStore(),
    )
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    document = response.json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        row = _rows(document)[connector_id]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_TRUTH_UNAVAILABLE


async def test_13c_unknown_composed_state_fails_closed(monkeypatch):
    """A substituted composition cannot introduce an unpublished state."""

    async def _bogus(**kwargs):
        return {"available": True, "connectors": [{"connector_id": "gmail", "state": "totally_unknown"}]}

    monkeypatch.setattr(projection_module, "compose_workspace_connector_truth", _bogus)
    settings, app, *_ = _wired([GMAIL_CONNECTED])
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        row = _rows(document)[connector_id]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_TRUTH_UNAVAILABLE


@pytest.mark.parametrize(
    "envelope",
    [
        None,
        "not-a-dict",
        {"connectors": ()},
        {"available": "yes", "connectors": ()},
        {"available": True, "connectors": "not-a-list"},
        {"available": True, "connectors": ["not-a-row"]},
    ],
)
async def test_13d_malformed_composition_envelope_fails_closed(monkeypatch, envelope):
    async def _bogus(**kwargs):
        return envelope

    monkeypatch.setattr(projection_module, "compose_workspace_connector_truth", _bogus)
    settings, app, *_ = _wired([GMAIL_CONNECTED])
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        row = _rows(document)[connector_id]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_TRUTH_UNAVAILABLE


# --------------------------------------------------------------------------
# 14. the client cannot assert the workspace
# --------------------------------------------------------------------------


async def test_14_client_cannot_provide_a_workspace_ref():
    settings, app, identity_binding, oauth_binding, _ = _wired([GMAIL_CONNECTED])

    params = inspect.signature(compose_workspace_connector_truth).parameters
    assert "workspace_ref" not in params

    async with _client(settings, app) as client:
        baseline = await client.get(STATUS_PATH)
        forged = await client.get(
            STATUS_PATH,
            params={"workspace_ref": "attacker_workspace"},
            headers={
                "X-Workspace-Ref": "attacker_workspace",
                "X-Session-Id": "attacker_session",
                "X-Tenant-Id": "attacker_tenant",
            },
        )
    assert forged.status_code == 200
    assert forged.json() == baseline.json()
    # The only payload that ever reaches the private authorities is the trusted
    # session-scoped one; nothing from the query string or headers crosses over.
    assert identity_binding.calls
    assert all(call == {"session_id": CANONICAL_SESSION_ID} for call in identity_binding.calls)
    assert oauth_binding.calls
    assert all(call == {"workspace_ref": WORKSPACE_REF} for call in oauth_binding.calls)


# --------------------------------------------------------------------------
# 15-17. bounded projection: no leaks, no authority promotion
# --------------------------------------------------------------------------


async def test_15_no_raw_identity_or_workspace_reference_leaks():
    settings, app, *_ = _wired([GMAIL_CONNECTED, DRIVE_AMBIGUOUS])
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    _assert_no_leak(document)
    for row in document["connectors"]:
        assert set(row) == {
            "connector_id",
            "contract_version",
            "supported",
            "read_availability",
            "workspace_state",
            "workspace_reason",
            "deferred_reason",
        }


async def test_16_no_token_credential_or_scope_material_leaks():
    settings, app, *_ = _wired([GMAIL_CONNECTED, DRIVE_CONNECTED])
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    _assert_no_leak(response.json())
    lowered = response.text.lower()
    for needle in ("token", "secret", "credential", "scope", "oauth", "bearer", "ticket"):
        assert needle not in lowered, needle


async def test_17_send_write_is_never_authorized():
    settings, app, *_ = _wired([GMAIL_CONNECTED, DRIVE_CONNECTED])
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    assert document["send_write_authorized"] is False
    assert projection_module.READ_TRUTH_PROMOTES_TO_SEND_WRITE is False
    for row in document["connectors"]:
        assert row["supported"] == ["read"]


# --------------------------------------------------------------------------
# 18. the Phase-A support axis is untouched by B-1C
# --------------------------------------------------------------------------


async def test_18_static_support_truth_is_unchanged_when_authenticated():
    settings, app, *_ = _wired([GMAIL_CONNECTED, DRIVE_CONNECTED])
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    rows = _rows(document)
    expected = {
        DRIVE_ID: ("complete", None),
        GMAIL_ID: ("complete", None),
        TELEGRAM_ID: ("complete", None),
        SLACK_ID: ("deferred", "slack_live_deferred"),
        CALENDAR_ID: ("source_ready", "calendar_source_ready_live_deferred"),
    }
    for connector_id, (availability, deferred_reason) in expected.items():
        assert rows[connector_id]["read_availability"] == availability, connector_id
        assert rows[connector_id]["deferred_reason"] == deferred_reason, connector_id
        assert rows[connector_id]["supported"] == ["read"]
    assert document["static_support_vs_workspace_state_separated"] is True
    assert document["projection_version"] == PROJECTION_VERSION


# --------------------------------------------------------------------------
# 19. determinism
# --------------------------------------------------------------------------


async def test_19_repeated_requests_are_deterministic_for_the_same_inputs():
    settings, app, *_ = _wired([GMAIL_CONNECTED, DRIVE_AMBIGUOUS])
    async with _client(settings, app) as client:
        first = await client.get(STATUS_PATH)
        second = await client.get(STATUS_PATH)
    assert first.json() == second.json()
    assert json.dumps(first.json(), sort_keys=True) == json.dumps(second.json(), sort_keys=True)


# --------------------------------------------------------------------------
# 20. B-1B canonical state equivalence is inherited, not re-derived
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "malformed",
    [
        {"connector_id": "gmail", "state": "connected", "usable": False, "expires_present": True, "ambiguous": False},
        {"connector_id": "google-drive", "state": "not_connected", "usable": True, "expires_present": False, "ambiguous": False},
        {"connector_id": "gmail", "state": "ambiguous", "usable": False, "expires_present": True, "ambiguous": False},
        {"connector_id": "gmail", "state": "ambiguous", "usable": True, "expires_present": True, "ambiguous": True},
    ],
)
async def test_20_malformed_b1b_rows_fail_closed_through_the_projection(malformed):
    """B-1C must not weaken B-1B's canonical state equivalence."""

    settings, app, *_ = _wired([malformed])
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    assert response.status_code == 200
    document = response.json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        row = _rows(document)[connector_id]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_TRUTH_UNAVAILABLE


async def test_20b_valid_canonical_rows_still_compose_after_the_equivalence_check():
    settings, app, *_ = _wired([GMAIL_CONNECTED, DRIVE_AMBIGUOUS])
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    rows = _rows(document)
    assert rows[GMAIL_ID]["workspace_state"] == WORKSPACE_STATE_CONNECTED
    assert rows[DRIVE_ID]["workspace_state"] == WORKSPACE_STATE_AMBIGUOUS
    assert document["workspace_state_authority"] is True


# --------------------------------------------------------------------------
# 21-27. B62 product authentication boundary
#
#     COOKIE_UID_PRESENT != PRODUCT_USER_AUTHENTICATED
#
# Canonical workspace truth may only be projected after the local B62 product
# session is proven against the product authority. The canonical identity shadow
# is NOT a product authentication authority, and a canonical auth session is not
# a substitute for the product session.
# --------------------------------------------------------------------------


async def test_21_auth_mode_off_never_reaches_a_private_authority():
    settings, app, identity_binding, oauth_binding, store = _wired(auth_mode="off")
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    assert response.status_code == 200
    assert response.json() == build_connector_status_projection()
    assert identity_binding.calls == []
    assert oauth_binding.calls == []
    assert store.calls == []


async def test_22_missing_product_user_degrades_to_the_anonymous_projection():
    history = _HistoryStore(profile=None)
    settings, app, identity_binding, oauth_binding, store = _wired(history_store=history)
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    assert response.status_code == 200
    # Exactly the Phase-A projection: a stale cookie is not authenticated.
    assert response.json() == build_connector_status_projection()
    assert history.calls == [USER_ID]
    assert identity_binding.calls == []
    assert oauth_binding.calls == []
    assert store.calls == []


async def test_23_product_auth_lookup_failure_is_unavailable_not_a_state():
    history = _BoomHistoryStore()
    settings, app, identity_binding, oauth_binding, store = _wired(history_store=history)
    async with _client(settings, app) as client:
        response = await client.get(STATUS_PATH)
    assert response.status_code == 200
    document = response.json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        row = _rows(document)[connector_id]
        assert row["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert row["workspace_reason"] == WORKSPACE_REASON_TRUTH_UNAVAILABLE
    assert identity_binding.calls == []
    assert oauth_binding.calls == []
    assert store.calls == []


async def test_24_valid_product_profile_still_composes_canonical_truth():
    history = _HistoryStore()
    settings, app, identity_binding, oauth_binding, store = _wired(
        [GMAIL_CONNECTED, DRIVE_CONNECTED], history_store=history
    )
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    assert history.calls == [USER_ID]
    assert _rows(document)[GMAIL_ID]["workspace_state"] == WORKSPACE_STATE_CONNECTED
    assert _rows(document)[DRIVE_ID]["workspace_state"] == WORKSPACE_STATE_CONNECTED
    assert document["workspace_state_authority"] is True


async def test_25_stale_user_cookie_cannot_produce_any_connection_state():
    """A deleted product user must never surface a guessed connector state."""

    history = _HistoryStore(profile=None)
    settings, app, identity_binding, oauth_binding, store = _wired(
        [GMAIL_CONNECTED, DRIVE_CONNECTED], history_store=history
    )
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    rows = _rows(document)
    for connector_id in (GMAIL_ID, DRIVE_ID):
        assert rows[connector_id]["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
        assert rows[connector_id]["workspace_state"] != WORKSPACE_STATE_CONNECTED
        assert rows[connector_id]["workspace_state"] != WORKSPACE_STATE_NOT_CONNECTED
        assert rows[connector_id]["workspace_state"] != WORKSPACE_STATE_AMBIGUOUS
        assert rows[connector_id]["workspace_reason"] == WORKSPACE_REASON_NO_TRUSTED_AUTHORITY
    assert document["workspace_state_authority"] is False
    assert identity_binding.calls == []
    assert oauth_binding.calls == []
    assert store.calls == []


async def test_26_shadow_presence_alone_does_not_authenticate_the_product_user():
    """A linked canonical shadow with no product profile stays anonymous."""

    history = _HistoryStore(profile=None)
    shadow = _ShadowStore(linked=True)
    settings, app, identity_binding, oauth_binding, store = _wired(
        [GMAIL_CONNECTED], history_store=history, shadow_store=shadow
    )
    async with _client(settings, app) as client:
        document = (await client.get(STATUS_PATH)).json()
    assert document["workspace_state_authority"] is False
    for connector_id in (GMAIL_ID, DRIVE_ID):
        assert _rows(document)[connector_id]["workspace_state"] == WORKSPACE_STATE_UNVERIFIED
    # The canonical shadow was never even read.
    assert shadow.calls == []
    assert identity_binding.calls == []
    assert oauth_binding.calls == []


def test_27_product_authentication_boundary_pins_hold():
    assert projection_module.AUTH_READY_REQUIRED is True
    assert projection_module.PRODUCT_PROFILE_REQUIRED is True
    assert projection_module.SIGNED_COOKIE_ALONE_AUTHORIZES is False
    assert projection_module.SHADOW_PRESENCE_AUTHENTICATES_USER is False
    assert projection_module.CANONICAL_SESSION_REPLACES_PRODUCT_AUTH is False
    assert projection_module.NEW_AUTHENTICATION_AUTHORITY is False


# --------------------------------------------------------------------------
# Governance pins
# --------------------------------------------------------------------------


def test_governance_pins_hold():
    assert projection_module.NEW_WORKSPACE_AUTHORITY is False
    assert projection_module.NEW_IDENTITY_AUTHORITY is False
    assert projection_module.NEW_OAUTH_AUTHORITY is False
    assert projection_module.CLIENT_WORKSPACE_ASSERTION is False
    assert projection_module.IDENTITY_REF_PROJECTED is False
    assert projection_module.TOKEN_OR_SECRET_PROJECTED is False
    assert projection_module.SCOPE_PROJECTED is False
    assert projection_module.READ_TRUTH_PROMOTES_TO_SEND_WRITE is False


def test_closed_mapping_is_gmail_and_drive_only():
    assert projection_module._WORKSPACE_TRUTH_TARGETS == {
        "gmail": ("gmail", GMAIL_ID),
        "google-drive": ("drive", DRIVE_ID),
    }
    projection_module._require_reviewed_targets()
