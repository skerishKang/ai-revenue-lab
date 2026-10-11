"""#3237 — read-only canonical automation rule catalogue (Web projection).

Network-free tests. They prove the strict identity chain and the minimal
projection, and that this slice is genuinely read-only:

    signed-in user -> identity shadow -> refreshed canonical session
    -> AuthSessionSnapshot.tenant_id -> list_rules(tenant_id)

Specifically:
- CANONICAL_TENANT_AUTHORITY_REUSED: the existing strict resolver is used, and
  a session WITHOUT a canonical tenant yields no catalogue at all
- OWNER_FALLBACK_WORKSPACE: the ``f"owner:{user_id}"`` compatibility branch of
  the Claw memory resolver is NOT reachable here
- CALLER_TENANT_AUTHORITY: no query/header/body input can select a tenant
- CROSS_TENANT_DISCLOSURE: only the resolved tenant's rules are ever returned
- the projection never carries workspace_id / owner_ref / canonical_subject_id /
  execution_intent (task, repository_ref, exact_revision)
- no write method on the store is ever called
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from kagent.claw_automation import (
    ClawAutomationExecutionIntent,
    ClawAutomationOutputType,
    ClawAutomationRule,
    ClawAutomationTarget,
    ClawScheduleExpression,
    ClawScheduleKind,
    ClawNotificationChannel,
    ClawNotificationPreference,
)

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_automation_rules_routes import (
    CRON_ACTIVATION,
    MAX_RULES_PER_RESPONSE,
    PRODUCTION_SCHEDULER_ACTIVATION,
    RULE_CREATE,
    RULE_DELETE,
    RULE_ENABLE_DISABLE,
    RULE_UPDATE,
    RUN_NOW,
    WEB_RULE_AUTHORITY_CANONICAL,
    WEB_RULE_AUTHORITY_LEGACY_QUARANTINED,
    WEB_RULE_KEYS,
    AutomationRuleProjectionError,
    project_web_rule_row,
    web_rule_authority,
)
from app.config import Settings
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

LIST_PATH = "/api/claw/automation/rules"

SIGNED_IN_USER_ID = "usr_" + "7" * 32
OTHER_USER_ID = "usr_" + "f" * 32
# #3043 classifies against canonical id shapes: a tenant must be
# ``tenant_<32 hex>`` and a canonical subject ``sub_<32 hex>``. A non-canonical
# workspace is itself a legacy class, so a canonical rule can only be built on a
# canonical tenant.
TENANT_ID = "tenant_" + "a" * 32
OTHER_TENANT_ID = "tenant_" + "b" * 32
CANONICAL_SUBJECT_ID = "sub_" + "c" * 32


def _settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "claw-automation-client.apps.googleusercontent.com",
        "google_client_secret": "claw-automation-google-secret",
        "session_secret": "claw-automation-session-secret-not-real-00",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


def _shadow_store(**overrides) -> MagicMock:
    now = datetime.now(timezone.utc)
    values = {
        "product_user_id": SIGNED_IN_USER_ID,
        "canonical_subject_id": "subject_test",
        "auth_session_id": "session_test123",
        "session_revision": 1,
        "session_state": "active",
        "session_expires_at": now + timedelta(hours=1),
        "observed_at": now,
    }
    values.update(overrides)
    store = MagicMock()
    store.load_projection = AsyncMock(return_value=IdentityShadowRecord(**values))
    return store


def _session_snapshot(**overrides) -> AuthSessionSnapshot:
    now = datetime.now(timezone.utc)
    values = {
        "session_id": "session_test123",
        "product_id": PADIEM_CHAT_PRODUCT_ID,
        "subject": CanonicalSubjectRef(SubjectType.USER, "subject_test"),
        "issued_at": now - timedelta(hours=1),
        "expires_at": now + timedelta(hours=1),
        "state": AuthSessionState.ACTIVE,
        "revision": 1,
        "tenant_id": TENANT_ID,
    }
    values.update(overrides)
    return AuthSessionSnapshot(**values)


def _authority(snapshot=None) -> MagicMock:
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(
        return_value=snapshot if snapshot is not None else _session_snapshot()
    )
    return authority


def _rule(
    workspace_id: str,
    rule_id: str,
    name: str,
    *,
    canonical_subject_id: str | None = CANONICAL_SUBJECT_ID,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name=name,
        schedule=ClawScheduleExpression(
            kind=ClawScheduleKind.DAYPART, expression="morning", timezone="Asia/Seoul"
        ),
        target_source=ClawAutomationTarget.MEMORY,
        output_type=ClawAutomationOutputType.ALERT,
        enabled=True,
        notification_channels=(
            ClawNotificationPreference(channel=ClawNotificationChannel.WEB_ALERT_INBOX),
        ),
        owner_ref="opaque_delivery_owner_abc",
        canonical_subject_id=canonical_subject_id,
        execution_intent=ClawAutomationExecutionIntent(
            task="Summarize overnight inbox",
            repository_ref="https://example.test/private/repo",
            exact_revision="a" * 40,
        ),
    )


class _RecordingRuleStore:
    """Route-level fake recording exactly which workspace was read."""

    def __init__(self, rules: dict[str, list[ClawAutomationRule]]) -> None:
        self._rules = rules
        self.list_calls: list[str] = []
        self.write_calls: list[str] = []

    async def list_rules(self, workspace_id: str) -> list[ClawAutomationRule]:
        self.list_calls.append(workspace_id)
        return list(self._rules.get(workspace_id, []))

    # Every mutation surface is instrumented so a test can prove none fired.
    async def save_rule(self, rule) -> None:
        self.write_calls.append("save_rule")

    async def update_rule(self, rule) -> None:
        self.write_calls.append("update_rule")

    async def delete_rule(self, workspace_id, rule_id) -> None:
        self.write_calls.append("delete_rule")

    async def set_rule_enabled(self, workspace_id, rule_id, enabled) -> ClawAutomationRule:
        self.write_calls.append("set_rule_enabled")
        raise AssertionError("read-only slice must not toggle a rule")

    async def record_run(self, run) -> None:
        self.write_calls.append("record_run")


def _client(store, *, user_id: str = SIGNED_IN_USER_ID, snapshot=None) -> TestClient:
    app = create_app(
        settings=_settings(),
        history_store=MagicMock(),
        claw_automation_store=store,
    )
    app.state.identity_shadow_store = _shadow_store(product_user_id=user_id)
    app.state.control_plane_identity_authority = _authority(snapshot=snapshot)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), user_id),
        domain="chat.example.test",
        path="/",
    )
    return client


def _anonymous_client(store) -> TestClient:
    app = create_app(
        settings=_settings(), history_store=MagicMock(), claw_automation_store=store
    )
    app.state.identity_shadow_store = _shadow_store()
    app.state.control_plane_identity_authority = _authority()
    return TestClient(app, base_url="https://chat.example.test")


# --- route registration + read-only constants -------------------------------


def test_route_is_registered_as_get_only() -> None:
    app = create_app(Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"))
    routes = [r for r in app.routes if getattr(r, "path", None) == LIST_PATH]
    # #3257 added the POST Create route on the same resource; the read-only GET
    # route itself is unchanged, and no PUT/PATCH/DELETE exists.
    assert len(routes) == 2
    get_routes = [r for r in routes if "GET" in getattr(r, "methods", set())]
    post_routes = [r for r in routes if "POST" in getattr(r, "methods", set())]
    assert len(get_routes) == 1
    assert getattr(get_routes[0], "methods", set()) == {"GET", "HEAD"}
    assert len(post_routes) == 1
    assert getattr(post_routes[0], "methods", set()) == {"POST"}
    for route in routes:
        assert not getattr(route, "methods", set()) & {"PUT", "PATCH", "DELETE"}


def test_slice_declares_itself_read_only() -> None:
    assert RULE_CREATE is False
    assert RULE_UPDATE is False
    assert RULE_DELETE is False
    assert RULE_ENABLE_DISABLE is False
    assert RUN_NOW is False
    assert CRON_ACTIVATION is False
    assert PRODUCTION_SCHEDULER_ACTIVATION is False


# --- identity chain ---------------------------------------------------------


def test_anonymous_caller_gets_nothing() -> None:
    store = _RecordingRuleStore({TENANT_ID: [_rule(TENANT_ID, "rule_1", "아침 메모")]})
    client = _anonymous_client(store)
    resp = client.get(LIST_PATH)
    assert resp.status_code == 401
    assert store.list_calls == []


def test_rules_are_read_from_the_resolved_canonical_tenant() -> None:
    store = _RecordingRuleStore({TENANT_ID: [_rule(TENANT_ID, "rule_1", "아침 메모")]})
    client = _client(store)
    resp = client.get(LIST_PATH)
    assert resp.status_code == 200
    assert store.list_calls == [TENANT_ID]
    assert [r["name"] for r in resp.json()["rules"]] == ["아침 메모"]


def test_no_canonical_tenant_fails_closed_without_owner_fallback() -> None:
    """OWNER_FALLBACK_WORKSPACE=0: a session without a tenant lists nothing."""

    store = _RecordingRuleStore({f"owner:{SIGNED_IN_USER_ID}": [_rule("x", "rule_1", "leak")]})
    client = _client(store, snapshot=_session_snapshot(tenant_id=None))
    resp = client.get(LIST_PATH)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "canonical_tenant_unavailable"
    # The store was never asked for an owner-derived workspace, and the
    # owner-derived workspace's row is not disclosed.
    assert store.list_calls == []
    assert "leak" not in resp.text


def test_cross_tenant_rows_are_never_disclosed() -> None:
    store = _RecordingRuleStore(
        {
            TENANT_ID: [_rule(TENANT_ID, "rule_1", "내 규칙")],
            OTHER_TENANT_ID: [_rule(OTHER_TENANT_ID, "rule_2", "남의 규칙")],
        }
    )
    client = _client(store)
    body = client.get(LIST_PATH).json()
    assert [r["name"] for r in body["rules"]] == ["내 규칙"]
    assert "남의 규칙" not in str(body)
    assert OTHER_TENANT_ID not in str(body)


def test_caller_cannot_select_a_tenant() -> None:
    """CALLER_TENANT_AUTHORITY=0: query/header input cannot move the scope."""

    store = _RecordingRuleStore(
        {
            TENANT_ID: [_rule(TENANT_ID, "rule_1", "내 규칙")],
            OTHER_TENANT_ID: [_rule(OTHER_TENANT_ID, "rule_2", "남의 규칙")],
        }
    )
    client = _client(store)
    body = client.get(
        f"{LIST_PATH}?workspace_id={OTHER_TENANT_ID}&tenant_id={OTHER_TENANT_ID}",
        headers={"X-Workspace-Id": OTHER_TENANT_ID, "X-Tenant-Id": OTHER_TENANT_ID},
    ).json()
    assert store.list_calls == [TENANT_ID]
    assert "남의 규칙" not in str(body)


def test_missing_shadow_or_authority_fails_closed() -> None:
    store = _RecordingRuleStore({TENANT_ID: [_rule(TENANT_ID, "rule_1", "아침 메모")]})
    app = create_app(
        settings=_settings(), history_store=MagicMock(), claw_automation_store=store
    )
    app.state.identity_shadow_store = None
    app.state.control_plane_identity_authority = None
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    assert client.get(LIST_PATH).status_code == 403
    assert store.list_calls == []


def test_unavailable_store_fails_closed() -> None:
    app = create_app(settings=_settings(), history_store=MagicMock(), claw_automation_store=None)
    app.state.identity_shadow_store = _shadow_store()
    app.state.control_plane_identity_authority = _authority()
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    resp = client.get(LIST_PATH)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "automation_store_unavailable"


def test_reading_rules_performs_no_store_write() -> None:
    store = _RecordingRuleStore({TENANT_ID: [_rule(TENANT_ID, "rule_1", "아침 메모")]})
    client = _client(store)
    assert client.get(LIST_PATH).status_code == 200
    assert store.write_calls == []


# --- projection -------------------------------------------------------------


def test_projection_is_minimal_and_drops_internal_fields() -> None:
    store = _RecordingRuleStore({TENANT_ID: [_rule(TENANT_ID, "rule_1", "아침 메모")]})
    body = _client(store).get(LIST_PATH).json()
    row = body["rules"][0]
    assert set(row) == set(WEB_RULE_KEYS)
    # Never projected: tenant identity and internal execution material.
    assert "workspace_id" not in row
    assert "owner_ref" not in row
    assert "canonical_subject_id" not in row
    assert "execution_intent" not in row
    serialized = str(body)
    for leaked in (
        TENANT_ID,
        "opaque_delivery_owner_abc",
        "Summarize overnight inbox",
        "private/repo",
        "a" * 40,
    ):
        assert leaked not in serialized


def test_projection_reports_schedule_and_status_truthfully() -> None:
    row = project_web_rule_row(_rule(TENANT_ID, "rule_1", "아침 메모"))
    assert row["rule_id"] == "rule_1"
    assert row["name"] == "아침 메모"
    assert row["enabled"] is True
    assert row["schedule_kind"] == "daypart"
    assert row["schedule_expression"] == "morning"
    assert row["schedule_timezone"] == "Asia/Seoul"
    assert row["target_source"] == "memory"
    assert row["output_type"] == "alert"
    assert row["notification_channels"] == ["web_alert_inbox"]


def test_disabled_rule_is_reported_as_disabled() -> None:
    rule = ClawAutomationRule(
        rule_id="rule_off",
        workspace_id=TENANT_ID,
        name="저녁 정리",
        schedule=ClawScheduleExpression(
            kind=ClawScheduleKind.DAYPART, expression="evening", timezone="UTC"
        ),
        target_source=ClawAutomationTarget.INBOX,
        output_type=ClawAutomationOutputType.REPORT,
        enabled=False,
        notification_channels=(
            ClawNotificationPreference(channel=ClawNotificationChannel.WEB_ALERT_INBOX),
        ),
    )
    assert project_web_rule_row(rule)["enabled"] is False


def test_empty_catalogue_is_an_empty_list_not_an_error() -> None:
    store = _RecordingRuleStore({TENANT_ID: []})
    body = _client(store).get(LIST_PATH).json()
    assert body["ok"] is True
    assert body["rules"] == []
    assert body["truncated"] is False


# --- #3043 legacy authority classification ----------------------------------


def test_canonical_rule_is_reported_background_eligible() -> None:
    row = project_web_rule_row(_rule(TENANT_ID, "rule_1", "아침 메모"))
    assert row["authority_status"] == WEB_RULE_AUTHORITY_CANONICAL
    assert row["background_eligible"] is True


def test_legacy_rule_without_canonical_subject_is_quarantined() -> None:
    """#3043 LEGACY_MISSING_SUBJECT: not eligible for background execution."""

    legacy = _rule(TENANT_ID, "rule_legacy", "옛날 메모", canonical_subject_id=None)
    status, eligible = web_rule_authority(legacy)
    assert status == WEB_RULE_AUTHORITY_LEGACY_QUARANTINED
    assert eligible is False
    row = project_web_rule_row(legacy)
    assert row["authority_status"] == WEB_RULE_AUTHORITY_LEGACY_QUARANTINED
    assert row["background_eligible"] is False


