"""#2010 Calendar Control-Plane access-lease convergence (Control Plane side).

Proves the Control Plane authority layers accept exactly one Calendar scope
(``https://www.googleapis.com/auth/calendar.readonly``) for the reviewed
``google-calendar`` OAuth connector, and that every layer fails closed on any
Calendar write/full/extra scope widening. No provider call, no OAuth mutation,
no D1 write and no secret value is involved anywhere in this file.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from google_oauth_access_lease import GoogleOAuthAccessLeaseRuntime
from google_oauth_durable_store import (
    GOOGLE_CALENDAR_READONLY_SCOPE,
    GMAIL_READONLY_SCOPE,
    DurableGoogleOAuthCredential,
    _REVIEWED_SCOPES,
)
from google_oauth_ingress_runtime import (
    GoogleOAuthIngressConfig,
    GoogleOAuthIngressRuntime,
)
from google_oauth_webcrypto_sealer import (
    GoogleOAuthSealContext,
    GoogleOAuthSealPurpose,
    GoogleOAuthWebCryptoSealer,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.connector_connect_ticket import ConnectorConnectTicketAuthority
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)

from test_google_oauth_ingress_runtime import (
    DeterministicAeadTestPort,
    FakeTokenExchange,
    FakeDurableStorage,
    SEAL_KEY,
    TICKET_KEY,
    TokenSource,
)

NOW = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)
CALENDAR_CONNECTOR_ID = "google-calendar"
CALENDAR_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar"
CALENDAR_FULL_SCOPE = "https://www.googleapis.com/auth/calendars"
ACCESS_TOKEN = "cp-calendar-access-token"
REFRESH_TOKEN = "cp-calendar-refresh-token"
SEALED_REFRESH = "sealed:v1:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"


def session() -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="auth_session_1",
        product_id="b54",
        subject=CanonicalSubjectRef(SubjectType.USER, "subject_1"),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )


def issue_ticket(authority: ConnectorConnectTicketAuthority, **overrides) -> str:
    values = dict(
        auth_session=session(),
        ticket_id="calendar_ticket_1",
        connector_id=CALENDAR_CONNECTOR_ID,
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        now=NOW,
        ttl_seconds=180,
    )
    values.update(overrides)
    return authority.issue(**values)


# ---------------------------------------------------------------------------
# A / B: connector ticket accepts exactly calendar.readonly and rejects widening
# ---------------------------------------------------------------------------


def test_a_connector_ticket_accepts_google_calendar_with_exact_readonly_scope() -> None:
    authority = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY)
    auth = session()
    token = issue_ticket(authority, auth_session=auth)

    claims = authority.verify(
        token=token,
        now=NOW + timedelta(seconds=10),
        expected_connector_id=CALENDAR_CONNECTOR_ID,
        auth_session=auth,
    )

    assert claims.connector_id == CALENDAR_CONNECTOR_ID
    assert claims.scopes == (GOOGLE_CALENDAR_READONLY_SCOPE,)
    assert claims.actor_ref == "actor_1"
    assert claims.workspace_ref == "workspace_1"


@pytest.mark.parametrize(
    "scopes",
    [
        (CALENDAR_WRITE_SCOPE,),
        (CALENDAR_FULL_SCOPE,),
        (GOOGLE_CALENDAR_READONLY_SCOPE, CALENDAR_WRITE_SCOPE),
        (GMAIL_READONLY_SCOPE,),
    ],
)
def test_b_connector_ticket_rejects_calendar_scope_widening(scopes: tuple[str, ...]) -> None:
    authority = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY)
    with pytest.raises(ControlPlaneContractError) as caught:
        issue_ticket(authority, scopes=scopes)
    assert caught.value.code == "unreviewed_connect_scope"


def test_b_empty_calendar_scope_set_fails_closed() -> None:
    authority = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY)
    with pytest.raises(ControlPlaneContractError) as caught:
        issue_ticket(authority, scopes=())
    assert caught.value.code == "invalid_connect_ticket"


def test_b_unreviewed_calendar_connector_alias_is_rejected() -> None:
    authority = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY)
    with pytest.raises(ControlPlaneContractError) as caught:
        issue_ticket(
            authority,
            connector_id="google-calendar-write",
            scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        )
    assert caught.value.code == "unreviewed_connect_scope"


# ---------------------------------------------------------------------------
# C: OAuth ingress requests exactly calendar.readonly
# ---------------------------------------------------------------------------


def calendar_ticket() -> str:
    authority = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY)
    return authority.issue(
        auth_session=session(),
        ticket_id="calendar_ticket_ingress",
        connector_id=CALENDAR_CONNECTOR_ID,
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        now=NOW,
        ttl_seconds=180,
    )


def test_c_oauth_ingress_requests_exactly_calendar_readonly() -> None:
    exchange = FakeTokenExchange(
        payload={
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "token_type": "Bearer",
            "scope": GOOGLE_CALENDAR_READONLY_SCOPE,
        }
    )
    storage = FakeDurableStorage()
    from google_oauth_durable_store import CloudflareDurableGoogleOAuthStore

    sealer = GoogleOAuthWebCryptoSealer(
        key_secret_b64url=SEAL_KEY,
        crypto_port=DeterministicAeadTestPort(),
    )
    runtime = GoogleOAuthIngressRuntime(
        store=CloudflareDurableGoogleOAuthStore(storage),
        sealer=sealer,
        ticket_authority=ConnectorConnectTicketAuthority(signing_key=TICKET_KEY),
        config=GoogleOAuthIngressConfig(
            client_id="client-id-public",
            client_secret="client-secret-private",
            redirect_uri="https://oauth.example.invalid/v1/google/callback",
        ),
        token_exchange=exchange,
        clock=lambda: NOW,
        random_token=TokenSource(),
    )

    receipt = asyncio.run(runtime.begin(connect_ticket=calendar_ticket()))
    params = parse_qs(urlsplit(receipt.authorization_url).query)

    assert params["scope"] == [GOOGLE_CALENDAR_READONLY_SCOPE]
    assert CALENDAR_WRITE_SCOPE not in receipt.authorization_url
    assert params["access_type"] == ["offline"]


# ---------------------------------------------------------------------------
# D: durable credential accepts only the reviewed calendar readonly scope
# ---------------------------------------------------------------------------


def calendar_credential(**overrides) -> DurableGoogleOAuthCredential:
    values = dict(
        binding_ref="calendar-binding-1",
        connector_id=CALENDAR_CONNECTOR_ID,
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
        sealed_refresh_token=SEALED_REFRESH,
        issued_at=NOW - timedelta(minutes=1),
    )
    values.update(overrides)
    return DurableGoogleOAuthCredential(**values)


def test_d_durable_calendar_credential_accepts_exactly_calendar_readonly() -> None:
    record = calendar_credential()
    assert record.scopes == (GOOGLE_CALENDAR_READONLY_SCOPE,)
    assert record.connector_id == CALENDAR_CONNECTOR_ID
    assert "google-calendar" in _REVIEWED_SCOPES
    assert _REVIEWED_SCOPES["google-calendar"] == (GOOGLE_CALENDAR_READONLY_SCOPE,)


@pytest.mark.parametrize(
    "scopes",
    [
        (CALENDAR_WRITE_SCOPE,),
        (CALENDAR_FULL_SCOPE,),
        (GOOGLE_CALENDAR_READONLY_SCOPE, CALENDAR_WRITE_SCOPE),
        (GMAIL_READONLY_SCOPE,),
    ],
)
def test_d_durable_calendar_credential_rejects_scope_widening(scopes: tuple[str, ...]) -> None:
    with pytest.raises(ControlPlaneContractError) as caught:
        calendar_credential(scopes=scopes)
    assert caught.value.code == "unreviewed_google_oauth_scope"


# ---------------------------------------------------------------------------
# E: CP access lease for google-calendar carries exactly the calendar scope
# ---------------------------------------------------------------------------


class FakeCalendarStore:
    def __init__(self, record=None, error: Exception | None = None) -> None:
        self.record = record or SimpleNamespace(
            binding_ref="calendar-binding-1",
            connector_id=CALENDAR_CONNECTOR_ID,
            actor_ref="actor_1",
            account_ref="account_1",
            workspace_ref="workspace_1",
            scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
            sealed_refresh_token=SEALED_REFRESH,
        )
        self.error = error

    def load_active_credential(self, *, binding_ref: str, now: datetime):
        if self.error is not None:
            raise self.error
        return self.record


class FakeSealer:
    async def unseal_text(self, *, envelope: str, context: GoogleOAuthSealContext) -> str:
        assert context.connector_id == CALENDAR_CONNECTOR_ID
        return REFRESH_TOKEN


class FakeCalendarRefreshPort:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {
            "access_token": ACCESS_TOKEN,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": GOOGLE_CALENDAR_READONLY_SCOPE,
        }
        self.calls: list[dict] = []

    async def refresh_access_token(self, **kwargs):
        self.calls.append(dict(kwargs))
        return dict(self.payload)

    def safe_dict(self):
        return {"test_port": True, "raw_token_public": False}


def calendar_runtime(*, store=None, refresh=None) -> GoogleOAuthAccessLeaseRuntime:
    return GoogleOAuthAccessLeaseRuntime(
        store=store or FakeCalendarStore(),
        sealer=FakeSealer(),
        config=GoogleOAuthIngressConfig(
            client_id="client-id-public",
            client_secret="client-secret-private",
            redirect_uri="https://oauth.example.invalid/v1/google/callback",
        ),
        refresh_port=refresh or FakeCalendarRefreshPort(),
        clock=lambda: NOW,
    )


def issue_calendar_lease(subject: GoogleOAuthAccessLeaseRuntime):
    return asyncio.run(
        subject.issue(binding_ref="calendar-binding-1", connector_id=CALENDAR_CONNECTOR_ID)
    )


def test_e_cp_access_lease_for_calendar_carries_only_the_calendar_readonly_scope() -> None:
    refresh = FakeCalendarRefreshPort()
    lease = issue_calendar_lease(calendar_runtime(refresh=refresh))

    assert lease.connector_id == CALENDAR_CONNECTOR_ID
    assert lease.scopes == (GOOGLE_CALENDAR_READONLY_SCOPE,)
    assert lease.expires_at == NOW + timedelta(seconds=3600)
    assert lease.access_token == ACCESS_TOKEN
    assert ACCESS_TOKEN not in repr(lease)
    assert "access_token" not in lease.safe_dict()
    assert refresh.calls and refresh.calls[0]["refresh_token"] == REFRESH_TOKEN


def test_e_widened_calendar_record_or_refresh_response_fails_closed() -> None:
    widened_record = SimpleNamespace(
        binding_ref="calendar-binding-1",
        connector_id=CALENDAR_CONNECTOR_ID,
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GOOGLE_CALENDAR_READONLY_SCOPE, CALENDAR_WRITE_SCOPE),
        sealed_refresh_token=SEALED_REFRESH,
    )
    with pytest.raises(ControlPlaneContractError) as record_error:
        issue_calendar_lease(calendar_runtime(store=FakeCalendarStore(record=widened_record)))
    assert record_error.value.code == "google_oauth_scope_mismatch"

    widened_response = FakeCalendarRefreshPort(
        payload={
            "access_token": ACCESS_TOKEN,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": f"{GOOGLE_CALENDAR_READONLY_SCOPE} {CALENDAR_WRITE_SCOPE}",
        }
    )
    with pytest.raises(ControlPlaneContractError) as refresh_error:
        issue_calendar_lease(calendar_runtime(refresh=widened_response))
    assert refresh_error.value.code == "google_oauth_scope_mismatch"


def test_e_unreviewed_calendar_connector_id_is_rejected_by_the_cp_lease() -> None:
    with pytest.raises(ControlPlaneContractError) as caught:
        asyncio.run(
            calendar_runtime().issue(
                binding_ref="calendar-binding-1",
                connector_id="google-calendar-write",
            )
        )
    assert caught.value.code == "unreviewed_google_oauth_scope"


def test_seal_context_accepts_calendar_readonly_authority() -> None:
    context = GoogleOAuthSealContext(
        purpose=GoogleOAuthSealPurpose.REFRESH_TOKEN,
        connector_id=CALENDAR_CONNECTOR_ID,
        record_ref="calendar-binding-1",
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
    )
    assert context.connector_id == CALENDAR_CONNECTOR_ID
