"""#8359 — 유지보수 소유자 판정: 관리 표시 + 링크 주인의 자동 업데이트 설정.

2026-11-24 결정: 페어링으로 연결한 관리 PC의 유지보수 허락은 관리자가 찍은
관리 표시와 그 링크 주인의 자동 업데이트 설정(#8204)이 켜져 있는 것으로 본다.
네이티브 커넥터 등록 동의 기록은 읽지 않는다. 거부 사유는 값 없는 닫힌 코드다.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app import pc_helper_maintenance_host as host
from app.pc_helper_registration import registration_command

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)
STAMP = NOW.isoformat()
SUB = "subject_fixture"
DEVICE = "node//fixture"
OWNER = "usr_fixture"
OTHER = "usr_other_fixture"
LINK_ID = "pclink_fixture"
SCOPE = {"owner_subject_id": SUB, "account_ref": "acct_fixture", "workspace_ref": "ws_fixture"}
LINK = {"link_id": LINK_ID, "user_id": OWNER, "mesh_node_id": DEVICE, "state": "active",
        "paused_at": None, "managed_at": STAMP, "managed_by": "usr_admin_fixture"}
PREFERENCE = {"link_id": LINK_ID, "mesh_node_id": DEVICE, "label": "label_fixture",
              "auto_helper_update": 1, "helper_update_dismissed_version": None}
MANIFEST = {"version": "0.3.0-rc2", "sha256": "a" * 64,
            "download_url": "https://downloads.padiem.net/pc-helper/0.3.0-rc2/padiem-user-helper.exe",
            "min_supported_version": "0.3.0-rc1"}
OBSERVATION = {"device_id": DEVICE, "received_at": STAMP, "state": {
    "helper_status_present": True, "helper_sha256": "b" * 64,
    "helper_version": "0.3.0-rc1", "updater_source_present": True,
    "updater_source_sha256": "c" * 64, "updater_task_present": True,
    "self_heal_task_present": True,
}}
ROLLOUT = {"initialized": True, "stage": "internal", "percent": 10,
           "stable": {**MANIFEST, "version": "0.3.0-rc1", "sha256": "b" * 64},
           "target": MANIFEST}
ENV = {"PADIEM_PC_HELPER_AUTO_UPDATE_ENABLED": "1"}
PRIVATE = (SUB, DEVICE, OWNER, OTHER, LINK_ID, "acct_fixture", "ws_fixture",
           "usr_admin_fixture", "label_fixture", "other_subject")


class Pairing:
    """Only the owner-scoped #8204 preference read the owner authority uses."""

    def __init__(self, rows=None):
        self.rows = {OWNER: [dict(PREFERENCE)]} if rows is None else rows
        self.reads = []

    async def list_helper_update_preferences(self, *, user_id):
        self.reads.append(user_id)
        answer = self.rows.get(user_id, [])
        return [dict(row) for row in answer] if isinstance(answer, list) else answer


def _request(pairing=None):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        control_plane_identity_authority=object(),
        pc_device_pairing_store=pairing if pairing is not None else Pairing())))


def _session():
    return SimpleNamespace(session_id="session_fixture",
                           subject=SimpleNamespace(subject_id=SUB))


def _facts(*links):
    return dict(device_id=DEVICE, managed_links=list(links) if links else [LINK],
                admin_now=True, online=True, observation=OBSERVATION, manifest=MANIFEST,
                rollout=ROLLOUT, now=NOW)


def _target(**changes):
    async def resolver(request, *, session, selected_device_id, user_id):
        assert (selected_device_id, user_id) == (DEVICE, OWNER)
        resolved = {"authorized": True, "account_ref": SCOPE["account_ref"],
                    "workspace_ref": SCOPE["workspace_ref"],
                    "target": {"node_ref": DEVICE, "device_id": DEVICE, "link_id": LINK_ID}}
        resolved.update({k: v for k, v in changes.items() if k != "target"})
        resolved["target"].update(changes.get("target", {}))
        return resolved, None
    return resolver


async def _unreachable(*args, **kwargs):
    raise AssertionError("the target resolver must not run after an owner refusal")


def _authorize(monkeypatch, caplog, request=None, *, scope=SCOPE, facts=None,
               resolver=None, report=None):
    reads = []

    async def read(identity, method, **kwargs):
        reads.append(method)
        # The decision removed the consent read: only the owner scope is asked.
        assert method == "owner_scope" and set(kwargs) == {"session_id"}
        return scope

    monkeypatch.setattr(host, "mode_connector_read", read)
    with caplog.at_level(logging.WARNING, logger=host.logger.name):
        result = asyncio.run(host._authorized(
            request or _request(), ENV, facts or _facts(), _session(), OWNER,
            resolver or _unreachable, report))
    assert reads == ["owner_scope"]
    return result


