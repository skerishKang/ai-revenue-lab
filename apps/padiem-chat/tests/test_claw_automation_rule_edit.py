"""#3270 — OWNER-gated bounded edit (name + schedule) for a canonical rule.

Network-free tests over PATCH /api/claw/automation/rules/{rule_id}, built on
the same harness as #3262 (the authority helper is shared).

Proven fail-closed on: signed-out (401), no current B54 session (403),
non-owner roles (403 without role disclosure), unknown/foreign rules (one
bounded 404 with tenant-scoped lookups only), any body that is not exactly the
four editable keys — including task, execution_intent, owner_ref, enabled,
target_source, output_type, notification_channels, tenant, subject, role,
product, member and rule_id (400), malformed/oversized bodies (400/413),
legacy/quarantined rules (409, zero writes) and canonical-but-incomplete rules
(409, zero writes).

Proven on success: exactly one update_rule write, every non-edited field
carried from the persisted row (the #2908 execution intent is preserved, not
reconstructed), and a response built from the post-write RE-READ row — never
from the locally constructed object.
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
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)
from padiem_control_plane.tenants import TenantMembership, TenantMembershipRole

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_automation_rules_routes import WEB_RULE_KEYS
from app.config import Settings

EDIT_PATH = "/api/claw/automation/rules/{}"
SIGNIN_USER_ID = "usr_" + "7" * 32
TENANT_ID = "tenant_" + "a" * 32
OTHER_TENANT_ID = "tenant_" + "b" * 32
CANONICAL_SUBJECT_ID = "sub_" + "c" * 32
REVISION = "d" * 40
B54_PRODUCT = "b54-padiem-claw"
OWNER_REF = "automation_owner_" + "1" * 32


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


def _b54_snapshot(*, product_id: str = B54_PRODUCT, state: AuthSessionState = AuthSessionState.ACTIVE):
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="b54session123",
        product_id=product_id,
        subject=CanonicalSubjectRef(SubjectType.USER, CANONICAL_SUBJECT_ID),
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        state=state,
        revision=1,
        tenant_id=TENANT_ID,
    )


def _membership(role: TenantMembershipRole = TenantMembershipRole.OWNER) -> TenantMembership:
    return TenantMembership(
        tenant_id=TENANT_ID, canonical_subject_id=CANONICAL_SUBJECT_ID, role=role
    )


def _authority(snapshot=None, membership=None) -> MagicMock:
    authority = MagicMock()
    authority.resolve_current_auth_session = AsyncMock(
        return_value=snapshot if snapshot is not None else _b54_snapshot()
    )
    authority.resolve_active_tenant_membership = AsyncMock(
        return_value=membership if membership is not None else _membership()
    )
    return authority


def _intent() -> ClawAutomationExecutionIntent:
    return ClawAutomationExecutionIntent(
        task="Summarize overnight alerts",
        repository_ref="padiem-chat",
        exact_revision=REVISION,
    )


def _rule(
    rule_id: str,
    *,
    workspace_id: str = TENANT_ID,
    name: str = "아침 알림 요약",
    kind: str = "daypart",
    expression: str = "morning",
    timezone: str = "UTC",
    owner_ref: str | None = OWNER_REF,
    canonical_subject_id: str | None = CANONICAL_SUBJECT_ID,
    enabled: bool = True,
    execution_intent: ClawAutomationExecutionIntent | None = None,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name=name,
        schedule=ClawScheduleExpression(kind=kind, expression=expression, timezone=timezone),
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.REPORT,
        enabled=enabled,
        notification_channels=(
            ClawNotificationPreference(channel=ClawNotificationChannel.WEB_ALERT_INBOX),
        ),
        owner_ref=owner_ref,
        canonical_subject_id=canonical_subject_id,
        execution_intent=execution_intent if execution_intent is not None else _intent(),
    )


class _RecordingStore:
    """Tenant-scoped fake over the existing store surface (get/update rule)."""

    def __init__(self, rules=None, *, fail_update: bool = False, fail_reread: bool = False,
                 normalize_name: str | None = None):
        self.rules = {rule.rule_id: rule for rule in (rules or [])}
        self.get_rule_calls: list[tuple[str, str]] = []
        self.update_calls: list[ClawAutomationRule] = []
        self.fail_update = fail_update
        self.fail_reread = fail_reread
        self.normalize_name = normalize_name

    async def list_rules(self, workspace_id: str):
        return [r for r in self.rules.values() if r.workspace_id == workspace_id]

    async def get_rule(self, rule_id: str, workspace_id: str):
        self.get_rule_calls.append((rule_id, workspace_id))
        if self.fail_reread:
            raise RuntimeError("read failed")
        rule = self.rules.get(rule_id)
        if rule is None or rule.workspace_id != workspace_id:
            return None
        return rule

    async def update_rule(self, rule: ClawAutomationRule) -> None:
        self.update_calls.append(rule)
        if self.fail_update:
            raise RuntimeError("storage unavailable")
        # A durable store may normalize; the harness can simulate that so the
        # response must come from the re-read row, not the submitted object.
        stored = rule
        if self.normalize_name is not None:
            stored = ClawAutomationRule(
                rule_id=rule.rule_id,
                workspace_id=rule.workspace_id,
                name=self.normalize_name,
                schedule=rule.schedule,
                target_source=rule.target_source,
                output_type=rule.output_type,
                enabled=rule.enabled,
                notification_channels=rule.notification_channels,
                owner_ref=rule.owner_ref,
                execution_intent=rule.execution_intent,
                canonical_subject_id=rule.canonical_subject_id,
            )
        self.rules[rule.rule_id] = stored


def _client(store, *, authority=None, user_id: str | None = SIGNIN_USER_ID) -> TestClient:
    app = create_app(settings=_settings(), history_store=MagicMock(), claw_automation_store=store)
    app.state.control_plane_identity_authority = (
        authority if authority is not None else _authority()
    )
    client = TestClient(app, base_url="https://chat.example.test")
    if user_id:
        client.cookies.set(
            SESSION_COOKIE, create_session_token(_settings(), user_id),
            domain="chat.example.test", path="/",
        )
    return client


def _edit(client, rule_id: str = "rule_1", *, body: object = ..., raw: bytes | None = None):
    if raw is not None:
        return client.patch(
            EDIT_PATH.format(rule_id), content=raw,
            headers={"Content-Type": "application/json"},
        )
    if body is ...:
        body = {
            "name": "저녁 알림 요약",
            "schedule_kind": "daypart",
            "schedule_expression": "evening",
            "schedule_timezone": "UTC",
        }
    return client.patch(EDIT_PATH.format(rule_id), json=body)


# ── auth / identity ─────────────────────────────────────────────────────────


def test_signed_out_edit_is_401() -> None:
    store = _RecordingStore([_rule("rule_1")])
    assert _edit(_client(store, user_id=None)).status_code == 401
    assert store.update_calls == []


def test_no_current_b54_session_fails_closed() -> None:
    store = _RecordingStore([_rule("rule_1")])
    authority = _authority(snapshot=_b54_snapshot(state=AuthSessionState.REVOKED))
    resp = _edit(_client(store, authority=authority))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "current_b54_session_unavailable"
    assert store.update_calls == []


@pytest.mark.parametrize(
    "role",
    [TenantMembershipRole.VIEWER, TenantMembershipRole.OPERATOR, TenantMembershipRole.APPROVER],
)
def test_non_owner_roles_are_denied_403(role: TenantMembershipRole) -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _edit(_client(store, authority=_authority(membership=_membership(role))))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "owner_role_required"
    assert role.value not in resp.text
    assert store.update_calls == []


# ── lookup scope ────────────────────────────────────────────────────────────


def test_missing_and_foreign_rules_share_one_bounded_404() -> None:
    store = _RecordingStore([_rule("rule_foreign", workspace_id=OTHER_TENANT_ID)])
    client = _client(store)
    for rule_id in ("rule_missing", "rule_foreign"):
        resp = _edit(client, rule_id)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "automation_rule_not_found"
    assert store.update_calls == []
    assert store.get_rule_calls and all(call[1] == TENANT_ID for call in store.get_rule_calls)


def test_malformed_rule_id_is_bounded() -> None:
    store = _RecordingStore([_rule("rule_1")])
    for bad in ("rule with spaces", "rule/../x"):
        assert _edit(_client(store), bad).status_code in {400, 404}
    assert store.update_calls == []


# ── exact four-key body ─────────────────────────────────────────────────────


def test_exact_four_keys_edit_passes() -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _edit(_client(store))
    assert resp.status_code == 200
    assert resp.json()["rule"]["name"] == "저녁 알림 요약"
    assert resp.json()["rule"]["schedule_expression"] == "evening"


@pytest.mark.parametrize(
    "extra",
    [
        "task", "execution_intent", "owner_ref", "enabled", "target_source", "output_type",
        "notification_channels", "workspace_id", "tenant_id", "canonical_subject_id",
        "rule_id", "role", "product_id", "member_id", "repository_ref", "exact_revision",
    ],
)
def test_non_editable_or_authority_keys_are_400(extra: str) -> None:
    store = _RecordingStore([_rule("rule_1")])
    body = {
        "name": "이름",
        "schedule_kind": "daypart",
        "schedule_expression": "morning",
        "schedule_timezone": "UTC",
        extra: "caller_attempted_value",
    }
    resp = _edit(_client(store), body=body)
    assert resp.status_code == 400
    assert "caller_attempted_value" not in resp.text
    assert store.update_calls == []


def test_missing_key_is_400() -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _edit(_client(store), body={"name": "이름", "schedule_kind": "daypart"})
    assert resp.status_code == 400
    assert store.update_calls == []


def test_malformed_and_oversized_bodies_are_bounded() -> None:
    store = _RecordingStore([_rule("rule_1")])
    client = _client(store)
    assert client.patch(
        EDIT_PATH.format("rule_1"), content=b"{not json",
        headers={"Content-Type": "application/json"},
    ).status_code == 400
    oversized = client.patch(
        EDIT_PATH.format("rule_1"),
        content=b'{"name":"' + b"x" * (9 * 1024) + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
    assert store.update_calls == []


# ── eligibility ─────────────────────────────────────────────────────────────


def test_legacy_missing_subject_is_409_without_write() -> None:
    store = _RecordingStore([_rule("rule_legacy", canonical_subject_id=None)])
    resp = _edit(_client(store), "rule_legacy")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "automation_rule_not_mutable"
    assert store.update_calls == []


def test_missing_owner_ref_is_409_without_write() -> None:
    store = _RecordingStore([_rule("rule_1", owner_ref=None)])
    resp = _edit(_client(store), "rule_1")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "automation_rule_not_execution_ready"
    assert store.update_calls == []


def test_missing_execution_intent_is_409_without_write() -> None:
    rule = ClawAutomationRule(
        rule_id="rule_1",
        workspace_id=TENANT_ID,
        name="아침 알림 요약",
        schedule=ClawScheduleExpression(
            kind=ClawScheduleKind.DAYPART, expression="morning", timezone="UTC"
        ),
        target_source=ClawAutomationTarget.TASKS,
        output_type=ClawAutomationOutputType.REPORT,
        enabled=True,
        owner_ref=OWNER_REF,
        canonical_subject_id=CANONICAL_SUBJECT_ID,
    )
    store = _RecordingStore([rule])
    resp = _edit(_client(store), "rule_1")
    assert resp.status_code == 409
    assert store.update_calls == []


# ── name / schedule contracts ───────────────────────────────────────────────


def test_credential_shaped_name_is_400() -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _edit(_client(store), body={
        "name": "api_key = supersecretvalue123",
        "schedule_kind": "daypart",
        "schedule_expression": "morning",
        "schedule_timezone": "UTC",
    })
    assert resp.status_code == 400
    assert store.update_calls == []


@pytest.mark.parametrize("daypart", ["morning", "midday", "evening", "close_of_business"])
def test_daypart_matrix(daypart: str) -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _edit(_client(store), body={
        "name": "저녁 요약", "schedule_kind": "daypart",
        "schedule_expression": daypart, "schedule_timezone": "UTC",
    })
    assert resp.status_code == 200
    assert len(store.update_calls) == 1


@pytest.mark.parametrize("interval", ["15m", "1h", "6h", "1d"])
def test_interval_matrix(interval: str) -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _edit(_client(store), body={
        "name": "간격 요약", "schedule_kind": "interval",
        "schedule_expression": interval, "schedule_timezone": "UTC",
    })
    assert resp.status_code == 200


def test_cron_matrix() -> None:
    store = _RecordingStore([_rule("rule_1")])
    assert _edit(_client(store), body={
        "name": "cron 요약", "schedule_kind": "cron",
        "schedule_expression": "0 9 * * *", "schedule_timezone": "UTC",
    }).status_code == 200
    assert _edit(_client(store), body={
        "name": "cron 요약", "schedule_kind": "cron",
        "schedule_expression": "0 25 * * *", "schedule_timezone": "UTC",
    }).status_code == 400


def test_unresolvable_timezone_is_400_without_write() -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _edit(_client(store), body={
        "name": "이름", "schedule_kind": "daypart",
        "schedule_expression": "morning", "schedule_timezone": "Mars/Olympus",
    })
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_timezone"
    assert store.update_calls == []


def test_region_timezone_follows_runtime_timezone_database() -> None:
    import zoneinfo

    try:
        zoneinfo.ZoneInfo("Asia/Seoul")
        resolvable = True
    except Exception:
        resolvable = False
    store = _RecordingStore([_rule("rule_1")])
    resp = _edit(_client(store), body={
        "name": "이름", "schedule_kind": "daypart",
        "schedule_expression": "morning", "schedule_timezone": "Asia/Seoul",
    })
    if resolvable:
        assert resp.status_code == 200
        assert resp.json()["rule"]["schedule_timezone"] == "Asia/Seoul"
    else:
        assert resp.status_code == 400
        assert store.update_calls == []


# ── persistence: exactly one write, everything else preserved ────────────────


def test_edit_preserves_every_non_edited_field_and_writes_once() -> None:
    original = _rule("rule_1")
    store = _RecordingStore([original])
    resp = _edit(_client(store), "rule_1", body={
        "name": "새 이름", "schedule_kind": "interval",
        "schedule_expression": "2h", "schedule_timezone": "UTC",
    })
    assert resp.status_code == 200
    assert len(store.update_calls) == 1
    updated = store.update_calls[0]
    assert updated.name == "새 이름"
    assert updated.rule_id == original.rule_id
    assert updated.workspace_id == original.workspace_id
    assert updated.target_source is original.target_source
    assert updated.output_type is original.output_type
    assert updated.enabled is original.enabled
    assert updated.notification_channels == original.notification_channels
    assert updated.owner_ref == original.owner_ref
    assert updated.execution_intent == original.execution_intent
    assert updated.canonical_subject_id == original.canonical_subject_id


def test_response_reflects_the_post_write_reread_row() -> None:
    store = _RecordingStore([_rule("rule_1")], normalize_name="저장된 이름")
    resp = _edit(_client(store), "rule_1")
    assert resp.status_code == 200
    # The durable row is authoritative, not the locally built object.
    assert resp.json()["rule"]["name"] == "저장된 이름"
    assert len(store.update_calls) == 1


def test_post_write_read_failure_is_503_without_a_second_write() -> None:
    store = _RecordingStore([_rule("rule_1")])
    store.fail_reread = False

    class _FailingReread(_RecordingStore):
        async def update_rule(self, rule):
            self.update_calls.append(rule)
            self.rules[rule.rule_id] = rule
            self.fail_reread = True

    failing = _FailingReread([_rule("rule_1")])
    resp = _edit(_client(failing), "rule_1")
    assert resp.status_code == 503
    assert len(failing.update_calls) == 1  # SECOND_WRITE=0


def test_store_failure_is_503_without_retry() -> None:
    store = _RecordingStore([_rule("rule_1")], fail_update=True)
    resp = _edit(_client(store), "rule_1")
    assert resp.status_code == 503
    assert len(store.update_calls) == 1


# ── safe projection ─────────────────────────────────────────────────────────


def test_success_response_is_the_safe_projection_only() -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _edit(_client(store), "rule_1")
    payload = resp.json()
    assert set(payload) == {"ok", "rule"}
    assert set(payload["rule"]) == set(WEB_RULE_KEYS)
    for secret in (
        TENANT_ID, CANONICAL_SUBJECT_ID, OWNER_REF, REVISION, "padiem-chat",
        "Summarize overnight alerts", "automation_owner_",
    ):
        assert secret not in resp.text


# ── route registration + slice constants ────────────────────────────────────


def test_route_registered_and_slice_is_edit_only() -> None:
    from app.claw_automation_rule_edit_routes import (
        CRON_ACTIVATION,
        CROSS_TENANT_RULE_LOOKUP,
        ENABLED_EDIT,
        EXECUTION_INTENT_EDIT,
        IN_PLACE_RULE_MUTATION,
        NOTIFICATION_EDIT,
        OUTPUT_TYPE_EDIT,
        OWNER_REF_EDIT,
        PRODUCTION_SCHEDULER_ACTIVATION,
        RULE_DELETE,
        RULE_NAME_SCHEDULE_EDIT,
        RUN_NOW,
        SECOND_UPDATE_IMPLEMENTATION,
        TARGET_SOURCE_EDIT,
        TASK_EDIT,
    )

    app = create_app(Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"))
    patches = [
        r for r in app.routes
        if getattr(r, "path", None) == "/api/claw/automation/rules/{rule_id}"
    ]
    assert len(patches) == 1
    assert getattr(patches[0], "methods", set()) == {"PATCH"}
    assert RULE_NAME_SCHEDULE_EDIT is True
    assert TASK_EDIT is False
    assert EXECUTION_INTENT_EDIT is False
    assert OWNER_REF_EDIT is False
    assert TARGET_SOURCE_EDIT is False
    assert OUTPUT_TYPE_EDIT is False
    assert NOTIFICATION_EDIT is False
    assert ENABLED_EDIT is False
    assert RULE_DELETE is False
    assert RUN_NOW is False
    assert CRON_ACTIVATION is False
    assert PRODUCTION_SCHEDULER_ACTIVATION is False
    assert CROSS_TENANT_RULE_LOOKUP is False
    assert IN_PLACE_RULE_MUTATION is False
    assert SECOND_UPDATE_IMPLEMENTATION is False