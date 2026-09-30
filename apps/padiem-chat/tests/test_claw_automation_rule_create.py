"""#3257 — Web Automation Create: POST /api/claw/automation/rules.

The first real mutation surface. Network-free tests prove the authority chain
and the bounded failure modes:

    signed-in browser -> current active B54 canonical session (#3243, reused)
    -> exact ACTIVE tenant membership, role == OWNER (owner-only first policy)
    -> server-minted rule_id + opaque owner_ref
    -> #3252 server-owned execution intent (padiem-chat + served git revision)
    -> existing canonical rule helper -> existing D1 store (one save)
    -> existing safe Web projection (no tenant/subject/owner_ref/intent/task)

Specifically fail-closed on: signed-out (401), no current B54 session (403),
foreign product session (403), membership that is not exactly this
tenant+subject ACTIVE OWNER (403: viewer/operator/approver all denied), any
caller authority key or unknown key (400), malformed/oversized body
(400/413), missing/malformed served version metadata (503 AND zero saves),
store unavailable/failed (503 AND zero committed rules), and credential-shaped
name/task (400). Success saves EXACTLY once and responds with the existing
safe projection only.
"""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from kagent.claw_automation import ClawAutomationRule
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
from padiem_control_plane import AuthSessionSnapshot  # noqa: F401  (re-exported above)

LIST_PATH = "/api/claw/automation/rules"

SIGNED_IN_USER_ID = "usr_" + "7" * 32
TENANT_ID = "tenant_" + "a" * 32
CANONICAL_SUBJECT_ID = "sub_" + "c" * 32
OTHER_TENANT_ID = "tenant_" + "b" * 32
REVISION = "d" * 40
B54_PRODUCT = "b54-padiem-claw"

RULE_ID_SHAPE = re.compile(r"^rule_[0-9a-f]{32}$")
OWNER_REF_SHAPE = re.compile(r"^automation_owner_[0-9a-f]{32}$")


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
    tenant_id: str | None = TENANT_ID,
    subject_id: str = CANONICAL_SUBJECT_ID,
    state: AuthSessionState = AuthSessionState.ACTIVE,
) -> AuthSessionSnapshot:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="b54session123",
        product_id=product_id,
        subject=CanonicalSubjectRef(SubjectType.USER, subject_id),
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        state=state,
        revision=1,
        tenant_id=tenant_id,
    )


def _membership(role: TenantMembershipRole = TenantMembershipRole.OWNER) -> TenantMembership:
    return TenantMembership(
        tenant_id=TENANT_ID,
        canonical_subject_id=CANONICAL_SUBJECT_ID,
        role=role,
    )


def _authority(
    snapshot: AuthSessionSnapshot | None = None,
    membership: TenantMembership | None = None,
) -> MagicMock:
    authority = MagicMock()
    authority.resolve_current_auth_session = AsyncMock(
        return_value=snapshot if snapshot is not None else _b54_snapshot()
    )
    authority.resolve_active_tenant_membership = AsyncMock(
        return_value=membership if membership is not None else _membership()
    )
    return authority


class _ServedTagMetadata:
    def __init__(self, tag: str | None = None, *, with_tag: bool = True):
        if with_tag:
            self.tag = tag
        self.id = "version-id-1"


class _TargetAuthority:
    def __init__(self, tag: str | None = None, *, with_binding: bool = True, with_tag: bool = True):
        if with_binding:
            self.CF_VERSION_METADATA = _ServedTagMetadata(tag=tag, with_tag=with_tag)


class _RecordingStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.saved: list[ClawAutomationRule] = []
        self.save_calls = 0
        self.list_calls: list[str] = []
        self.fail = fail

    async def list_rules(self, workspace_id: str) -> list[ClawAutomationRule]:
        self.list_calls.append(workspace_id)
        return []

    async def save_rule(self, rule) -> None:
        self.save_calls += 1
        if self.fail:
            raise RuntimeError("storage unavailable")
        self.saved.append(rule)


def _valid_body() -> dict:
    return {
        "name": "아침 알림 요약",
        "task": "매일 아침 어제의 알림을 요약해서 알려줘.",
        "schedule_kind": "daypart",
        "schedule_expression": "morning",
        "schedule_timezone": "Asia/Seoul",
        "target_source": "memory",
        "output_type": "alert",
    }


_UNSET = object()


