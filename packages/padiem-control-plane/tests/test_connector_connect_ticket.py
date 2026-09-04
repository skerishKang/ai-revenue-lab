from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json

import pytest

from padiem_control_plane.auth_sessions import (
    AuthSessionSnapshot,
    AuthSessionState,
)
from padiem_control_plane.connector_connect_ticket import (
    CONNECT_TICKET_AUDIENCE,
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    ConnectorConnectTicketAuthority,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)


NOW = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
KEY = b"control-plane-connect-ticket-key-32-bytes-minimum"


def session(**overrides) -> AuthSessionSnapshot:
    values = dict(
        session_id="auth_session_1",
        product_id="b54",
        subject=CanonicalSubjectRef(SubjectType.USER, "subject_1"),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )
    values.update(overrides)
    return AuthSessionSnapshot(**values)


def issue(authority: ConnectorConnectTicketAuthority, **overrides) -> str:
    values = dict(
        auth_session=session(),
        ticket_id="connect_ticket_1",
        connector_id="gmail",
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GMAIL_READONLY_SCOPE,),
        now=NOW,
        ttl_seconds=180,
    )
    values.update(overrides)
    return authority.issue(**values)


def decode_payload(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))


def test_issue_and_verify_binds_canonical_session_and_exact_google_connector_scope():
    authority = ConnectorConnectTicketAuthority(signing_key=KEY)
    auth = session()
    token = issue(authority, auth_session=auth)

    claims = authority.verify(
        token=token,
        now=NOW + timedelta(seconds=20),
        expected_connector_id="gmail",
        auth_session=auth,
    )

    assert claims.ticket_id == "connect_ticket_1"
    assert claims.session_id == auth.session_id
    assert claims.product_id == "b54"
    assert claims.subject_type == "user"
    assert claims.subject_id == "subject_1"
    assert claims.connector_id == "gmail"
    assert claims.actor_ref == "actor_1"
    assert claims.account_ref == "account_1"
    assert claims.workspace_ref == "workspace_1"
    assert claims.scopes == (GMAIL_READONLY_SCOPE,)
    assert claims.audience == CONNECT_TICKET_AUDIENCE
    assert claims.expires_at == NOW + timedelta(seconds=180)

    public = claims.to_public_dict()
    assert public["raw_ticket"] is False
    assert public["raw_signature"] is False
    assert public["raw_secret"] is False
    assert token not in json.dumps(public)


def test_canonical_unicode_and_space_subject_id_is_preserved_without_new_identity_grammar():
    authority = ConnectorConnectTicketAuthority(signing_key=KEY)
    auth = session(subject=CanonicalSubjectRef(SubjectType.USER, "사용자 001"))
    token = issue(authority, auth_session=auth)

    claims = authority.verify(token=token, now=NOW, auth_session=auth)

    assert claims.subject_id == "사용자 001"
    assert decode_payload(token)["subject_id"] == "사용자 001"


def test_drive_scope_is_separate_and_readonly_only():
    authority = ConnectorConnectTicketAuthority(signing_key=KEY)
    token = issue(
        authority,
        connector_id="google-drive",
        scopes=(GOOGLE_DRIVE_READONLY_SCOPE,),
    )
    claims = authority.verify(
        token=token,
        now=NOW,
        expected_connector_id="google-drive",
    )
    assert claims.scopes == (GOOGLE_DRIVE_READONLY_SCOPE,)

    with pytest.raises(ControlPlaneContractError) as exc:
        issue(
            authority,
            connector_id="google-drive",
            scopes=("https://www.googleapis.com/auth/drive",),
        )
    assert exc.value.code == "unreviewed_connect_scope"


