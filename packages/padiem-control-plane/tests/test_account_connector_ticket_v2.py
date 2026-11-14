"""Sessionless account tickets through signing, sealed OAuth state, and replay checks."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from test_identity_connector_account_key_write_rpc import ready, invoke, TICKET
from test_google_oauth_ingress_runtime import (
    fixture, auth_session, FakeTokenExchange, TICKET_KEY, NOW, AUTH_CODE,
    ACCESS_TOKEN, REFRESH_TOKEN,
)
from google_oauth_ingress_runtime import GoogleOAuthSessionPayload
from identity_connector_ticket import GoogleConnectTicketIssuer, CanonicalConnectorContextStore
from padiem_control_plane.connector_connect_ticket import (
    ConnectorConnectTicketAuthority, GOOGLE_DRIVE_READONLY_SCOPE,
)
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType, ControlPlaneContractError


def account_ticket():
    do, subject, _, _ = ready()
    do._connect_ticket_issuer._authority = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY)
    response = invoke(do, TICKET, subject)
    assert response["ok"] is True
    return response["ticket"]["connect_ticket"], subject


def decode(token):
    return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))


def sign_wire(wire, prefix="v2"):
    encoded = base64.urlsafe_b64encode(json.dumps(wire, separators=(",", ":")).encode()).decode().rstrip("=")
    signed = prefix + "." + encoded
    signature = base64.urlsafe_b64encode(hmac.new(TICKET_KEY, signed.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return signed + "." + signature


def test_real_account_ticket_completes_existing_oauth_path_without_a_session():
    raw, subject = account_ticket()
    exchange = FakeTokenExchange(payload={"access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN,
                                          "token_type": "Bearer", "scope": GOOGLE_DRIVE_READONLY_SCOPE})
    runtime, storage, _, _, authority, _ = fixture(exchange=exchange)
    runtime._clock = lambda: datetime.now(timezone.utc)
    claims = authority.verify(token=raw, now=runtime._clock())
    assert claims.version == "v2" and claims.session_id is None and claims.subject_id == subject
    receipt = asyncio.run(runtime.begin(connect_ticket=raw))
    with pytest.raises(ControlPlaneContractError) as replay:
        asyncio.run(runtime.begin(connect_ticket=raw))
    assert replay.value.code == "replayed_connect_ticket"
    state = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]
    connected = asyncio.run(runtime.complete_callback(state_ref=state, authorization_code=AUTH_CODE, provider_error=None))
    assert connected.actor_ref == claims.actor_ref and connected.workspace_ref == claims.workspace_ref
    assert connected.scopes == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert storage.count("google_oauth_authorization_state") == 0
    assert storage.count("google_oauth_refresh_credential") == 1 and len(exchange.calls) == 1
    assert all(value not in storage.all_text() for value in (raw, ACCESS_TOKEN, REFRESH_TOKEN, AUTH_CODE))
    with pytest.raises(ControlPlaneContractError) as repeated:
        asyncio.run(runtime.complete_callback(state_ref=state, authorization_code=AUTH_CODE, provider_error=None))
    assert repeated.value.code == "missing_google_oauth_state"


@pytest.mark.parametrize("value", ["", "session.fake", 1, False])
def test_v2_accepts_only_explicit_null_and_v1_still_requires_a_real_session_reference(value):
    raw, _ = account_ticket()
    wire = decode(raw)
    authority = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY)
    for change, prefix in (({"session_id": value}, "v2"), ({"version": "v1", "session_id": None}, "v1")):
        with pytest.raises(ControlPlaneContractError):
            authority.verify(token=sign_wire(wire | change, prefix), now=datetime.now(timezone.utc))


def test_missing_fields_and_version_confusion_are_rejected_even_with_valid_signature():
    raw, _ = account_ticket()
    wire = decode(raw)
    authority = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY)
    for field in ("session_id", "version", "subject_id"):
        malformed = dict(wire)
        del malformed[field]
        with pytest.raises(ControlPlaneContractError):
            authority.verify(token=sign_wire(malformed), now=datetime.now(timezone.utc))
    with pytest.raises(ControlPlaneContractError):
        authority.verify(token=sign_wire(wire, "v1"), now=datetime.now(timezone.utc))


def test_sealed_payload_keeps_missing_null_and_session_versions_distinct():
    session = auth_session()
    payload = GoogleOAuthSessionPayload(
        state_ref="state.test", connector_id="google-drive", actor_ref="actor.test", account_ref="account.test",
        workspace_ref="workspace.test", session_id=session.session_id, product_id="b62", subject_type="user",
        subject_id=session.subject.subject_id, scopes=(GOOGLE_DRIVE_READONLY_SCOPE,), code_verifier="V" * 64,
        redirect_uri="https://oauth.example.invalid/callback", created_at=session.issued_at,
        expires_at=session.issued_at + timedelta(seconds=600),
    )
    old = json.loads(payload.to_plaintext())
    assert "ticket_version" not in old
    assert GoogleOAuthSessionPayload.from_plaintext(payload.to_plaintext()) == payload
    new = old | {"ticket_version": "v2", "session_id": None}
    assert GoogleOAuthSessionPayload.from_plaintext(json.dumps(new)).session_id is None
    malformed = [old | {"session_id": None}, new | {"session_id": ""}, new | {"session_id": "session.fake"},
                 new | {"ticket_version": "v1"}, new | {"ticket_version": None}]
    missing = dict(new)
    del missing["session_id"]
    malformed.append(missing)
    for wire in malformed:
        with pytest.raises(ControlPlaneContractError):
            GoogleOAuthSessionPayload.from_plaintext(json.dumps(wire))


@pytest.mark.parametrize("subject", ["계정 번호", "opaque subject with spaces"])
def test_legacy_session_ticket_preserves_unicode_and_spaces(subject):
    from test_lovetree_identity_registration import _Storage
    original = replace(auth_session(), product_id="b62",
                       subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=subject))
    issuer = GoogleConnectTicketIssuer(context_store=CanonicalConnectorContextStore(_Storage()),
                                      signing_key=TICKET_KEY, clock=lambda: NOW)
    receipt = issuer.issue(auth_session=original, connector_id="google-drive")
    claims = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY).verify(token=receipt.connect_ticket, now=NOW,
                                                                         auth_session=original)
    assert claims.version == "v1" and claims.subject_id == subject and claims.session_id == original.session_id