def _client(
    store: _RecordingStore,
    *,
    authority: MagicMock | None = None,
    target: object | None = _UNSET,
    user_id: str | None = SIGNED_IN_USER_ID,
    store_unavailable: bool = False,
) -> TestClient:
    app = create_app(
        settings=_settings(),
        history_store=MagicMock(),
        claw_automation_store=None if store_unavailable else store,
    )
    app.state.control_plane_identity_authority = (
        authority if authority is not None else _authority()
    )
    if target is not _UNSET:
        app.state.claw_automation_execution_target_authority = target
    else:
        app.state.claw_automation_execution_target_authority = _TargetAuthority(
            tag=f"git-{REVISION}"
        )
    client = TestClient(app, base_url="https://chat.example.test")
    if user_id:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_settings(), user_id),
            domain="chat.example.test",
            path="/",
        )
    return client


def _post(client: TestClient, body: object | None = None, *, raw: bytes | None = None):
    if raw is not None:
        return client.post(
            LIST_PATH,
            content=raw,
            headers={"Content-Type": "application/json"},
        )
    return client.post(LIST_PATH, json=_valid_body() if body is None else body)


# ── auth / identity chain ───────────────────────────────────────────────────


def test_signed_out_gets_401_and_never_touches_the_store() -> None:
    store = _RecordingStore()
    resp = _post(_client(store, user_id=None))
    assert resp.status_code == 401
    assert store.save_calls == 0


def test_no_current_b54_session_fails_closed_without_save() -> None:
    store = _RecordingStore()
    authority = _authority()
    authority.resolve_current_auth_session = AsyncMock(
        return_value=_b54_snapshot(state=AuthSessionState.REVOKED)
    )
    resp = _post(_client(store, authority=authority))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "current_b54_session_unavailable"
    assert store.save_calls == 0


def test_foreign_product_session_fails_closed() -> None:
    store = _RecordingStore()
    authority = _authority(snapshot=_b54_snapshot(product_id="b62"))
    resp = _post(_client(store, authority=authority))
    assert resp.status_code == 403
    assert store.save_calls == 0


@pytest.mark.parametrize("role", [TenantMembershipRole.VIEWER, TenantMembershipRole.OPERATOR, TenantMembershipRole.APPROVER])
def test_non_owner_roles_are_denied_403(role: TenantMembershipRole) -> None:
    store = _RecordingStore()
    resp = _post(_client(store, authority=_authority(membership=_membership(role))))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "owner_role_required"
    # The bounded denial must not disclose the caller's own role either.
    assert role.value not in resp.text
    assert store.save_calls == 0


def test_membership_for_a_foreign_tenant_is_denied() -> None:
    store = _RecordingStore()
    membership = TenantMembership(
        tenant_id=OTHER_TENANT_ID,
        canonical_subject_id=CANONICAL_SUBJECT_ID,
        role=TenantMembershipRole.OWNER,
    )
    resp = _post(_client(store, authority=_authority(membership=membership)))
    assert resp.status_code == 403
    assert store.save_calls == 0
    assert OTHER_TENANT_ID not in resp.text


def test_membership_for_a_foreign_subject_is_denied() -> None:
    store = _RecordingStore()
    membership = TenantMembership(
        tenant_id=TENANT_ID,
        canonical_subject_id="sub_" + "e" * 32,
        role=TenantMembershipRole.OWNER,
    )
    resp = _post(_client(store, authority=_authority(membership=membership)))
    assert resp.status_code == 403
    assert store.save_calls == 0


# ── body bound + caller authority fields ────────────────────────────────────


@pytest.mark.parametrize(
    "field",
    [
        "rule_id",
        "workspace_id",
        "tenant_id",
        "canonical_subject_id",
        "owner_ref",
        "repository_ref",
        "exact_revision",
        "revision",
        "sha",
        "branch",
        "ref",
        "version_tag",
        "version_id",
        "product_id",
        "member_id",
        "role",
        "enabled",
        "notification_channels",
        "execution_intent",
        "execution_mode",
        "definitely_unknown_key",
    ],
)
def test_caller_authority_and_unknown_keys_are_rejected_400(field: str) -> None:
    store = _RecordingStore()
    body = _valid_body()
    body[field] = "caller_attempted_value"
    resp = _post(_client(store), body=body)
    assert resp.status_code == 400
    # Raw rejected input is never echoed.
    assert "caller_attempted_value" not in resp.text
    assert store.save_calls == 0


def test_missing_key_is_rejected_400() -> None:
    store = _RecordingStore()
    body = _valid_body()
    del body["schedule_timezone"]
    resp = _post(_client(store), body=body)
    assert resp.status_code == 400
    assert store.save_calls == 0


