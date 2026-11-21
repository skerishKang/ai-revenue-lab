"""Shared offline connector ticket bridge test fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.auth import create_session_token
from app.config import Settings
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.history import UserProfile
from app.main import create_app


SESSION_SECRET = "connector-ticket-session-secret-not-real-000000000"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="connector-test.apps.googleusercontent.com",
        google_client_secret="unit-test-only-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


class MemoryHistoryStore:
    def __init__(self) -> None:
        self.profile = UserProfile(
            "usr_" + "1" * 32,
            "user@example.test",
            "Connector User",
            "",
        )

    async def get_user(self, user_id):
        return self.profile if user_id == self.profile.id else None

    async def upsert_google_user(self, subject, email, name, picture):
        del subject, email, name, picture
        return self.profile


class MemoryShadowStore:
    def __init__(self, record: IdentityShadowRecord | None = None) -> None:
        self.record = record
        self.saved = []

    async def save_projection(self, bridged) -> None:
        self.saved.append(bridged)
        session = bridged.auth_session
        self.record = IdentityShadowRecord(
            product_user_id=bridged.product_user_id,
            canonical_subject_id=bridged.canonical_subject.subject_id,
            auth_session_id=session.session_id,
            session_revision=session.revision,
            session_state=session.state.value,
            session_expires_at=session.expires_at,
            observed_at=NOW,
        )

    async def load_projection(self, product_user_id):
        if self.record is None or self.record.product_user_id != product_user_id:
            return None
        return self.record


def shadow(profile_id: str) -> IdentityShadowRecord:
    return IdentityShadowRecord(
        product_user_id=profile_id,
        canonical_subject_id="sub_test",
        auth_session_id="sess_test",
        session_revision=1,
        session_state="active",
        session_expires_at=NOW + timedelta(hours=1),
        observed_at=NOW,
    )


class FakeControlPlaneBinding:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.ticket = "opaque-connect-ticket-that-never-appears-in-headers"
        self.ticket_error: dict | None = None

    async def resolve_or_create_product_link(self, payload):
        self.calls.append(("link", dict(payload)))
        return {
            "ok": True,
            "link": {
                "product_id": "b62",
                "product_user_id": payload["product_user_id"],
                "canonical_subject_id": "sub_test",
                "state": "active",
            },
        }

    async def establish_auth_session(self, payload):
        self.calls.append(("establish", dict(payload)))
        return {
            "ok": True,
            "session": {
                "session_id": "sess_test",
                "product_id": "b62",
                "subject": {"subject_type": "user", "subject_id": "sub_test"},
                "issued_at": payload["authenticated_at"],
                "expires_at": payload["not_after"],
                "state": "active",
                "revision": 1,
            },
        }

    async def resolve_auth_session(self, payload):
        self.calls.append(("resolve", dict(payload)))
        return {
            "ok": True,
            "session": {
                "session_id": payload["session_id"],
                "product_id": "b62",
                "subject": {"subject_type": "user", "subject_id": "sub_test"},
                "issued_at": NOW.isoformat(),
                "expires_at": (NOW + timedelta(hours=1)).isoformat(),
                "state": "active",
                "revision": 1,
            },
        }

    async def issue_google_connect_ticket(self, payload):
        self.calls.append(("ticket", dict(payload)))
        if self.ticket_error is not None:
            return {"ok": False, "error": dict(self.ticket_error)}
        return {
            "ok": True,
            "ticket": {
                "connect_ticket": self.ticket,
                "connector_id": payload["connector_id"],
                "expires_at": (NOW + timedelta(minutes=3)).isoformat(),
            },
        }

def cookie_for(profile_id: str) -> str:

    return create_session_token(settings(), profile_id, canonical_session_id="session_test_a")



def app_fixture(*, with_shadow=True, binding=None, auth_transport=None):
    history = MemoryHistoryStore()
    shadow_store = MemoryShadowStore(shadow(history.profile.id) if with_shadow else None)
    binding = binding or FakeControlPlaneBinding()
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    app = create_app(
        settings(),
        auth_transport=auth_transport,
        history_store=history,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow_store,
    )
    return app, history, shadow_store, binding, authority
