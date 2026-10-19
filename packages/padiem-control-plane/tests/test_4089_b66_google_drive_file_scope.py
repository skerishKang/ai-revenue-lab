"""Provider-free #4089 B66 Drive.file/full-Drive consent and CP durable tests."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from google_oauth_durable_store import (
    B66_GOOGLE_DRIVE_FILE_CONNECTOR,
    B66_GOOGLE_DRIVE_FULL_CONNECTOR,
    B66_GOOGLE_DRIVE_OIDC_SCOPES,
    GOOGLE_DRIVE_FILE_SCOPE,
    GOOGLE_DRIVE_FULL_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    CloudflareDurableGoogleOAuthStore,
)
from google_oauth_ingress_runtime import GoogleOAuthIngressRuntime, GoogleOAuthSessionPayload
from google_oauth_webcrypto_sealer import (
    GoogleOAuthSealContext,
    GoogleOAuthSealPurpose,
)
from padiem_control_plane.connector_connect_ticket import (
    B66_GOOGLE_DRIVE_FILE_CONNECTOR,
    B66_GOOGLE_DRIVE_FULL_CONNECTOR,
    B66_GOOGLE_DRIVE_OIDC_SCOPES as TICKET_OIDC_SCOPES,
)
from google_oauth_access_lease import _REVIEWED_SCOPES as lease_reviewed_scopes

from test_google_oauth_ingress_runtime import (
    NOW,
    ACCESS_TOKEN,
    AUTH_CODE,
    PKCE_VERIFIER,
    REFRESH_TOKEN,
    FakeTokenExchange,
    auth_session,
    fixture,
)


class FileTokenExchange(FakeTokenExchange):
    def __init__(self) -> None:
        super().__init__(
            payload={
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "token_type": "Bearer",
                "scope": " ".join(
                    (GOOGLE_DRIVE_FILE_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
                ),
            }
        )


class FullTokenExchange(FakeTokenExchange):
    def __init__(self) -> None:
        super().__init__(
            payload={
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "token_type": "Bearer",
                "scope": " ".join(
                    (GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
                ),
            }
        )


class DriveOnlyTokenExchange(FakeTokenExchange):
    def __init__(self) -> None:
        super().__init__(
            payload={
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "token_type": "Bearer",
                "scope": GOOGLE_DRIVE_FULL_SCOPE,
            }
        )


class VerifiedDestinationPort:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {
            "sub": "google-sub-12345678",
            "email": "owner@drive.test",
        }
        self.calls: list[str] = []

    async def verify_destination(self, *, config, access_token):
        self.calls.append(access_token)
        return dict(self.payload)

    def safe_dict(self):
        return {"test_port": True, "raw_access_token_public": False}


def b66_fixture(
    *,
    destination: VerifiedDestinationPort | None = None,
    connector_id: str = B66_GOOGLE_DRIVE_FILE_CONNECTOR,
):
    destination_port = destination or VerifiedDestinationPort()
    exchange = (
        FullTokenExchange()
        if connector_id == B66_GOOGLE_DRIVE_FULL_CONNECTOR
        else FileTokenExchange()
    )
    runtime, storage, store, sealer, authority, token_exchange = fixture(
        exchange=exchange,
        destination_verification=destination_port,
    )
    return runtime, storage, store, sealer, authority, token_exchange, destination_port


def b66_ticket(
    authority,
    *,
    connector_id: str = B66_GOOGLE_DRIVE_FILE_CONNECTOR,
    ticket_id: str = "ticket_b66",
) -> str:
    scope = (
        (GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
        if connector_id == B66_GOOGLE_DRIVE_FULL_CONNECTOR
        else (GOOGLE_DRIVE_FILE_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    )
    return authority.issue(
        auth_session=auth_session(),
        ticket_id=ticket_id,
        connector_id=connector_id,
        actor_ref="actor_b66_a",
        account_ref="account_b66_a",
        workspace_ref="workspace_b66_a",
        scopes=scope,
        now=NOW,
        ttl_seconds=180,
    )


def test_b66_file_connector_is_separate_from_shared_readonly_drive():
    from google_oauth_durable_store import _OAUTH_REVIEWED_SCOPES
    from google_oauth_ingress_runtime import _REVIEWED_SCOPES
    from padiem_control_plane.connector_connect_ticket import _REVIEWED_SCOPES as ticket_scopes

    assert ticket_scopes["google-drive"] == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert ticket_scopes[B66_GOOGLE_DRIVE_FILE_CONNECTOR] == (
        (GOOGLE_DRIVE_FILE_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    )
    assert _OAUTH_REVIEWED_SCOPES["google-drive"] == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert _OAUTH_REVIEWED_SCOPES[B66_GOOGLE_DRIVE_FILE_CONNECTOR] == (
        (GOOGLE_DRIVE_FILE_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    )
    assert _REVIEWED_SCOPES["google-drive"] == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert _REVIEWED_SCOPES[B66_GOOGLE_DRIVE_FILE_CONNECTOR] == (
        (GOOGLE_DRIVE_FILE_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    )


def test_b66_file_connector_rejects_a_readonly_grant_callback():
    exchange = FakeTokenExchange(
        payload={
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "token_type": "Bearer",
            "scope": GOOGLE_DRIVE_READONLY_SCOPE,
        }
    )
    runtime, storage, _, _, authority, _, _ = b66_fixture()
    runtime._token_exchange = exchange
    raw_ticket = b66_ticket(authority)
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    with pytest.raises(Exception) as mismatch:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert mismatch.value.code == "google_oauth_scope_mismatch"
    assert storage.count("google_oauth_refresh_credential") == 0
    assert storage.count("google_oauth_provider_destination") == 0


def test_b66_file_begin_requests_drive_file_and_completes_with_verified_destination():
    runtime, storage, store, sealer, authority, exchange, destination_port = b66_fixture()
    raw_ticket = b66_ticket(authority)
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))

    parsed = urlsplit(receipt.authorization_url)
    params = parse_qs(parsed.query)
    assert params["scope"] == [" ".join((GOOGLE_DRIVE_FILE_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES)]
    assert params["access_type"] == ["offline"]
    assert GOOGLE_DRIVE_READONLY_SCOPE not in receipt.authorization_url
    state_ref = params["state"][0]

    connected = asyncio.run(
        runtime.complete_callback(
            state_ref=state_ref,
            authorization_code=AUTH_CODE,
            provider_error=None,
        )
    )

    assert connected.connector_id == B66_GOOGLE_DRIVE_FILE_CONNECTOR
    assert connected.actor_ref == "actor_b66_a"
    assert connected.workspace_ref == "workspace_b66_a"
    assert connected.scopes == (GOOGLE_DRIVE_FILE_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    assert destination_port.calls == [ACCESS_TOKEN]
    assert exchange.calls
    assert storage.count("google_oauth_refresh_credential") == 1
    assert storage.count("google_oauth_provider_destination") == 1
    assert storage.count("google_oauth_authorization_state") == 0

    record = store.load_active_credential(binding_ref=connected.binding_ref, now=NOW)
    assert record.connector_id == B66_GOOGLE_DRIVE_FILE_CONNECTOR
    assert record.provider_subject == "google-sub-12345678"
    assert record.provider_email == "owner@drive.test"
    assert record.scopes == (GOOGLE_DRIVE_FILE_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    context = GoogleOAuthSealContext(
        purpose=GoogleOAuthSealPurpose.REFRESH_TOKEN,
        connector_id=B66_GOOGLE_DRIVE_FILE_CONNECTOR,
        record_ref=connected.binding_ref,
        actor_ref="actor_b66_a",
        account_ref="account_b66_a",
        workspace_ref="workspace_b66_a",
    )
    assert asyncio.run(
        sealer.unseal_text(envelope=record.sealed_refresh_token, context=context)
    ) == REFRESH_TOKEN

    selection = store.select_active_b66_google_drive_file_binding(
        workspace_ref="workspace_b66_a",
        now=NOW,
    )
    assert selection.status.value == "resolved"
    assert selection.provider_subject == "google-sub-12345678"
    assert selection.provider_email == "owner@drive.test"
    assert selection.actor_ref == "actor_b66_a"


def test_b66_file_callback_is_single_use_and_revoked_binding_is_not_usable():
    runtime, storage, store, sealer, authority, _, _ = b66_fixture()
    raw_ticket = b66_ticket(authority)
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    connected = asyncio.run(
        runtime.complete_callback(
            state_ref=state_ref,
            authorization_code=AUTH_CODE,
            provider_error=None,
        )
    )

    with pytest.raises(Exception) as replay:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert replay.value.code == "missing_google_oauth_state"

    store.revoke_credential(binding_ref=connected.binding_ref, revoked_at=NOW)
    with pytest.raises(Exception) as inactive:
        store.load_active_credential(binding_ref=connected.binding_ref, now=NOW)
    assert inactive.value.code == "inactive_google_oauth_binding"
    assert store.select_active_b66_google_drive_file_binding(
        workspace_ref="workspace_b66_a",
        now=NOW,
    ).status.value == "not_connected"


def test_b66_file_destination_verification_is_required():
    runtime, storage, store, sealer, authority, _, _ = b66_fixture(
        destination=None,
    )
    runtime._destination_verification = None
    raw_ticket = b66_ticket(authority)
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    with pytest.raises(Exception) as missing:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert missing.value.code == "google_oauth_destination_verification_unavailable"
    assert storage.count("google_oauth_refresh_credential") == 0


def test_b66_file_destination_must_be_verified_google_account():
    unverified = VerifiedDestinationPort(payload={"sub": "not a verified google subject"})
    runtime, storage, _, _, authority, _, _ = b66_fixture(destination=unverified)
    raw_ticket = b66_ticket(authority)
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    with pytest.raises(Exception) as invalid:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert invalid.value.code == "google_oauth_destination_unverified"
    assert storage.count("google_oauth_refresh_credential") == 0


def test_shared_drive_cannot_select_b66_file_binding():
    runtime, storage, store, sealer, authority, exchange, _ = b66_fixture()
    shared = store.select_active_b66_google_drive_file_binding(
        workspace_ref="workspace_shared",
        now=NOW,
    )
    assert shared.status.value == "not_connected"


def test_b66_full_drive_connector_is_separate_and_shared_drive_stays_readonly():
    from google_oauth_durable_store import _OAUTH_REVIEWED_SCOPES
    from google_oauth_ingress_runtime import _REVIEWED_SCOPES
    from padiem_control_plane.connector_connect_ticket import _REVIEWED_SCOPES as ticket_scopes

    assert ticket_scopes["google-drive"] == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert ticket_scopes[B66_GOOGLE_DRIVE_FILE_CONNECTOR] == (
        (GOOGLE_DRIVE_FILE_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    )
    assert ticket_scopes[B66_GOOGLE_DRIVE_FULL_CONNECTOR] == (
        (GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    )
    assert _OAUTH_REVIEWED_SCOPES["google-drive"] == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert _OAUTH_REVIEWED_SCOPES[B66_GOOGLE_DRIVE_FULL_CONNECTOR] == (
        (GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    )
    assert _REVIEWED_SCOPES["google-drive"] == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert _REVIEWED_SCOPES[B66_GOOGLE_DRIVE_FULL_CONNECTOR] == (
        (GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    )
    assert lease_reviewed_scopes["google-drive"] == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert lease_reviewed_scopes[B66_GOOGLE_DRIVE_FULL_CONNECTOR] == (
        (GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    )


def test_b66_callback_state_is_bound_to_canonical_owner_without_browser_owner_input():
    runtime, _, _, _, _, _, _ = b66_fixture(
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
    )
    created = NOW
    payload = GoogleOAuthSessionPayload(
        state_ref="state_owner_bound",
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
        actor_ref="actor_b66_a",
        account_ref="account_b66_a",
        workspace_ref="workspace_b66_a",
        session_id="sess_owner_bound",
        product_id="b62",
        subject_type="user",
        subject_id="subject 1 한글",
        scopes=(GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES,
        code_verifier=PKCE_VERIFIER,
        redirect_uri="https://oauth.example.invalid/v1/google/callback",
        created_at=created,
        expires_at=created + timedelta(seconds=600),
    )
    roundtrip = GoogleOAuthSessionPayload.from_plaintext(payload.to_plaintext())

    assert roundtrip.session_id == "sess_owner_bound"
    assert roundtrip.product_id == "b62"
    assert roundtrip.subject_type == "user"
    assert roundtrip.subject_id == "subject 1 한글"
    assert runtime.safe_dict()["callback_state_owner_bound"] is True


def test_b66_full_drive_begin_requests_full_scope_and_completes_with_verified_destination():
    runtime, storage, store, sealer, authority, exchange, destination_port = b66_fixture(
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
    )
    raw_ticket = b66_ticket(
        authority,
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
        ticket_id="ticket_b66_full",
    )
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))

    params = parse_qs(urlsplit(receipt.authorization_url).query)
    assert params["scope"] == [" ".join((GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES)]
    assert GOOGLE_DRIVE_READONLY_SCOPE not in receipt.authorization_url
    assert GOOGLE_DRIVE_FILE_SCOPE not in receipt.authorization_url
    state_ref = params["state"][0]

    connected = asyncio.run(
        runtime.complete_callback(
            state_ref=state_ref,
            authorization_code=AUTH_CODE,
            provider_error=None,
        )
    )

    assert connected.connector_id == B66_GOOGLE_DRIVE_FULL_CONNECTOR
    assert connected.scopes == (GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    assert destination_port.calls == [ACCESS_TOKEN]
    assert storage.count("google_oauth_refresh_credential") == 1
    assert storage.count("google_oauth_provider_destination") == 1

    record = store.load_active_credential(binding_ref=connected.binding_ref, now=NOW)
    assert record.connector_id == B66_GOOGLE_DRIVE_FULL_CONNECTOR
    assert record.scopes == (GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
    assert record.provider_subject == "google-sub-12345678"
    assert record.provider_email == "owner@drive.test"
    context = GoogleOAuthSealContext(
        purpose=GoogleOAuthSealPurpose.REFRESH_TOKEN,
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
        record_ref=connected.binding_ref,
        actor_ref="actor_b66_a",
        account_ref="account_b66_a",
        workspace_ref="workspace_b66_a",
    )
    assert asyncio.run(
        sealer.unseal_text(envelope=record.sealed_refresh_token, context=context)
    ) == REFRESH_TOKEN

    selection = store.select_active_b66_google_drive_full_binding(
        workspace_ref="workspace_b66_a",
        now=NOW,
    )
    assert selection.status.value == "resolved"
    assert selection.provider_subject == "google-sub-12345678"
    assert store.select_active_b66_google_drive_file_binding(
        workspace_ref="workspace_b66_a",
        now=NOW,
    ).status.value == "not_connected"


def test_b66_full_drive_rejects_a_drive_file_grant_without_silent_scope_widening():
    exchange = FakeTokenExchange(
        payload={
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "token_type": "Bearer",
            "scope": GOOGLE_DRIVE_FILE_SCOPE,
        }
    )
    runtime, storage, _, _, authority, _, _ = b66_fixture(
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
    )
    runtime._token_exchange = exchange
    raw_ticket = b66_ticket(authority, connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR)
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    with pytest.raises(Exception) as mismatch:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert mismatch.value.code == "google_oauth_scope_mismatch"
    assert storage.count("google_oauth_refresh_credential") == 0
    assert storage.count("google_oauth_provider_destination") == 0


def test_b66_full_drive_rejects_a_true_drive_only_grant():
    runtime, storage, _, _, authority, _, _ = b66_fixture(
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
    )
    runtime._token_exchange = DriveOnlyTokenExchange()
    raw_ticket = b66_ticket(
        authority,
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
        ticket_id="ticket_b66_drive_only",
    )
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    with pytest.raises(Exception) as mismatch:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert mismatch.value.code == "google_oauth_scope_mismatch"
    assert storage.count("google_oauth_refresh_credential") == 0
    assert storage.count("google_oauth_provider_destination") == 0


def test_b66_file_and_full_grants_are_independent_bindings():
    runtime, storage, store, sealer, authority, _, _ = b66_fixture(
        connector_id=B66_GOOGLE_DRIVE_FILE_CONNECTOR,
    )
    raw_ticket = b66_ticket(authority, connector_id=B66_GOOGLE_DRIVE_FILE_CONNECTOR)
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]
    file_connected = asyncio.run(
        runtime.complete_callback(
            state_ref=state_ref,
            authorization_code=AUTH_CODE,
            provider_error=None,
        )
    )

    full_runtime, full_storage, full_store, full_sealer, full_authority, _, _ = b66_fixture(
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
    )
    full_raw_ticket = b66_ticket(
        full_authority,
        connector_id=B66_GOOGLE_DRIVE_FULL_CONNECTOR,
        ticket_id="ticket_b66_full_independent",
    )
    full_receipt = asyncio.run(full_runtime.begin(connect_ticket=full_raw_ticket))
    full_state_ref = parse_qs(urlsplit(full_receipt.authorization_url).query)["state"][0]
    full_connected = asyncio.run(
        full_runtime.complete_callback(
            state_ref=full_state_ref,
            authorization_code=AUTH_CODE,
            provider_error=None,
        )
    )

    assert file_connected.connector_id == B66_GOOGLE_DRIVE_FILE_CONNECTOR
    assert full_connected.connector_id == B66_GOOGLE_DRIVE_FULL_CONNECTOR
    assert file_connected.binding_ref != full_connected.binding_ref
    assert store.select_active_b66_google_drive_file_binding(
        workspace_ref="workspace_b66_a",
        now=NOW,
    ).status.value == "resolved"
    assert full_store.select_active_b66_google_drive_full_binding(
        workspace_ref="workspace_b66_a",
        now=NOW,
    ).status.value == "resolved"

