"""#6460 — 자동화 규칙 소유자·멤버 격리 행렬 (시험 전용).

아스트라3 격리 스윕은 자동화를 "권한 없으면 닫힘" 한 줄로만 고정했다. 이 파일은
그 자리를 **세 사람의 행렬**로 채운다.

    A = 회사1 OWNER (규칙을 만든 사람)
    B = 회사2 OWNER (다른 회사, 자기 회사에서는 최고 권한 — 가장 센 상대)
    C = 회사1 MEMBER (같은 회사, 다른 사람, OWNER 아님)

각 사람은 자기 서명 세션 쿠키와 자기 B54 세션·멤버십을 갖는다. 즉 한 앱 안에서
쿠키만 바꾸는 것이 아니라 **서버가 각 사람에 대해 실제로 그렇게 답하는** 상태로
본다. 기대는 제품 코드 계약 그대로다:

- 쓰기(CREATE·EDIT·ENABLE)는 **OWNER 전용** — B·C는 403.
- 규칙 조회는 **테넌트 범위** — B는 A의 규칙을 목록에서도, ID로도 볼 수 없다(404).
  C는 같은 테넌트라 목록에서 본다(이것이 설계다: 격리 단위는 회사이고, 규칙은
  회사 자산이다). 다만 C는 그 규칙을 **바꿀 수 없다**.
- 삭제·즉시 실행 표면은 아예 없다(라우트 미등록) — 모든 사람에게 404.
- 응답 본문에 테넌트·주체·소유 증거가 실리지 않는다.

제품 코드는 건드리지 않는다. 결함이 보이면 이 파일이 아니라 보고로 남긴다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
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
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.claw_automation_rules_routes import WEB_RULE_KEYS
from app.config import Settings

LIST_PATH = "/api/claw/automation/rules"
B54_PRODUCT = "b54-padiem-claw"
REVISION = "d" * 40
RULE_ID_SHAPE = re.compile(r"^rule_[0-9a-f]{32}$")

# A(회사1 소유자) / B(회사2 소유자) / C(회사1 멤버)
TENANT_A = "tenant_" + "a" * 32
TENANT_B = "tenant_" + "b" * 32
SUBJECT_A, SUBJECT_B, SUBJECT_C = ("sub_" + ch * 32 for ch in "abc")
USER_A, USER_B, USER_C = ("usr_" + ch * 32 for ch in "123")


def _settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "automation-isolation.apps.googleusercontent.com",
        "google_client_secret": "automation-isolation-google-secret",
        "session_secret": "automation-isolation-session-secret-00",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


def _snapshot(
    *, tenant_id: str, subject_id: str,
    product_id: str = B54_PRODUCT, session_id: str = "b54session123",
) -> AuthSessionSnapshot:
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id=session_id,
        product_id=product_id,
        subject=CanonicalSubjectRef(SubjectType.USER, subject_id),
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
        tenant_id=tenant_id,
    )


def _membership(*, tenant_id: str, subject_id: str, role: TenantMembershipRole) -> TenantMembership:
    return TenantMembership(
        tenant_id=tenant_id, canonical_subject_id=subject_id, role=role
    )


def _authority(
    *, tenant_id: str, subject_id: str, role: TenantMembershipRole, session_id: str
) -> MagicMock:
    """한 사람의 Control Plane 답변 세 가지.

    - ``resolve_auth_session``: 목록 라우트의 테넌트 해석(#3237이 재사용하는 기존
      계약 — 사본 포인터와 세션 ID·주체·리비전·ACTIVE가 모두 맞아야 통과).
    - ``resolve_current_auth_session``: 쓰기 라우트의 현재 B54 세션.
    - ``resolve_active_tenant_membership``: 정확한 테넌트+주체의 ACTIVE 멤버십.
    """

    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(
        return_value=_snapshot(
            tenant_id=tenant_id, subject_id=subject_id,
            product_id=PADIEM_CHAT_PRODUCT_ID, session_id=session_id,
        )
    )
    authority.resolve_current_auth_session = AsyncMock(
        return_value=_snapshot(
            tenant_id=tenant_id, subject_id=subject_id, session_id=session_id
        )
    )
    authority.resolve_active_tenant_membership = AsyncMock(
        return_value=_membership(tenant_id=tenant_id, subject_id=subject_id, role=role)
    )
    return authority


def _shadow_store(*, user_id: str, subject_id: str, session_id: str) -> MagicMock:
    """그 사람의 식별 사본 — 목록 라우트의 테넌트 해석 전제조건."""

    now = datetime.now(timezone.utc)
    store = MagicMock()
    store.load_projection = AsyncMock(return_value=IdentityShadowRecord(
        product_user_id=user_id,
        canonical_subject_id=subject_id,
        auth_session_id=session_id,
        session_revision=1,
        session_state="active",
        session_expires_at=now + timedelta(hours=1),
        observed_at=now,
    ))
    return store


class _TargetAuthority:
    """서버가 서빙 중인 git 리비전 — 실행 의도를 만드는 데만 쓰인다."""

    class _Tag:
        def __init__(self) -> None:
            self.tag = f"git-{REVISION}"
            self.id = "version-id-1"

    CF_VERSION_METADATA = _Tag()


class _TenantRuleStore:
    """테넌트별 규칙 저장소 — 실제 D1 스토어와 같은 조회 경계를 흉내낸다.

    ``get_rule(rule_id, tenant_id)``는 **그 테넌트에 있는 규칙만** 돌려준다.
    그래서 다른 회사의 규칙 ID는 "없음"과 구분되지 않는다(404).
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], ClawAutomationRule] = {}
        self.list_calls: list[str] = []

    async def list_rules(self, workspace_id: str) -> list[ClawAutomationRule]:
        self.list_calls.append(workspace_id)
        return [rule for (tenant, _), rule in self.rows.items() if tenant == workspace_id]

    async def save_rule(self, rule: ClawAutomationRule) -> None:
        self.rows[(rule.workspace_id, rule.rule_id)] = rule

    async def get_rule(self, rule_id: str, workspace_id: str) -> ClawAutomationRule | None:
        return self.rows.get((workspace_id, rule_id))

    async def update_rule(self, rule: ClawAutomationRule) -> None:
        self.rows[(rule.workspace_id, rule.rule_id)] = rule

    async def set_rule_enabled(
        self, workspace_id: str, rule_id: str, enabled: bool
    ) -> ClawAutomationRule | None:
        rule = self.rows.get((workspace_id, rule_id))
        if rule is None:
            return None
        updated = self.rows[(workspace_id, rule_id)] = ClawAutomationRule(
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
        return updated


def _client(
    store: _TenantRuleStore, *, user_id: str, authority: MagicMock, shadow: MagicMock
) -> TestClient:
    app = create_app(
        settings=_settings(), history_store=MagicMock(), claw_automation_store=store
    )
    app.state.identity_shadow_store = shadow
    app.state.control_plane_identity_authority = authority
    app.state.claw_automation_execution_target_authority = _TargetAuthority()
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), user_id),
        domain="chat.example.test",
        path="/",
    )
    return client