def test_managed_link_with_automatic_updates_on_is_admitted(caplog, monkeypatch):
    pairing = Pairing()
    report = {}
    intent, target, reason = _authorize(
        monkeypatch, caplog, _request(pairing), resolver=_target(), report=report)
    assert reason is None
    assert (intent.user_id, intent.link_id, intent.device_id) == (OWNER, LINK_ID, DEVICE)
    assert intent.action == "refresh" and intent.command == registration_command()
    assert target == {"node_ref": DEVICE, "device_id": DEVICE, "link_id": LINK_ID}
    # The setting was read for the managed link's own owner and nobody else.
    assert pairing.reads == [OWNER]
    assert report == {"owner_authority": "passed"}
    assert "pc_maintenance_owner_authority" not in caplog.text


def _link(**changes):
    return {**LINK, **changes}


def _rows(*rows):
    return Pairing({OWNER: list(rows)})


@pytest.mark.parametrize(("code", "outcome", "scope", "facts", "pairing"), [
    ("scope_missing", "owner_authority_denied", None, None, None),
    ("scope_missing", "owner_authority_denied", {**SCOPE, "workspace_ref": ""}, None, None),
    ("scope_missing", "owner_authority_denied", {**SCOPE, "account_ref": None}, None, None),
    ("scope_subject", "owner_authority_denied",
     {**SCOPE, "owner_subject_id": "other_subject"}, None, None),
    # 관리 표시 없음, 일시정지·해제(대체 포함)된 링크, 다른 계정·다른 PC의 링크.
    ("owner_managed_missing", "owner_authority_denied", SCOPE,
     _facts(_link(managed_at=None)), None),
    ("owner_managed_missing", "owner_authority_denied", SCOPE,
     _facts(_link(managed_by=None)), None),
    ("owner_managed_missing", "owner_authority_denied", SCOPE,
     _facts(_link(paused_at=STAMP)), None),
    ("owner_managed_missing", "owner_authority_denied", SCOPE,
     _facts(_link(state="revoked")), None),
    ("owner_managed_missing", "owner_authority_denied", SCOPE,
     _facts(_link(user_id=OTHER)), None),
    ("owner_managed_missing", "owner_authority_denied", SCOPE,
     _facts(_link(mesh_node_id="node//other")), None),
    ("owner_managed_missing", "owner_authority_denied", SCOPE,
     _facts(_link(link_id=None)), None),
    ("owner_managed_missing", "owner_authority_denied", SCOPE,
     _facts(LINK, _link(link_id="pclink_second")), None),
    ("owner_managed_missing", "owner_authority_denied", SCOPE,
     {**_facts(), "managed_links": []}, None),
    # 주인 자신의 목록이 이 링크를 정확히 가리키지 않으면 기본값(켜짐)으로 보지 않는다.
    ("owner_setting_missing", "owner_authority_denied", SCOPE, None, _rows()),
    ("owner_setting_missing", "owner_authority_denied", SCOPE, None,
     _rows({**PREFERENCE, "link_id": "pclink_second"})),
    ("owner_setting_missing", "owner_authority_denied", SCOPE, None,
     _rows({**PREFERENCE, "mesh_node_id": "node//other"})),
    ("owner_setting_missing", "owner_authority_denied", SCOPE, None,
     _rows(PREFERENCE, PREFERENCE)),
    ("owner_setting_invalid", "owner_authority_denied", SCOPE, None,
     Pairing({OWNER: None})),
    ("owner_setting_invalid", "owner_authority_denied", SCOPE, None,
     _rows({**PREFERENCE, "auto_helper_update": None})),
    ("owner_setting_invalid", "owner_authority_denied", SCOPE, None,
     _rows({**PREFERENCE, "auto_helper_update": True})),
    ("owner_setting_invalid", "owner_authority_denied", SCOPE, None,
     _rows({**PREFERENCE, "auto_helper_update": "1"})),
    ("owner_setting_invalid", "owner_authority_denied", SCOPE, None,
     _rows({**PREFERENCE, "auto_helper_update": 2})),
    # 주인이 스스로 끈 것은 운영 사고가 아니라 주인의 선택이다.
    ("owner_auto_update_off", "owner_auto_update_off", SCOPE, None,
     _rows({**PREFERENCE, "auto_helper_update": 0})),
])
def test_owner_refusals_are_closed_value_free_codes(
        caplog, monkeypatch, code, outcome, scope, facts, pairing):
    report = {}
    result = _authorize(monkeypatch, caplog, _request(pairing), scope=scope,
                        facts=facts, report=report)
    assert result == (None, None, outcome)
    assert f"pc_maintenance_owner_authority outcome=denied reason={code}" in caplog.text
    assert report == {"owner_authority":
                      "auto_update_off" if code == "owner_auto_update_off" else "denied"}
    for value in PRIVATE:
        assert value not in caplog.text, (code, value)


