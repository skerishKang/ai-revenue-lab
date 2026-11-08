"""대표 지적 2026-11-08: the automation screen said "이 워크스페이스의 자동화
규칙을 볼 권한이 없습니다." even when the identity bridge merely FAILED — the
resolver collapsed bridge outages (503) and genuine refusals (403) into one
403. The list route must answer 503 (the front words it "불러오지 못했어요" +
retry) only when the bridge refuses the session does it say "권한 없음".
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient

from kagent.claw_automation import ClawAutomationRule
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity import IdentityBridgeError, PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord

LIST_PATH = "/api/claw/automation/rules"
TENANT = "tenant_" + "a" * 32
SUBJECT = "sub_" + "a" * 32
SESSION = "session_" + "a" * 8
USER = "usr_100"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="automation-branching.apps.googleusercontent.com",
        google_client_secret="automation-branching-google-secret",
        session_secret="automation-branching-session-secret-000",
        session_max_age_seconds=3600,
    )


def _snapshot() -> AuthSessionSnapshot:
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id=SESSION,
        product_id=PADIEM_CHAT_PRODUCT_ID,
        subject=CanonicalSubjectRef(SubjectType.USER, SUBJECT),
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
        tenant_id=TENANT,
    )


def _shadow_store(session_id: str = SESSION) -> MagicMock:
    now = datetime.now(timezone.utc)
    store = MagicMock()
    store.load_projection = AsyncMock(return_value=IdentityShadowRecord(
        product_user_id=USER,
        canonical_subject_id=SUBJECT,
        auth_session_id=session_id,
        session_revision=1,
        session_state="active",
        session_expires_at=now + timedelta(hours=1),
        observed_at=now,
    ))
    return store


def _authority(resolve_auth_session) -> MagicMock:
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(side_effect=resolve_auth_session)
    return authority


def _client(*, authority, shadow=None, store=None) -> TestClient:
    automation_store = store or MagicMock()

    async def list_rules(workspace_id):
        return []

    automation_store.list_rules = list_rules
    app = create_app(settings=_settings(), history_store=MagicMock(),
                     claw_automation_store=automation_store)
    app.state.identity_shadow_store = shadow if shadow is not None else _shadow_store()
    app.state.control_plane_identity_authority = authority
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE, create_session_token(_settings(), USER),
        domain="chat.example.test", path="/",
    )
    return client


def test_bridge_outage_answers_503_retry_not_forbidden():
    """Authority unreachable (503 class) must NOT read as "권한 없음" — the
    old collapse turned exactly this into a 403 permission refusal."""
    authority = _authority(IdentityBridgeError(
        503, "control_plane_session_unavailable",
        "Canonical auth session is unavailable.",
    ))
    client = _client(authority=authority)
    response = client.get(LIST_PATH)
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["error"]["code"] == "automation_rules_read_failed"
    assert body["error"]["code"] != "canonical_tenant_unavailable"


def test_missing_identity_bridge_answers_503_retry():
    """No shadow store / authority wired at all is a deployment failure, not
    a permission verdict."""
    client = _client(authority=MagicMock(), shadow=None)
    response = client.get(LIST_PATH)
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "automation_rules_read_failed"


def test_session_mismatch_answers_403_forbidden():
    """A session that does not match the linked identity is a real refusal —
    the permission wording stays, with its explicit code. (An authority that
    MALFUNCTIONS is different: resolve_refreshed_session wraps any authority
    exception into a 503, which is the outage branch above.)"""
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(return_value=_snapshot())
    client = _client(authority=authority, shadow=_shadow_store(session_id="other_session"))
    response = client.get(LIST_PATH)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "canonical_tenant_unavailable"


def test_healthy_resolution_still_lists_rules():
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(return_value=_snapshot())
    store = MagicMock()

    async def list_rules(workspace_id):
        assert workspace_id == TENANT
        return []

    store.list_rules = list_rules
    client = _client(authority=authority, store=store)
    response = client.get(LIST_PATH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["rules"] == []