@pytest.fixture()
def actors():
    """(저장소, A, B, C) — 각자 자기 세션·멤버십을 가진 세 클라이언트."""

    store = _TenantRuleStore()
    a = _client(
        store, user_id=USER_A,
        authority=_authority(tenant_id=TENANT_A, subject_id=SUBJECT_A,
                             role=TenantMembershipRole.OWNER, session_id="session_a"),
        shadow=_shadow_store(user_id=USER_A, subject_id=SUBJECT_A,
                             session_id="session_a"),
    )
    b = _client(
        store, user_id=USER_B,
        authority=_authority(tenant_id=TENANT_B, subject_id=SUBJECT_B,
                             role=TenantMembershipRole.OWNER, session_id="session_b"),
        shadow=_shadow_store(user_id=USER_B, subject_id=SUBJECT_B,
                             session_id="session_b"),
    )
    c = _client(
        store, user_id=USER_C,
        authority=_authority(tenant_id=TENANT_A, subject_id=SUBJECT_C,
                             role=TenantMembershipRole.OPERATOR, session_id="session_c"),
        shadow=_shadow_store(user_id=USER_C, subject_id=SUBJECT_C,
                             session_id="session_c"),
    )
    return store, a, b, c


def _rule_body(name: str = "아침 알림 요약") -> dict:
    return {
        "name": name,
        "task": "매일 아침 어제의 알림을 요약해서 알려줘.",
        "schedule_kind": "daypart",
        "schedule_expression": "morning",
        "schedule_timezone": "UTC",
        "target_source": "memory",
        "output_type": "alert",
    }


