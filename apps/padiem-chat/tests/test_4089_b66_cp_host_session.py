import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from padiem_control_plane import AuthSessionSnapshot, AuthSessionState, CanonicalSubjectRef, SubjectType

from app.b66_cp_drive_boundary import B66VerifiedCPDriveOwnerLink, B66_REQUIRED_DRIVE_SCOPE
from app.b66_cp_host_session import B66PadiemCPHostComposer, resolve_b66_cp_drive_owner_from_padiem_session


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


class Context:
    def __init__(self, subject_id="canon-1", workspace="ws-a", actor="actor-a"):
        self.subject_id = subject_id
        self.workspace_ref = workspace
        self.actor_ref = actor

    def resolve_existing(self, *, auth_session, now):
        return self


A = "usr_" + "a" * 32


def make_session(owner):
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session-ident",
        product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, owner),
        issued_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=1),
        tenant_id="tenant-a",
    )


def test_composition_requires_host_services():
    async def run():
        subject = "canon-a"
        shadow = Shadow(subject)
        auth = Authority(make_session(subject))
        context = Context(subject)
        link = await resolve_b66_cp_drive_owner_from_padiem_session(
            owner_b66_user_id=A,
            identity_shadow_store=shadow,
            current_canonical_session_authority=auth,
            connector_context_store=context,
            now=datetime.now(timezone.utc),
        )
        assert isinstance(link, B66VerifiedCPDriveOwnerLink)
        assert link.cp_workspace_ref == "ws-a"

    asyncio.run(run())


def test_composition_fails_closed():
    async def run():
        shadow = Shadow("canon-a")
        auth = Authority(make_session("canon-b"))
        context = Context("canon-b", "ws-b", "actor-b")
        try:
            await resolve_b66_cp_drive_owner_from_padiem_session(
                owner_b66_user_id=A,
                identity_shadow_store=shadow,
                current_canonical_session_authority=auth,
                connector_context_store=context,
                now=datetime.now(timezone.utc),
            )
        except ValueError:
            pass
        else:
            raise AssertionError("subject mismatch accepted")

    asyncio.run(run())


def test_composer_safe_dict_marks_not_runtime_wired():
    composer = B66PadiemCPHostComposer(identity_shadow_store=None, current_canonical_session_authority=None, connector_context_store=None)
    assert composer.production_host_composition_proven is False
    assert composer.safe_dict()["production_runtime_wired"] is False
    assert B66_REQUIRED_DRIVE_SCOPE.endswith("/drive.file")
