"""#3262 — OWNER-gated enable/disable for a canonical automation rule.

Network-free tests over PATCH /api/claw/automation/rules/{rule_id}/enabled,
built on the same harness as the #3257 Create suite (the authority helper is
now shared, so the identity chain is exercised through both surfaces).

Proven fail-closed on: signed-out (401), no current B54 session (403),
viewer/operator/approver (403, no role disclosure), non-JSON-boolean enabled
values (400), unknown/missing keys and malformed/oversized bodies (400/413),
malformed rule id and unknown/foreign rules (bounded 404 with tenant-scoped
lookup only), legacy/quarantined rows (409, zero writes), enabling a rule that
lacks owner_ref or execution_intent (409, zero writes), and store failures
(bounded 503 with no retry).

Proven on success: exactly one set_rule_enabled write, all other rule fields
preserved by the existing store contract, and a response that carries only the
existing safe Web projection.
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

ENABLED_PATH = "/api/claw/automation/rules/{}/enabled"
SIGNIN_USER_ID = "usr_" + "7" * 32
TENANT_ID = "tenant_" + "a" * 32
OTHER_TENANT_ID = "tenant_" + "b" * 32
CANONICAL_SUBJECT_ID = "sub_" + "c" * 32
REVISION = "d" * 40
B54_PRODUCT = "b54-padiem-claw"


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


def _b54_snapshot(
    *,
    product_id: str = B54_PRODUCT,
    state: AuthSessionState = AuthSessionState.ACTIVE,
) -> AuthSessionSnapshot:
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
        tenant_id=TENANT_ID,
        canonical_subject_id=CANONICAL_SUBJECT_ID,
        role=role,
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
    enabled: bool = True,
    owner_ref: str | None = "automation_owner_" + "1" * 32,
    execution_intent: ClawAutomationExecutionIntent | None = None,
    canonical_subject_id: str | None = CANONICAL_SUBJECT_ID,
) -> ClawAutomationRule:
    return ClawAutomationRule(
        rule_id=rule_id,
        workspace_id=workspace_id,
        name="아침 알림 요약",
        schedule=ClawScheduleExpression(
            kind=ClawScheduleKind.DAYPART, expression="morning", timezone="UTC"
        ),
        target_source=ClawAutomationTarget.MEMORY,
        output_type=ClawAutomationOutputType.ALERT,
        enabled=enabled,
        notification_channels=(
            ClawNotificationPreference(channel=ClawNotificationChannel.WEB_ALERT_INBOX),
        ),
        owner_ref=owner_ref,
        canonical_subject_id=canonical_subject_id,
        execution_intent=execution_intent if execution_intent is not None else _intent(),
    )


class _RecordingStore:
    """Tenant-scoped fake over the EXISTING store contract surface."""

    def __init__(self, rules: list[ClawAutomationRule] | None = None, *, fail: bool = False):
        self.rules = {rule.rule_id: rule for rule in (rules or [])}
        self.get_rule_calls: list[tuple[str, str]] = []
        self.set_enabled_calls: list[tuple[str, str, bool]] = []
        self.save_rule_calls: list[ClawAutomationRule] = []
        self.fail = fail

    async def list_rules(self, workspace_id: str) -> list[ClawAutomationRule]:
        return [rule for rule in self.rules.values() if rule.workspace_id == workspace_id]

    async def get_rule(self, rule_id: str, workspace_id: str) -> ClawAutomationRule | None:
        self.get_rule_calls.append((rule_id, workspace_id))
        rule = self.rules.get(rule_id)
        if rule is None or rule.workspace_id != workspace_id:
            return None
        return rule

    async def set_rule_enabled(self, workspace_id: str, rule_id: str, enabled: bool) -> ClawAutomationRule:
        self.set_enabled_calls.append((workspace_id, rule_id, enabled))
        if self.fail:
            raise RuntimeError("storage unavailable")
        rule = await self.get_rule(rule_id, workspace_id)
        assert rule is not None
        updated = ClawAutomationRule(
            rule_id=rule.rule_id,
            workspace_id=rule.workspace_id,
            name=rule.name,
            schedule=rule.schedule,
            target_source=rule.target_source,
            output_type=rule.output_type,
            enabled=enabled,
            notification_channels=rule.notification_channels,
            owner_ref=rule.owner_ref,
            execution_intent=rule.execution_intent,
            canonical_subject_id=rule.canonical_subject_id,
        )
        # The existing store persists through save_rule; the write accounting
        # below must see exactly one such write.
        self.save_rule_calls.append(updated)
        self.rules[rule_id] = updated
        return updated


def _client(store, *, authority=None, user_id: str | None = SIGNIN_USER_ID) -> TestClient:
    app = create_app(
        settings=_settings(), history_store=MagicMock(), claw_automation_store=store
    )
    app.state.control_plane_identity_authority = (
        authority if authority is not None else _authority()
    )
    app.state.claw_automation_execution_target_authority = object()
    client = TestClient(app, base_url="https://chat.example.test")
    if user_id:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_settings(), user_id),
            domain="chat.example.test",
            path="/",
        )
    return client


def _toggle(client: TestClient, rule_id: str = "rule_1", *, enabled: object = True, raw: bytes | None = None):
    if raw is not None:
        return client.patch(
            ENABLED_PATH.format(rule_id),
            content=raw,
            headers={"Content-Type": "application/json"},
        )
    return client.patch(ENABLED_PATH.format(rule_id), json={"enabled": enabled})


# ── auth / identity ─────────────────────────────────────────────────────────


def test_signed_out_toggle_is_401() -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _toggle(_client(store, user_id=None))
    assert resp.status_code == 401
    assert store.set_enabled_calls == []


def test_no_current_b54_session_fails_closed() -> None:
    store = _RecordingStore([_rule("rule_1")])
    authority = _authority(snapshot=_b54_snapshot(state=AuthSessionState.REVOKED))
    resp = _toggle(_client(store, authority=authority))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "current_b54_session_unavailable"
    assert store.set_enabled_calls == []


def test_foreign_product_session_fails_closed() -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _toggle(_client(store, authority=_authority(snapshot=_b54_snapshot(product_id="b62"))))
    assert resp.status_code == 403
    assert store.set_enabled_calls == []


@pytest.mark.parametrize(
    "role",
    [TenantMembershipRole.VIEWER, TenantMembershipRole.OPERATOR, TenantMembershipRole.APPROVER],
)
def test_non_owner_roles_are_denied_403(role: TenantMembershipRole) -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _toggle(_client(store, authority=_authority(membership=_membership(role))))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "owner_role_required"
    assert role.value not in resp.text
    assert store.set_enabled_calls == []


# ── body contract ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("flag", [True, False])
def test_json_boolean_enabled_is_accepted(flag: bool) -> None:
    store = _RecordingStore([_rule("rule_1", enabled=not flag)])
    resp = _toggle(_client(store), enabled=flag)
    assert resp.status_code == 200
    assert resp.json()["rule"]["enabled"] is flag


@pytest.mark.parametrize("bad", ["true", "false", 1, 0, None, [], {}])
def test_non_boolean_enabled_is_400(bad: object) -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _toggle(_client(store), enabled=bad)
    assert resp.status_code == 400
    assert store.set_enabled_calls == []


def test_unknown_and_missing_keys_are_400() -> None:
    store = _RecordingStore([_rule("rule_1")])
    client = _client(store)
    for body in (
        {"enabled": True, "reason": "because"},
        {"enabled": True, "workspace_id": TENANT_ID},
        {"enabled": True, "owner_ref": "caller_owned"},
        {"enabled": True, "execution_intent": {"task": "x"}},
        {"enabled": True, "revision": REVISION},
        {},
    ):
        resp = client.patch(ENABLED_PATH.format("rule_1"), json=body)
        assert resp.status_code == 400, body
        assert "caller_owned" not in resp.text
    assert store.set_enabled_calls == []


def test_malformed_and_oversized_bodies_are_bounded() -> None:
    store = _RecordingStore([_rule("rule_1")])
    client = _client(store)
    assert client.patch(
        ENABLED_PATH.format("rule_1"),
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    ).status_code == 400
    oversized = client.patch(
        ENABLED_PATH.format("rule_1"),
        content=b'{"enabled": true, "pad": "' + b"x" * (5 * 1024) + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
    assert store.set_enabled_calls == []


def test_malformed_rule_id_is_bounded_rejected() -> None:
    store = _RecordingStore([_rule("rule_1")])
    client = _client(store)
    for bad in ("rule with spaces", "rule/../other", "-nope"):
        resp = _toggle(client, bad)
        assert resp.status_code in {400, 404}
    assert store.set_enabled_calls == []


# ── lookup scope ────────────────────────────────────────────────────────────


def test_unknown_rule_is_bounded_404() -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _toggle(_client(store), "rule_missing")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "automation_rule_not_found"
    assert store.set_enabled_calls == []


def test_foreign_tenant_rule_is_indistinguishable_404() -> None:
    store = _RecordingStore([_rule("rule_foreign", workspace_id=OTHER_TENANT_ID)])
    resp = _toggle(_client(store), "rule_foreign")
    assert resp.status_code == 404
    assert store.set_enabled_calls == []
    # Every lookup used the session's tenant only — no cross-tenant probe.
    assert store.get_rule_calls and all(call[1] == TENANT_ID for call in store.get_rule_calls)


def test_lookup_never_checks_another_tenant() -> None:
    store = _RecordingStore([_rule("rule_1")])
    _toggle(_client(store), "rule_missing")
    assert {call[1] for call in store.get_rule_calls} == {TENANT_ID}


# ── legacy / quarantine ─────────────────────────────────────────────────────


def test_legacy_missing_subject_is_409_without_write() -> None:
    store = _RecordingStore([_rule("rule_legacy", canonical_subject_id=None)])
    resp = _toggle(_client(store), "rule_legacy")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "automation_rule_not_mutable"
    assert store.set_enabled_calls == []
    assert store.save_rule_calls == []


def test_legacy_noncanonical_workspace_is_409_without_write() -> None:
    store = _RecordingStore(
        [_rule("rule_legacyws", workspace_id="workspace_legacy", canonical_subject_id=CANONICAL_SUBJECT_ID)]
    )
    # The session tenant lookup cannot even see it -> same bounded 404.
    resp = _toggle(_client(store), "rule_legacyws")
    assert resp.status_code in {404, 409}
    assert store.set_enabled_calls == []


# ── enabling requires execution readiness ────────────────────────────────────


def test_missing_owner_ref_cannot_be_enabled_409_zero_write() -> None:
    store = _RecordingStore([_rule("rule_norefs", owner_ref=None)])
    resp = _toggle(_client(store), "rule_norefs", enabled=True)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "automation_rule_not_execution_ready"
    assert store.set_enabled_calls == []


def test_missing_execution_intent_cannot_be_enabled_409_zero_write() -> None:
    store = _RecordingStore([_rule("rule_nointent")])
    # Build a canonical rule without an execution intent through the store
    # contract (the dataclass keeps it optional for legacy rows).
    rule = ClawAutomationRule(
        rule_id="rule_nointent",
        workspace_id=TENANT_ID,
        name="아침 알림 요약",
        schedule=ClawScheduleExpression(
            kind=ClawScheduleKind.DAYPART, expression="morning", timezone="UTC"
        ),
        target_source=ClawAutomationTarget.MEMORY,
        output_type=ClawAutomationOutputType.ALERT,
        enabled=True,
        owner_ref="automation_owner_" + "2" * 32,
        canonical_subject_id=CANONICAL_SUBJECT_ID,
    )
    store.rules[rule.rule_id] = rule
    resp = _toggle(_client(store), "rule_nointent", enabled=True)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "automation_rule_not_execution_ready"
    assert store.set_enabled_calls == []


def test_canonical_incomplete_rule_can_still_be_disabled() -> None:
    store = _RecordingStore([_rule("rule_norefs", owner_ref=None, enabled=True)])
    resp = _toggle(_client(store), "rule_norefs", enabled=False)
    assert resp.status_code == 200
    assert resp.json()["rule"]["enabled"] is False
    assert len(store.set_enabled_calls) == 1


# ── persistence and preservation ─────────────────────────────────────────────


def test_success_writes_exactly_once_and_preserves_every_field() -> None:
    original = _rule("rule_1", enabled=True)
    store = _RecordingStore([original])
    resp = _toggle(_client(store), "rule_1", enabled=False)
    assert resp.status_code == 200
    assert len(store.set_enabled_calls) == 1
    assert store.set_enabled_calls[0][0] == TENANT_ID
    assert len(store.save_rule_calls) == 1
    updated = store.save_rule_calls[0]
    assert updated.enabled is False
    assert updated.owner_ref == original.owner_ref
    assert updated.execution_intent == original.execution_intent
    assert updated.canonical_subject_id == original.canonical_subject_id
    assert updated.schedule == original.schedule
    assert updated.target_source == original.target_source
    assert updated.output_type == original.output_type
    assert updated.notification_channels == original.notification_channels
    assert updated.name == original.name


def test_toggle_never_mints_owner_ref_or_execution_intent() -> None:
    store = _RecordingStore([_rule("rule_norefs", owner_ref=None)])
    _toggle(_client(store), "rule_norefs", enabled=False)
    updated = store.save_rule_calls[0]
    assert updated.owner_ref is None
    assert updated.execution_intent is not None  # unchanged, not rebuilt


def test_store_failure_is_503_without_retry() -> None:
    store = _RecordingStore([_rule("rule_1")], fail=True)
    resp = _toggle(_client(store), "rule_1", enabled=False)
    assert resp.status_code == 503
    assert len(store.set_enabled_calls) == 1  # no retry


def test_store_unavailable_is_503() -> None:
    store = _RecordingStore([_rule("rule_1")])
    app_client = _client(store)
    app_client.app.state.claw_automation_store = None
    resp = _toggle(app_client, "rule_1", enabled=False)
    assert resp.status_code == 503


# ── safe projection ─────────────────────────────────────────────────────────


def test_success_response_is_the_safe_projection_only() -> None:
    store = _RecordingStore([_rule("rule_1")])
    resp = _toggle(_client(store), "rule_1", enabled=False)
    payload = resp.json()
    assert set(payload) == {"ok", "rule"}
    assert set(payload["rule"]) == set(WEB_RULE_KEYS)
    for secret in (TENANT_ID, CANONICAL_SUBJECT_ID, "automation_owner_", REVISION, "padiem-chat", "Summarize overnight alerts"):
        assert secret not in resp.text


# ── route registration + slice constants ────────────────────────────────────


def test_route_is_registered_and_slice_is_toggle_only() -> None:
    from app.claw_automation_rule_enabled_routes import (
        CRON_ACTIVATION,
        CROSS_TENANT_RULE_LOOKUP,
        EXECUTION_INTENT_EDIT,
        LEGACY_RULE_MUTATION,
        NOTIFICATION_EDIT,
        OUTPUT_EDIT,
        OWNER_REF_EDIT,
        PRODUCTION_SCHEDULER_ACTIVATION,
        RULE_DELETE,
        RULE_EDIT_FIELDS,
        RULE_ENABLED_TOGGLE,
        RUN_NOW,
        SCHEDULE_EDIT,
        SECOND_UPDATE_IMPLEMENTATION,
        TARGET_EDIT,
    )

    app = create_app(Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"))
    patches = [
        r
        for r in app.routes
        if getattr(r, "path", None) == "/api/claw/automation/rules/{rule_id}/enabled"
    ]
    assert len(patches) == 1
    assert getattr(patches[0], "methods", set()) == {"PATCH"}
    assert RULE_ENABLED_TOGGLE is True
    assert RULE_EDIT_FIELDS is False
    assert RULE_DELETE is False
    assert RUN_NOW is False
    assert OWNER_REF_EDIT is False
    assert EXECUTION_INTENT_EDIT is False
    assert SCHEDULE_EDIT is False
    assert TARGET_EDIT is False
    assert OUTPUT_EDIT is False
    assert NOTIFICATION_EDIT is False
    assert CRON_ACTIVATION is False
    assert PRODUCTION_SCHEDULER_ACTIVATION is False
    assert CROSS_TENANT_RULE_LOOKUP is False
    assert LEGACY_RULE_MUTATION is False
    assert SECOND_UPDATE_IMPLEMENTATION is False