def _create_rule(client: TestClient, name: str = "아침 알림 요약") -> str:
    created = client.post(LIST_PATH, json=_rule_body(name))
    assert created.status_code == 201, created.text
    rule_id = created.json()["rule"]["rule_id"]
    assert RULE_ID_SHAPE.fullmatch(rule_id)
    return rule_id


EDIT_PATH = LIST_PATH + "/{rule_id}"
ENABLED_PATH = LIST_PATH + "/{rule_id}/enabled"
RUN_PATH = LIST_PATH + "/{rule_id}/run"


def _edit_body() -> dict:
    return {
        "name": "아침 알림 요약 (수정)",
        "schedule_kind": "daypart",
        "schedule_expression": "evening",
        "schedule_timezone": "UTC",
    }


# ── 생성: OWNER만 ───────────────────────────────────────────────────────────

def test_create_lands_only_in_the_callers_own_tenant(actors):
    store, a, b, c = actors

    # A(회사1 소유자)는 자기 회사에 만든다.
    assert a.post(LIST_PATH, json=_rule_body()).status_code == 201
    # B(회사2 소유자)도 자기 회사에서는 소유자다 — 자기 회사에 만드는 것은 정상이고,
    # A의 회사에 들어갈 수 없어야 한다.
    assert b.post(LIST_PATH, json=_rule_body("B 자기 회사 규칙")).status_code == 201
    # C(같은 회사 멤버)는 소유자가 아니라 만들 수 없다.
    assert c.post(LIST_PATH, json=_rule_body("C 시도")).status_code == 403

    tenant_a_rules = [r for (tenant, _), r in store.rows.items() if tenant == TENANT_A]
    tenant_b_rules = [r for (tenant, _), r in store.rows.items() if tenant == TENANT_B]
    assert len(tenant_a_rules) == 1, "A의 회사에는 A가 만든 규칙 하나뿐이다"
    assert len(tenant_b_rules) == 1, "B의 규칙은 B의 회사에만 있다"
    assert tenant_b_rules[0].name == "B 자기 회사 규칙"
    assert all(r.name != "C 시도" for r in tenant_a_rules + tenant_b_rules)


# ── 목록: 테넌트 범위 ───────────────────────────────────────────────────────

def test_list_is_scoped_to_the_accounts_tenant(actors):
    store, a, b, c = actors
    rule_id = _create_rule(a)

    seen_a = a.get(LIST_PATH)
    assert seen_a.status_code == 200
    assert [row["rule_id"] for row in seen_a.json()["rules"]] == [rule_id]

    # B(다른 회사): 자기 회사 텐넌트만 조회된다 — A의 규칙이 없다.
    seen_b = b.get(LIST_PATH)
    assert seen_b.status_code == 200
    assert seen_b.json()["rules"] == []
    assert rule_id not in seen_b.text
    # B가 읽은 곳은 B의 회사뿐이다 — A의 회사는 한 번도 열리지 않았다.
    assert TENANT_B in store.list_calls

    # C(같은 회사 멤버): 회사 자산이라 목록에서 본다 — 다만 쓰기는 못 한다(아래).
    seen_c = c.get(LIST_PATH)
    assert seen_c.status_code == 200
    assert [row["rule_id"] for row in seen_c.json()["rules"]] == [rule_id]
    for row in seen_c.json()["rules"]:
        assert set(row) == set(WEB_RULE_KEYS)
        # 테넌트·주체·소유 증거는 어느 계정에도 실리지 않는다.
        for secret in (TENANT_A, SUBJECT_A, USER_A, TENANT_B, SUBJECT_B, USER_B):
            assert secret not in seen_c.text


