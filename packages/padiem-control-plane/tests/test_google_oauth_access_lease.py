from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs
import sys

import pytest

from google_oauth_access_lease import (
    CloudflareGoogleOAuthRefreshPort,
    GoogleOAuthAccessLeaseRuntime,
)
from google_oauth_durable_store import GOOGLE_DRIVE_READONLY_SCOPE
from google_oauth_ingress_runtime import GoogleOAuthIngressConfig
from google_oauth_webcrypto_sealer import GoogleOAuthSealPurpose
from padiem_control_plane.contracts import ControlPlaneContractError


NOW = datetime(2026, 9, 9, 5, 0, tzinfo=timezone.utc)
ACCESS_TOKEN = "access-token-private"
REFRESH_TOKEN = "refresh-token-private"
CLIENT_SECRET = "secret&with=reserved+chars%"


class FakeStore:
    def __init__(self, record=None, error: Exception | None = None) -> None:
        self.record = record or SimpleNamespace(
            binding_ref="google-drive-binding-1",
            connector_id="google-drive",
            actor_ref="actor_1",
            account_ref="account_1",
            workspace_ref="workspace_1",
            scopes=(GOOGLE_DRIVE_READONLY_SCOPE,),
            sealed_refresh_token="sealed:v1:test",
        )
        self.error = error
        self.calls: list[tuple[str, datetime]] = []

    def load_active_credential(self, *, binding_ref: str, now: datetime):
        self.calls.append((binding_ref, now))
        if self.error is not None:
            raise self.error
        return self.record


class FakeSealer:
    def __init__(self, plaintext: str = REFRESH_TOKEN, error: Exception | None = None) -> None:
        self.plaintext = plaintext
        self.error = error
        self.calls = []

    async def unseal_text(self, *, envelope: str, context):
        self.calls.append((envelope, context))
        if self.error is not None:
            raise self.error
        return self.plaintext


class FakeRefreshPort:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload or {
            "access_token": ACCESS_TOKEN,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": GOOGLE_DRIVE_READONLY_SCOPE,
        }
        self.error = error
        self.calls = []

    async def refresh_access_token(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return dict(self.payload)

    def safe_dict(self):
        return {"test_port": True, "raw_token_public": False}


def config() -> GoogleOAuthIngressConfig:
    return GoogleOAuthIngressConfig(
        client_id="client-id.apps.googleusercontent.com",
        client_secret=CLIENT_SECRET,
        redirect_uri="https://oauth.padiem.net/callback",
    )


def runtime(*, store=None, sealer=None, refresh=None) -> GoogleOAuthAccessLeaseRuntime:
    return GoogleOAuthAccessLeaseRuntime(
        store=store or FakeStore(),
        sealer=sealer or FakeSealer(),
        config=config(),
        refresh_port=refresh or FakeRefreshPort(),
        clock=lambda: NOW,
    )


def issue(subject: GoogleOAuthAccessLeaseRuntime, **kwargs):
    return asyncio.run(
        subject.issue(
            binding_ref=kwargs.get("binding_ref", "google-drive-binding-1"),
            connector_id=kwargs.get("connector_id", "google-drive"),
        )
    )


def test_active_canonical_binding_issues_short_lived_private_lease() -> None:
    store = FakeStore()
    sealer = FakeSealer()
    refresh = FakeRefreshPort()
    lease = issue(runtime(store=store, sealer=sealer, refresh=refresh))

    assert lease.access_token == ACCESS_TOKEN
    assert lease.binding_ref == "google-drive-binding-1"
    assert lease.connector_id == "google-drive"
    assert lease.scopes == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert lease.expires_at == NOW + timedelta(seconds=3600)
    assert store.calls == [("google-drive-binding-1", NOW)]

    assert len(sealer.calls) == 1
    envelope, context = sealer.calls[0]
    assert envelope == "sealed:v1:test"
    assert context.purpose is GoogleOAuthSealPurpose.REFRESH_TOKEN
    assert context.record_ref == "google-drive-binding-1"
    assert context.connector_id == "google-drive"
    assert context.actor_ref == "actor_1"
    assert context.account_ref == "account_1"
    assert context.workspace_ref == "workspace_1"

    assert len(refresh.calls) == 1
    assert refresh.calls[0]["refresh_token"] == REFRESH_TOKEN


def test_private_rpc_contains_access_token_but_safe_projection_contains_no_secret_values() -> None:
    lease = issue(runtime())
    private = lease.to_private_rpc_dict()
    safe = lease.safe_dict()

    assert private["access_token"] == ACCESS_TOKEN
    assert "access_token" not in safe
    rendered_safe = repr(safe)
    assert ACCESS_TOKEN not in rendered_safe
    assert REFRESH_TOKEN not in rendered_safe
    assert CLIENT_SECRET not in rendered_safe
    assert safe["raw_access_token"] is False
    assert safe["raw_refresh_token"] is False
    assert safe["raw_client_secret"] is False
    assert ACCESS_TOKEN not in repr(lease)


def test_wrong_connector_is_rejected_before_refresh() -> None:
    refresh = FakeRefreshPort()
    with pytest.raises(ControlPlaneContractError) as caught:
        issue(runtime(refresh=refresh), connector_id="gmail")
    assert caught.value.code == "google_oauth_scope_mismatch"
    assert refresh.calls == []


def test_unreviewed_connector_is_rejected() -> None:
    with pytest.raises(ControlPlaneContractError) as caught:
        issue(runtime(), connector_id="google-drive-write")
    assert caught.value.code == "unreviewed_google_oauth_scope"


def test_scope_widening_in_canonical_record_is_rejected() -> None:
    record = SimpleNamespace(
        binding_ref="google-drive-binding-1",
        connector_id="google-drive",
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GOOGLE_DRIVE_READONLY_SCOPE, "https://www.googleapis.com/auth/drive"),
        sealed_refresh_token="sealed:v1:test",
    )
    refresh = FakeRefreshPort()
    with pytest.raises(ControlPlaneContractError) as caught:
        issue(runtime(store=FakeStore(record=record), refresh=refresh))
    assert caught.value.code == "google_oauth_scope_mismatch"
    assert refresh.calls == []