def test_legacy_noncanonical_workspace_is_quarantined() -> None:
    legacy = _rule("ws_legacy", "rule_ws", "옛 워크스페이스", canonical_subject_id=None)
    row = project_web_rule_row(legacy)
    assert row["authority_status"] == WEB_RULE_AUTHORITY_LEGACY_QUARANTINED
    assert row["background_eligible"] is False


def test_same_tenant_legacy_row_is_disclosed_but_flagged_not_hidden() -> None:
    """A legacy row in the caller's own tenant is returned, but never as live."""

    store = _RecordingRuleStore(
        {
            TENANT_ID: [
                _rule(TENANT_ID, "rule_canonical", "현재 규칙"),
                _rule(TENANT_ID, "rule_legacy", "과거 규칙", canonical_subject_id=None),
            ]
        }
    )
    body = _client(store).get(LIST_PATH).json()
    by_id = {r["rule_id"]: r for r in body["rules"]}
    assert by_id["rule_canonical"]["authority_status"] == "canonical"
    assert by_id["rule_canonical"]["background_eligible"] is True
    assert by_id["rule_legacy"]["authority_status"] == "legacy_quarantined"
    assert by_id["rule_legacy"]["background_eligible"] is False
    # The classification exposes no subject identifier.
    serialized = str(body)
    assert "canonical_subject_id" not in serialized
    assert CANONICAL_SUBJECT_ID not in serialized