# ── 행렬: 읽기·수정·켜기·삭제·실행 ─────────────────────────────────────────

def test_matrix_edit_enable_delete_run_per_actor(actors):
    store, a, b, c = actors
    rule_id = _create_rule(a)

    # 읽기(단건) 표면은 없다 — 목록만 있다. 모든 계정에 같은 404.
    for client in (a, b, c):
        assert client.get(EDIT_PATH.format(rule_id=rule_id)).status_code in (404, 405)

    # 수정: A만 성공, B는 남의 회사 규칙(404), C는 같은 회사지만 OWNER가 아니라 403.
    assert a.patch(EDIT_PATH.format(rule_id=rule_id), json=_edit_body()).status_code == 200
    assert a.get(LIST_PATH).json()["rules"][0]["name"] == "아침 알림 요약 (수정)"
    assert b.patch(EDIT_PATH.format(rule_id=rule_id), json=_edit_body()).status_code == 404
    assert c.patch(EDIT_PATH.format(rule_id=rule_id), json=_edit_body()).status_code == 403
    # 거부는 아무것도 바꾸지 않는다.
    assert a.get(LIST_PATH).json()["rules"][0]["name"] == "아침 알림 요약 (수정)"

    # 켜기/끄기: 같은 행렬.
    assert a.patch(ENABLED_PATH.format(rule_id=rule_id), json={"enabled": False}).status_code == 200
    assert a.get(LIST_PATH).json()["rules"][0]["enabled"] is False
    assert b.patch(ENABLED_PATH.format(rule_id=rule_id), json={"enabled": True}).status_code == 404
    assert c.patch(ENABLED_PATH.format(rule_id=rule_id), json={"enabled": True}).status_code == 403
    assert a.get(LIST_PATH).json()["rules"][0]["enabled"] is False

    # 삭제·즉시 실행 표면은 라우트 자체가 없다 — 누구에게나 404/405.
    for client in (a, b, c):
        assert client.delete(EDIT_PATH.format(rule_id=rule_id)).status_code in (404, 405)
        assert client.post(RUN_PATH.format(rule_id=rule_id)).status_code in (404, 405)
    assert (TENANT_A, rule_id) in store.rows, "삭제 표면이 없으므로 규칙은 남아 있다"


def test_foreign_rule_id_behaves_exactly_like_a_missing_one(actors):
    store, a, b, c = actors
    rule_id = _create_rule(a)

    # B가 A의 규칙 ID를 알아도, 존재하지 않는 ID와 **같은 답**을 받는다.
    foreign = b.patch(EDIT_PATH.format(rule_id=rule_id), json=_edit_body())
    missing = b.patch(EDIT_PATH.format(rule_id="rule_" + "0" * 32), json=_edit_body())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()

    foreign_toggle = b.patch(ENABLED_PATH.format(rule_id=rule_id), json={"enabled": True})
    missing_toggle = b.patch(ENABLED_PATH.format(rule_id="rule_" + "0" * 32),
                             json={"enabled": True})
    assert foreign_toggle.status_code == missing_toggle.status_code == 404
    assert foreign_toggle.json() == missing_toggle.json()
    # A의 규칙은 그대로다.
    assert a.get(LIST_PATH).json()["rules"][0]["rule_id"] == rule_id


def test_member_without_owner_role_cannot_reach_any_mutation(actors):
    _store, a, c = actors[0], actors[1], actors[3]
    rule_id = _create_rule(a)

    for response in (
        c.post(LIST_PATH, json=_rule_body("C 생성")),
        c.patch(EDIT_PATH.format(rule_id=rule_id), json=_edit_body()),
        c.patch(ENABLED_PATH.format(rule_id=rule_id), json={"enabled": False}),
    ):
        assert response.status_code == 403
        # 거부 응답이 역할·테넌트를 흘리지 않는다.
        assert "operator" not in response.text.lower()
        assert TENANT_A not in response.text