def test_revoked_or_expired_binding_error_fails_closed_without_unseal_or_refresh() -> None:
    error = ControlPlaneContractError(
        "inactive_google_oauth_binding",
        "Google OAuth credential is expired or revoked",
    )
    sealer = FakeSealer()
    refresh = FakeRefreshPort()
    with pytest.raises(ControlPlaneContractError) as caught:
        issue(runtime(store=FakeStore(error=error), sealer=sealer, refresh=refresh))
    assert caught.value.code == "inactive_google_oauth_binding"
    assert sealer.calls == []
    assert refresh.calls == []


def test_unseal_failure_never_attempts_refresh() -> None:
    refresh = FakeRefreshPort()
    sealer = FakeSealer(
        error=ControlPlaneContractError(
            "google_oauth_unseal_failed",
            "sealed material failed integrity verification",
        )
    )
    with pytest.raises(ControlPlaneContractError) as caught:
        issue(runtime(sealer=sealer, refresh=refresh))
    assert caught.value.code == "google_oauth_unseal_failed"
    assert refresh.calls == []


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"token_type": "Bearer", "expires_in": 3600}, "google_oauth_refresh_failed"),
        ({"access_token": ACCESS_TOKEN, "token_type": "MAC", "expires_in": 3600}, "google_oauth_refresh_failed"),
        ({"access_token": ACCESS_TOKEN, "token_type": "Bearer", "expires_in": 0}, "google_oauth_refresh_failed"),
        ({"access_token": ACCESS_TOKEN, "token_type": "Bearer", "expires_in": 7201}, "google_oauth_refresh_failed"),
        (
            {
                "access_token": ACCESS_TOKEN,
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/drive",
            },
            "google_oauth_scope_mismatch",
        ),
    ],
)
def test_invalid_or_widened_refresh_response_fails_closed(payload: dict, code: str) -> None:
    with pytest.raises(ControlPlaneContractError) as caught:
        issue(runtime(refresh=FakeRefreshPort(payload=payload)))
    assert caught.value.code == code


def test_refresh_port_uses_form_urlencoding_for_reserved_credential_characters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status = 200

        async def text(self):
            return '{"access_token":"a","token_type":"Bearer","expires_in":3600}'

    async def fake_fetch(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return Response()

    monkeypatch.setitem(sys.modules, "workers", SimpleNamespace(fetch=fake_fetch))
    subject = CloudflareGoogleOAuthRefreshPort()
    cfg = GoogleOAuthIngressConfig(
        client_id="client&id=1.apps.googleusercontent.com",
        client_secret=CLIENT_SECRET,
        redirect_uri="https://oauth.padiem.net/callback",
    )
    raw_refresh = "refresh&value=1+two%three"
    payload = asyncio.run(subject.refresh_access_token(config=cfg, refresh_token=raw_refresh))

    assert payload["access_token"] == "a"
    body = captured["body"]
    assert isinstance(body, str)
    fields = parse_qs(body, keep_blank_values=True, strict_parsing=True)
    assert fields["client_id"] == [cfg.client_id]
    assert fields["client_secret"] == [CLIENT_SECRET]
    assert fields["refresh_token"] == [raw_refresh]
    assert fields["grant_type"] == ["refresh_token"]
    assert raw_refresh not in body


def test_runtime_safe_dict_never_contains_raw_tokens_or_client_secret() -> None:
    safe = runtime().safe_dict()
    rendered = repr(safe)
    assert ACCESS_TOKEN not in rendered
    assert REFRESH_TOKEN not in rendered
    assert CLIENT_SECRET not in rendered
    assert safe["refresh_token_unsealed_inside_control_plane"] is True
    assert safe["refresh_token_returned"] is False
    assert safe["access_token_persisted"] is False
    assert safe["private_rpc_only"] is True
    assert safe["google_write_scope"] is False
