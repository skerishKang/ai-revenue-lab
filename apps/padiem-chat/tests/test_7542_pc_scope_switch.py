"""#7542 — pc_scope 전환 스위치: 꺼지면 교차 확인, 켜지면 단일 테넌트 확인.

비교 기록(method=pc_scope)은 두 상태에서 모두 남고, 켠 상태에서도 다른
테넌트·주체 불일치·세션 없음은 그대로 거부된다. 스위치는 요청 컨텍스트와
설정(기본 꺼짐)을 통해 전달된다.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import connector_account_subject as proof
from app.config import Settings

OWNER = "usr_" + "7" * 32
WORKSPACE = "tenant-7542"
ACCOUNT = "acct-7542"
SUBJECT = "sub-7542"


@contextmanager
def _switch(*, tenant_only: bool, key_mode: bool = False):
    token = proof._current.set(proof._RequestProof(
        key_mode=key_mode, pc_scope_tenant_only=tenant_only,
    ))
    try:
        yield
    finally:
        proof._current.reset(token)


def _request(identity):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=identity,
        identity_shadow_store=None,
    )))


class _Identity:
    def __init__(self):
        self.calls: list[str] = []

    async def resolve_connector_owner_scope(self, *, session_id):
        self.calls.append(session_id)
        return {"account_ref": ACCOUNT, "workspace_ref": "ws-connector"}


def _session(*, tenant=WORKSPACE, subject=SUBJECT, session_id="sess-b54"):
    return SimpleNamespace(
        session_id=session_id, tenant_id=tenant,
        subject=SimpleNamespace(subject_id=subject),
    )


def _b62(*, workspace=WORKSPACE, subject=SUBJECT):
    return workspace, SimpleNamespace(
        session_id="sess-b62", tenant_id=workspace,
        subject=SimpleNamespace(subject_id=subject),
    )


def _resolve(*, tenant_only, b62, b54):
    from app.pc_work_context import resolve_pc_connector_scope

    identity = _Identity()

    async def owner_session(_request, _owner_id):
        return b62

    async def b54_bridge(_identity, _user_id):
        return b54 if isinstance(b54, BaseException) else SimpleNamespace(auth_session=b54)

    with (
        _switch(tenant_only=tenant_only),
        patch("app.pc_work_context._resolve_owner_session", side_effect=owner_session),
        patch(
            "padiem_control_plane.b54_identity_bridge.resolve_current_b54_canonical_session",
            side_effect=b54_bridge,
        ),
    ):
        result = asyncio.run(resolve_pc_connector_scope(
            _request(identity), owner_id=OWNER, workspace_id=WORKSPACE,
        ))
    return result, identity


@pytest.mark.parametrize("tenant_only", [False, True])
def test_switch_off_and_on_agree_when_both_sessions_agree(tenant_only):
    result, identity = _resolve(
        tenant_only=tenant_only, b62=_b62(), b54=_session(),
    )
    assert result.ready is True
    assert result.session_id == "sess-b54"
    assert identity.calls == ["sess-b54"]


def test_switch_on_uses_the_single_tenant_verdict_when_b62_is_absent():
    result, identity = _resolve(
        tenant_only=True, b62=(None, None), b54=_session(),
    )
    assert result.ready is True
    assert identity.calls == ["sess-b54"]


def test_switch_off_still_denies_when_b62_is_absent():
    result, identity = _resolve(
        tenant_only=False, b62=(None, None), b54=_session(),
    )
    assert result.ready is False
    assert identity.calls == []


@pytest.mark.parametrize("tenant_only", [False, True])
@pytest.mark.parametrize("b54", [
    _session(tenant="tenant-other"),
    None,
])
def test_switch_rejects_other_tenant_and_absent_session(tenant_only, b54):
    result, identity = _resolve(
        tenant_only=tenant_only, b62=_b62(), b54=b54,
    )
    assert result.ready is False
    assert identity.calls == []


@pytest.mark.parametrize("tenant_only", [False, True])
def test_switch_rejects_subject_mismatch(tenant_only):
    result, identity = _resolve(
        tenant_only=tenant_only,
        b62=_b62(subject="sub-other"),
        b54=_session(),
    )
    assert result.ready is False
    assert identity.calls == []


@pytest.mark.parametrize("mode", ["agree", "b62_absent", "subject", "tenant", "session"])
def test_comparison_journal_stays_after_the_switch_is_on(capsys, mode):
    b62 = _b62(subject="sub-other" if mode == "subject" else SUBJECT)
    if mode == "b62_absent":
        b62 = (None, None)
    b54 = None if mode == "session" else _session(
        tenant="tenant-other" if mode == "tenant" else WORKSPACE,
    )
    _resolve(tenant_only=True, b62=b62, b54=b54)
    out = capsys.readouterr().out
    assert "method=pc_scope" in out
    expected = {
        "agree": "reason=match",
        "b62_absent": "reason=tenant_only_allow_b62_absent",
        "subject": "reason=tenant_only_allow_subject_mismatch",
        "tenant": "reason=match",
        "session": "reason=match",
    }[mode]
    assert expected in out
    for raw in (ACCOUNT, SUBJECT, "sess-b54", "sess-b62"):
        assert raw not in out


def test_switch_is_default_off_and_strict_bool():
    assert Settings.from_values().pc_scope_tenant_only_enabled is False
    assert Settings.from_values(
        pc_scope_tenant_only_enabled="true",
    ).pc_scope_tenant_only_enabled is True
    assert Settings.from_values(
        pc_scope_tenant_only_enabled="false",
    ).pc_scope_tenant_only_enabled is False
    with pytest.raises(Exception):
        Settings.from_values(pc_scope_tenant_only_enabled="maybe")


def test_worker_binding_projects_the_switch():
    from app.worker_config import settings_from_worker_bindings

    settings = settings_from_worker_bindings(SimpleNamespace(
        PADIEM_CHAT_PC_SCOPE_TENANT_ONLY_ENABLED="true",
    ))
    assert settings.pc_scope_tenant_only_enabled is True


def test_middleware_carries_the_switch():
    app = SimpleNamespace()
    seen: list[bool] = []

    async def inner(scope, receive, send):
        seen.append(proof.pc_scope_tenant_only_enabled())

    middleware = proof.ConnectorAccountShadowContextMiddleware(app, pc_scope_tenant_only=True)
    middleware.app = inner
    asyncio.run(middleware({"type": "http"}, None, None))
    assert seen == [True]
    assert proof.pc_scope_tenant_only_enabled() is False