def test_malformed_and_non_object_bodies_are_rejected_400() -> None:
    store = _RecordingStore()
    client = _client(store)
    for raw in (b"{not json", b'["a"]', b'"text"', b""):
        resp = _post(client, raw=raw)
        assert resp.status_code == 400
    assert store.save_calls == 0


def test_oversized_body_is_bounded_413() -> None:
    store = _RecordingStore()
    client = _client(store)
    resp = client.post(
        LIST_PATH,
        content=b'{"name":"' + b"x" * (33 * 1024) + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413
    assert store.save_calls == 0


# ── execution-target runtime authority ──────────────────────────────────────


def test_missing_version_metadata_fails_503_and_never_saves() -> None:
    store = _RecordingStore()
    resp = _post(_client(store, target=_TargetAuthority(with_binding=False)))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "automation_execution_target_unavailable"
    assert store.save_calls == 0


def test_malformed_served_tag_fails_503_and_never_saves() -> None:
    store = _RecordingStore()
    for bad_tag in ("main", "HEAD", "git-" + "a" * 7, "git-" + "A" * 40, "git-" + REVISION + " "):
        resp = _post(_client(store, target=_TargetAuthority(tag=bad_tag)))
        assert resp.status_code == 503, bad_tag
        assert resp.json()["error"]["code"] == "automation_execution_target_unavailable"
    assert store.save_calls == 0


def test_injected_authority_is_required_not_process_env() -> None:
    store = _RecordingStore()
    client = _client(store, target=None)
    resp = _post(client)
    assert resp.status_code == 503
    assert store.save_calls == 0


# ── persistence ─────────────────────────────────────────────────────────────


def test_store_unavailable_is_503_without_save() -> None:
    store = _RecordingStore()
    resp = _post(_client(store, store_unavailable=True))
    assert resp.status_code == 503
    assert store.save_calls == 0


def test_storage_failure_is_bounded_503_without_retry() -> None:
    store = _RecordingStore(fail=True)
    resp = _post(_client(store))
    assert resp.status_code == 503
    # No retry: exactly one save attempt, no second rule id.
    assert store.save_calls == 1


def test_success_saves_exactly_once_and_returns_201() -> None:
    store = _RecordingStore()
    resp = _post(_client(store))
    assert resp.status_code == 201
    assert resp.json()["ok"] is True
    assert store.save_calls == 1
    assert store.list_calls == []  # create does not read


# ── canonical rule construction ─────────────────────────────────────────────


def _saved_rule(**overrides) -> tuple[_RecordingStore, ClawAutomationRule]:
    store = _RecordingStore()
    authority = _authority(membership=overrides.pop("membership", None) or _membership())
    target = overrides.pop("target", None) or _TargetAuthority(tag=f"git-{REVISION}")
    resp = _post(_client(store, authority=authority, target=target))
    assert resp.status_code == 201
    assert len(store.saved) == 1
    return store, store.saved[0]


def test_workspace_and_subject_come_only_from_the_session() -> None:
    _, rule = _saved_rule()
    assert rule.workspace_id == TENANT_ID
    assert rule.canonical_subject_id == CANONICAL_SUBJECT_ID


def test_rule_id_is_server_minted() -> None:
    _, rule = _saved_rule()
    assert RULE_ID_SHAPE.fullmatch(rule.rule_id)


def test_owner_ref_is_server_minted_opaque_provenance_never_identity() -> None:
    _, rule = _saved_rule()
    assert OWNER_REF_SHAPE.fullmatch(rule.owner_ref)
    for identity in (SIGNED_IN_USER_ID, CANONICAL_SUBJECT_ID, TENANT_ID):
        assert identity not in rule.owner_ref
        assert rule.owner_ref != identity


def test_execution_intent_is_server_owned() -> None:
    _, rule = _saved_rule()
    assert rule.execution_intent is not None
    assert rule.execution_intent.repository_ref == "padiem-chat"
    assert rule.execution_intent.exact_revision == REVISION
    assert rule.execution_intent.task == "매일 아침 어제의 알림을 요약해서 알려줘."


def test_notification_is_web_alert_inbox_only_and_enabled_true() -> None:
    _, rule = _saved_rule()
    assert rule.enabled is True
    assert [c.channel.value for c in rule.notification_channels] == ["web_alert_inbox"]


# ── schedule / input validation ─────────────────────────────────────────────


@pytest.mark.parametrize("daypart", ["morning", "midday", "evening", "close_of_business"])
def test_daypart_matrix(daypart: str) -> None:
    store = _RecordingStore()
    body = _valid_body()
    body["schedule_expression"] = daypart
    assert _post(_client(store), body=body).status_code == 201


@pytest.mark.parametrize("interval", ["15m", "1h", "6h", "1d"])
def test_interval_matrix_valid(interval: str) -> None:
    store = _RecordingStore()
    body = _valid_body()
    body.update({"schedule_kind": "interval", "schedule_expression": interval})
    assert _post(_client(store), body=body).status_code == 201


@pytest.mark.parametrize("interval", ["30s", "45d", "abc", "0m"])
def test_interval_matrix_invalid(interval: str) -> None:
    store = _RecordingStore()
    body = _valid_body()
    body.update({"schedule_kind": "interval", "schedule_expression": interval})
    assert _post(_client(store), body=body).status_code == 400


def test_cron_valid_and_malformed() -> None:
    store = _RecordingStore()
    body = _valid_body()
    body.update({"schedule_kind": "cron", "schedule_expression": "0 9 * * *"})
    assert _post(_client(store), body=body).status_code == 201
    body["schedule_expression"] = "0 25 * * *"
    assert _post(_client(store), body=body).status_code == 400


@pytest.mark.parametrize(
    "bad_timezone",
    ["Asia Seoul", ".Asia/Seoul", "-Asia/Seoul", "Asia/Seoul; drop", "Mars/Olympus 2050", ""],
)
def test_invalid_timezone_is_400(bad_timezone: str) -> None:
    store = _RecordingStore()
    body = _valid_body()
    body["schedule_timezone"] = bad_timezone
    resp = _post(_client(store), body=body)
    assert resp.status_code == 400
    assert store.save_calls == 0


def test_invalid_target_and_output_are_400() -> None:
    store = _RecordingStore()
    for field, value in (
        ("target_source", "shell_command"),
        ("output_type", "email_blast"),
    ):
        body = _valid_body()
        body[field] = value
        assert _post(_client(store), body=body).status_code == 400
    assert store.save_calls == 0


def test_credential_shaped_task_and_name_are_400() -> None:
    store = _RecordingStore()
    task_body = _valid_body()
    task_body["task"] = "use api_key = supersecretvalue123 when running"
    resp = _post(_client(store), body=task_body)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_task"
    name_body = _valid_body()
    name_body["name"] = "token = hunter2 schedule"
    resp = _post(_client(store), body=name_body)
    assert resp.status_code == 400
    assert store.save_calls == 0


# ── response privacy ────────────────────────────────────────────────────────


def test_success_response_is_exactly_the_safe_rule_projection() -> None:
    store = _RecordingStore()
    resp = _post(_client(store))
    payload = resp.json()
    assert set(payload) == {"ok", "rule"}
    assert set(payload["rule"]) == set(WEB_RULE_KEYS)
    serialized = resp.text
    for secret in (
        TENANT_ID,
        CANONICAL_SUBJECT_ID,
        SIGNED_IN_USER_ID,
        REVISION,
        "automation_owner_",
        "padiem-chat",
        "매일 아침 어제의 알림을 요약해서 알려줘.",
    ):
        assert secret not in serialized


def test_created_rule_is_background_eligible_in_projection() -> None:
    store = _RecordingStore()
    row = _post(_client(store)).json()["rule"]
    assert row["authority_status"] == "canonical"
    assert row["background_eligible"] is True
    assert row["enabled"] is True


# ── route registration ──────────────────────────────────────────────────────


def test_create_route_is_registered_and_readonly_constants_hold() -> None:
    from app.claw_automation_rule_create_routes import (
        CREATE_ROLE_OWNER_ONLY,
        NEW_AUTOMATION_STORE,
        NEW_MIGRATION,
        NEW_SCHEMA,
        RULE_CREATE,
        RULE_DELETE,
        RULE_ENABLE_DISABLE,
        RULE_UPDATE,
        RUN_NOW,
    )

    app = create_app(Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"))
    posts = [
        r
        for r in app.routes
        if getattr(r, "path", None) == LIST_PATH
        and "POST" in getattr(r, "methods", set())
    ]
    assert len(posts) == 1
    assert RULE_CREATE is True
    assert RULE_UPDATE is False
    assert RULE_DELETE is False
    assert RULE_ENABLE_DISABLE is False
    assert RUN_NOW is False
    assert CREATE_ROLE_OWNER_ONLY is True
    assert NEW_AUTOMATION_STORE is False
    assert NEW_SCHEMA is False
    assert NEW_MIGRATION is False
