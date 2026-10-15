"""#4089 2-B5: signed owner and independent CP READ authority; no Google calls."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from padiem_control_plane import (
    AuthSessionSnapshot, AuthSessionState, CanonicalSubjectRef, SubjectType,
)

from app import auth_routes
from app.b66_cp_drive_boundary import B66_REQUIRED_DRIVE_SCOPE
from app.b66_host_consent_activation import (
    B66HostConsentActivationGate,
    resolve_b66_host_consent_activation,
)

A = "usr_" + "a" * 32
B = "usr_" + "b" * 32


class Shadow:
    def __init__(self, subject):
        self.auth_session_id = "session-a"
        self.canonical_subject_id = subject
        self.session_revision = 1

    async def load_projection(self, product_user_id):
        return self


class Authority:
    def __init__(self, session):
        self.session = session
        self.reverse = A

    async def resolve_auth_session(self, *, session_id):
        return self.session

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        assert product_id == "b62"
        return self.reverse


class Context:
    def __init__(self, subject, *, product="b62", workspace="ws-a", actor="actor-a"):
        self.product_id = product
        self.subject_id = subject
        self.workspace_ref = workspace
        self.actor_ref = actor

    def resolve_existing(self, *, auth_session, now):
        return self


class Selection:
    def __init__(self, private=None):
        self.private = private or {
            "status": "resolved", "connector_id": "google-drive",
            "workspace_ref": "ws-a", "binding_ref": "bind-a", "actor_ref": "actor-a",
        }
        self.calls = 0

    def select_for_auth_session(self, *, auth_session, now):
        self.calls += 1
        return self

    def to_private_dict(self):
        return self.private


def session(subject="canon-a", *, expired=False, state=AuthSessionState.ACTIVE):
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session-a", product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, subject),
        issued_at=now - timedelta(minutes=5),
        expires_at=now - timedelta(seconds=1) if expired else now + timedelta(hours=1),
        state=state, revision=1,
    )


def fixtures(monkeypatch):
    monkeypatch.setattr(auth_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(auth_routes, "current_user_id", lambda request: A)
    authority = Authority(session())
    context = Context("canon-a")
    selection = Selection()
    bindings = dict(
        request=object(), identity_shadow_store=Shadow("canon-a"),
        current_canonical_session_authority=authority,
        connector_context_store=context,
        binding_selection_callsite=selection,
    )
    return bindings


def test_signed_owner_reads_existing_cp_and_returns_only_plan(monkeypatch):
    x = fixtures(monkeypatch)
    result = asyncio.run(resolve_b66_host_consent_activation(**x))
    assert result["status"] == "host_only_review_plan"
    assert result["public_gate"] == "DEFAULT_DENY"
    assert result["runtime_ready"] is False
    assert result["host_review"]["reviewed_scope"] == B66_REQUIRED_DRIVE_SCOPE
    assert result["host_review"]["destination_sub"] is None
    assert result["host_review"]["destination_account"] is None
    assert x["binding_selection_callsite"].calls == 1


@pytest.mark.parametrize("case", [
    "no-cookie", "wrong-user", "missing-session", "shadow-subject",
    "revoked", "expired", "reverse-owner", "context-subject",
    "context-product", "context-workspace", "cp-scope", "cp-connector",
    "missing-selection", "missing-context", "no-host",
])
def test_private_consent_review_refuses_unverified_owner_or_scope(monkeypatch, case):
    x = fixtures(monkeypatch)
    if case == "no-cookie":
        monkeypatch.setattr(auth_routes, "auth_ready", lambda request: False)
    elif case == "wrong-user":
        monkeypatch.setattr(auth_routes, "current_user_id", lambda request: B)
    elif case == "missing-session":
        x["current_canonical_session_authority"] = None
    elif case == "shadow-subject":
        x["identity_shadow_store"] = Shadow("foreign")
    elif case == "revoked":
        x["current_canonical_session_authority"].session = session(state=AuthSessionState.REVOKED)
    elif case == "expired":
        x["current_canonical_session_authority"].session = session(expired=True)
    elif case == "reverse-owner":
        x["current_canonical_session_authority"].reverse = B
    elif case == "context-subject":
        x["connector_context_store"].subject_id = "foreign"
    elif case == "context-product":
        x["connector_context_store"].product_id = "other"
    elif case == "context-workspace":
        x["connector_context_store"].workspace_ref = "ws-b"
    elif case == "cp-scope":
        # A READ binding may need reconnect, it never grants FILE.
        x["binding_selection_callsite"].private["status"] = "other-status"
    elif case == "cp-connector":
        x["binding_selection_callsite"].private["connector_id"] = "gmail"
    elif case == "missing-selection":
        x["binding_selection_callsite"] = None
    elif case == "missing-context":
        x["connector_context_store"] = None
    elif case == "no-host":
        x["identity_shadow_store"] = None
    with pytest.raises(ValueError):
        asyncio.run(resolve_b66_host_consent_activation(**x))


def test_client_cannot_supply_owner_or_private_selection(monkeypatch):
    x = fixtures(monkeypatch)
    with pytest.raises(TypeError):
        asyncio.run(resolve_b66_host_consent_activation(owner_b66_user_id=B, **x))
    with pytest.raises(TypeError):
        asyncio.run(resolve_b66_host_consent_activation(
            cp_private_selection={
                "status": "resolved", "connector_id": "google-drive",
                "workspace_ref": "ws-a", "binding_ref": "forged", "actor_ref": "actor-a",
            }, **x,
        ))


def test_gate_only_injection_time_authorities_and_public_default_deny(monkeypatch):
    x = fixtures(monkeypatch)
    request = x.pop("request")
    gate = B66HostConsentActivationGate(**x)
    assert gate.safe_dict()["runtime_ready"] is False
    assert gate.safe_dict()["production_mutation"] == 0
    assert gate.safe_dict()["shared_cp_scope_preserved"] is True
    result = asyncio.run(gate.compose_host_review(request=request))
    assert result["runtime_ready"] is False
    with pytest.raises(TypeError):
        asyncio.run(gate.compose_host_review(request=request, owner_b66_user_id=B))
