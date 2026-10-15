import asyncio
from datetime import datetime, timedelta, timezone
import pytest
from padiem_control_plane import AuthSessionSnapshot, AuthSessionState, CanonicalSubjectRef, SubjectType

from app.b66_cp_drive_boundary import B66_REQUIRED_DRIVE_SCOPE
from app.b66_host_consent_activation import B66HostConsentActivationGate, resolve_b66_host_consent_activation


class Shadow:
    def __init__(self, subject_id):
        self.canonical_subject_id = subject_id
        self.auth_session_id = "session-ident"
        self.session_revision = 1
        self.session_state = "active"
        self.session_expires_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
        self.observed_at = datetime.now(timezone.utc)

    async def load_projection(self, uid):
        return self


class Authority:
    def __init__(self, session):
        self.session = session

    async def resolve_auth_session(self, *, session_id):
        return self.session

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        return A


class Context:
    def __init__(self, subject_id, workspace="ws-a", actor="actor-a"):
        self.subject_id = subject_id
        self.workspace_ref = workspace
        self.actor_ref = actor

    def resolve_existing(self, *, auth_session, now):
        return self


class Callsite:
    def __init__(self, private_selection):
        self.private_selection = private_selection
        self.last_auth_session = None

    def select_for_auth_session(self, *, auth_session, now):
        self.last_auth_session = auth_session
        return self

    def to_private_dict(self):
        return self.private_selection


A = "usr_" + "a" * 32


def make_session(subject):
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session-ident",
        product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, subject),
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        tenant_id="tenant-a",
    )


def cp_private():
    return {"status": "resolved", "connector_id": "google-drive", "workspace_ref": "ws-a", "binding_ref": "bind-a", "actor_ref": "actor-a"}


def test_host_consent_requires_host_services():
    async def run():
        shadow = Shadow("canon-a")
        auth = Authority(make_session("canon-a"))
        context = Context("canon-a")
        callsite = Callsite(cp_private())
        result = await resolve_b66_host_consent_activation(
            A,
            identity_shadow_store=shadow,
            current_canonical_session_authority=auth,
            connector_context_store=context,
            binding_selection_callsite=callsite,
            now=datetime.now(timezone.utc),
        )
        assert result["status"] == "host_only_review_plan"
        assert result["verified_owner"] == A
        assert result["public_gate"] == "DEFAULT_DENY"
        assert callsite.last_auth_session is not None
    asyncio.run(run())


def test_host_consent_fails_without_callsite_or_selection():
    async def run():
        shadow = Shadow("canon-a")
        auth = Authority(make_session("canon-a"))
        context = Context("canon-a")
        try:
            await resolve_b66_host_consent_activation(
                A,
                identity_shadow_store=shadow,
                current_canonical_session_authority=auth,
                connector_context_store=context,
                now=datetime.now(timezone.utc),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("missing callsite accepted")
    asyncio.run(run())


def test_host_consent_rejects_mismatched_cp_owner():
    async def run():
        shadow = Shadow("canon-a")
        auth = Authority(make_session("canon-b"))
        context = Context("canon-b", "ws-b", "actor-b")
        callsite = Callsite({"status": "resolved", "connector_id": "google-drive", "workspace_ref": "ws-b", "binding_ref": "bind-b", "actor_ref": "actor-b"})
        try:
            await resolve_b66_host_consent_activation(
                A,
                identity_shadow_store=shadow,
                current_canonical_session_authority=auth,
                connector_context_store=context,
                binding_selection_callsite=callsite,
                now=datetime.now(timezone.utc),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("mismatched account accepted")
    asyncio.run(run())


def test_gate_defaults_are_fail_closed():
    gate = B66HostConsentActivationGate()
    assert gate.safe_dict()["production_mutation"] == 0
    assert gate.safe_dict()["runtime_ready"] is False