def test_issue_rejects_inactive_session_and_unbounded_ttl():
    authority = ConnectorConnectTicketAuthority(signing_key=KEY)
    revoked = session(state=AuthSessionState.REVOKED)
    with pytest.raises(ControlPlaneContractError) as exc:
        issue(authority, auth_session=revoked)
    assert exc.value.code == "inactive_auth_session"

    expired = session(expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(ControlPlaneContractError) as exc:
        issue(authority, auth_session=expired)
    assert exc.value.code == "inactive_auth_session"

    with pytest.raises(ControlPlaneContractError):
        issue(authority, ttl_seconds=301)


def test_tamper_expiry_and_wrong_connector_fail_closed():
    authority = ConnectorConnectTicketAuthority(signing_key=KEY)
    token = issue(authority, ttl_seconds=30)

    version, payload, signature = token.split(".")
    tampered = f"{version}.{payload[:-1]}{'A' if payload[-1] != 'A' else 'B'}.{signature}"
    with pytest.raises(ControlPlaneContractError) as exc:
        authority.verify(token=tampered, now=NOW)
    assert exc.value.code == "invalid_connect_ticket"

    with pytest.raises(ControlPlaneContractError) as exc:
        authority.verify(token=token, now=NOW + timedelta(seconds=30))
    assert exc.value.code == "expired_connect_ticket"

    with pytest.raises(ControlPlaneContractError) as exc:
        authority.verify(
            token=token,
            now=NOW,
            expected_connector_id="google-drive",
        )
    assert exc.value.code == "connector_ticket_mismatch"


def test_payload_cannot_be_changed_even_if_fields_look_safe():
    authority = ConnectorConnectTicketAuthority(signing_key=KEY)
    token = issue(authority)
    wire = decode_payload(token)
    wire["workspace_ref"] = "workspace_attacker"
    encoded = base64.urlsafe_b64encode(
        json.dumps(wire, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    forged = f"v1.{encoded}.{token.split('.')[2]}"

    with pytest.raises(ControlPlaneContractError) as exc:
        authority.verify(token=forged, now=NOW)
    assert exc.value.code == "invalid_connect_ticket"


def test_verification_can_recheck_exact_canonical_session_and_revocation():
    authority = ConnectorConnectTicketAuthority(signing_key=KEY)
    auth = session()
    token = issue(authority, auth_session=auth)

    other = session(
        session_id="auth_session_2",
        subject=CanonicalSubjectRef(SubjectType.USER, "subject_2"),
    )
    with pytest.raises(ControlPlaneContractError) as exc:
        authority.verify(token=token, now=NOW, auth_session=other)
    assert exc.value.code == "connector_ticket_session_mismatch"

    revoked = session(state=AuthSessionState.REVOKED)
    with pytest.raises(ControlPlaneContractError) as exc:
        authority.verify(token=token, now=NOW, auth_session=revoked)
    assert exc.value.code == "inactive_auth_session"


def test_future_ticket_and_bad_signing_key_are_rejected():
    with pytest.raises(ControlPlaneContractError) as exc:
        ConnectorConnectTicketAuthority(signing_key=b"short")
    assert exc.value.code == "invalid_connect_ticket_authority"

    authority = ConnectorConnectTicketAuthority(signing_key=KEY)
    future_token = issue(authority, now=NOW + timedelta(minutes=2))
    with pytest.raises(ControlPlaneContractError) as exc:
        authority.verify(token=future_token, now=NOW)
    assert exc.value.code == "invalid_connect_ticket"


def test_ticket_is_credential_but_contains_no_signing_secret():
    authority = ConnectorConnectTicketAuthority(signing_key=KEY)
    token = issue(authority)
    assert KEY.decode("ascii") not in token
    wire = decode_payload(token)
    assert set(wire) == {
        "version",
        "audience",
        "ticket_id",
        "session_id",
        "product_id",
        "subject_type",
        "subject_id",
        "connector_id",
        "actor_ref",
        "account_ref",
        "workspace_ref",
        "scopes",
        "issued_at",
        "expires_at",
    }
    assert "secret" not in wire
    assert "refresh_token" not in wire
    assert "client_secret" not in wire