def test_legacy_classification_does_not_break_other_projection_fields() -> None:
    legacy = _rule(TENANT_ID, "rule_legacy", "과거 규칙", canonical_subject_id=None)
    row = project_web_rule_row(legacy)
    assert set(row) == set(WEB_RULE_KEYS)
    assert row["name"] == "과거 규칙"
    assert row["enabled"] is True


def test_authority_status_only_advertises_the_two_documented_values() -> None:
    assert {WEB_RULE_AUTHORITY_CANONICAL, WEB_RULE_AUTHORITY_LEGACY_QUARANTINED} == {
        "canonical",
        "legacy_quarantined",
    }


def test_projection_refuses_non_rule_values() -> None:
    with pytest.raises(AutomationRuleProjectionError):
        project_web_rule_row({"rule_id": "rule_1"})  # type: ignore[arg-type]


def test_projection_is_deterministic_and_sorted() -> None:
    store = _RecordingRuleStore(
        {
            TENANT_ID: [
                _rule(TENANT_ID, "rule_b", "둘째"),
                _rule(TENANT_ID, "rule_a", "첫째"),
            ]
        }
    )
    rows = _client(store).get(LIST_PATH).json()["rules"]
    assert [r["rule_id"] for r in rows] == ["rule_a", "rule_b"]


def test_response_is_bounded() -> None:
    many = [
        _rule(TENANT_ID, f"rule_{index:04d}", f"규칙 {index}")
        for index in range(MAX_RULES_PER_RESPONSE + 5)
    ]
    store = _RecordingRuleStore({TENANT_ID: many})
    body = _client(store).get(LIST_PATH).json()
    assert len(body["rules"]) == MAX_RULES_PER_RESPONSE
    assert body["truncated"] is True


def test_response_is_not_cached() -> None:
    store = _RecordingRuleStore({TENANT_ID: [_rule(TENANT_ID, "rule_1", "아침 메모")]})
    resp = _client(store).get(LIST_PATH)
    assert resp.headers["cache-control"] == "no-store, max-age=0"
    assert resp.headers["x-content-type-options"] == "nosniff"