def test_another_accounts_setting_never_stands_in(caplog, monkeypatch):
    """같은 PC를 다른 계정이 자동 켬으로 연결해 두어도 관리 링크 주인의 설정만 본다."""
    foreign_on = {**PREFERENCE, "link_id": "pclink_other", "auto_helper_update": 1}
    pairing = Pairing({OWNER: [{**PREFERENCE, "auto_helper_update": 0}], OTHER: [foreign_on]})
    assert _authorize(monkeypatch, caplog, _request(pairing)) == (
        None, None, "owner_auto_update_off")
    assert pairing.reads == [OWNER]
    # 주인 목록이 비어 있으면 다른 계정의 줄을 빌리지 않고 닫힌다.
    pairing = Pairing({OTHER: [dict(PREFERENCE)]})
    assert _authorize(monkeypatch, caplog, _request(pairing)) == (
        None, None, "owner_authority_denied")
    assert pairing.reads == [OWNER]
    assert "reason=owner_setting_missing" in caplog.text


@pytest.mark.parametrize("changes", [
    {"target": {"link_id": "pclink_other"}},
    {"target": {"device_id": "node//other"}},
    {"target": {"node_ref": "node//other"}},
    {"account_ref": "acct_other"},
    {"workspace_ref": "ws_other"},
    {"authorized": False},
])
def test_target_of_another_link_or_account_is_refused(caplog, monkeypatch, changes):
    report = {}
    intent, _target_value, reason = _authorize(
        monkeypatch, caplog, resolver=_target(**changes), report=report)
    assert intent is None and reason == "target_mismatch"
    assert report == {"owner_authority": "target_mismatch"}


def test_resolver_refusal_is_a_target_mismatch(caplog, monkeypatch):
    async def refused(*args, **kwargs):
        return None, object()

    assert _authorize(monkeypatch, caplog, resolver=refused) == (None, None, "target_mismatch")


def test_admission_refusal_after_owner_authority_keeps_its_own_reason(caplog, monkeypatch):
    report = {}
    facts = {**_facts(), "rollout": {**ROLLOUT, "stage": "paused"}}
    intent, _target_value, reason = _authorize(
        monkeypatch, caplog, facts=facts, resolver=_target(), report=report)
    assert intent is None and reason == "stage_closed"
    assert report == {"owner_authority": "passed"}
    assert "pc_maintenance_owner_authority" not in caplog.text


def test_owner_denial_codes_are_a_closed_value_free_set():
    assert host.OWNER_DENIAL_CODES == frozenset({
        "scope_missing", "scope_subject", "owner_managed_missing",
        "owner_auto_update_off", "owner_setting_missing", "owner_setting_invalid",
    })
    for code in host.OWNER_DENIAL_CODES:
        assert re.fullmatch(r"[a-z0-9_]{1,64}", code)
        assert all(value not in code for value in PRIVATE)
    # 예전 동의 기록 사유 코드는 더 이상 만들어지지 않고, 로그 입구도 받지 않는다.
    assert not any(code.startswith("consent") for code in host.OWNER_DENIAL_CODES)
    state = SimpleNamespace()
    for retired in ("consent_missing", "consent_key_record_missing", "consent_map_missing"):
        with pytest.raises(ValueError):
            host._log_denial(state, DEVICE, retired)


def test_repeated_denial_is_logged_once_per_device_and_code(caplog, monkeypatch):
    request = _request(_rows({**PREFERENCE, "auto_helper_update": 0}))
    for _ in range(3):
        assert _authorize(monkeypatch, caplog, request) == (
            None, None, "owner_auto_update_off")
    assert caplog.text.count("pc_maintenance_owner_authority outcome=denied") == 1
    assert "reason=owner_auto_update_off" in caplog.text
    caplog.clear()
    _authorize(monkeypatch, caplog, request)
    assert caplog.text == ""
    # 다른 사유는 같은 PC에서도 따로 한 줄을 남긴다.
    request.app.state.pc_device_pairing_store = _rows()
    _authorize(monkeypatch, caplog, request)
    assert caplog.text.count("reason=owner_setting_missing") == 1
