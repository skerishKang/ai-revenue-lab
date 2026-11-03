"""#6695 PR-3 — legacy 맵 폴백은 운영 스위치로 끝난다.

격리 설계 문서(#6695) PR-3 (B-3). `_engine_pc_files_target`의 TODO(#5573)
폴백 — 소유 링크가 없는 계정을 배포 소유 맵 행으로 허용하는 전환 경로 — 가
`ORACLE_MESH_LEGACY_MAP_LANE=off`와 같은 스위치(app.state에 반영된 값)로
종료 가능함을 고정한다:

- 기본값(스위치 없음·그 외 값): 지금과 같다 — 링크 없는 계정도 맵 행으로
  파일 작업을 계속한다(컴1·컴2 운영 장치의 현재 동작).
- 스위치 off: 소유 링크가 없는 명령은 거부된다. 디렉터리가 "링크 없음"이라고
  답했으면 맵을 묻지도 않고, 디렉터리가 아예 답을 못 했으면 fail closed(503).
  링크가 있으면 맵과 무관하게 계속 통과한다.

여기서 가짜 소스의 command_target은 맵이 응답하는 상황을 흉내 낸다 — 즉 채널
소스 합성이 스위치를 놓치는 회귀가 생겨도 이 사이트의 게이트가 막는다는 것을
증명한다(단일 방어선이 아닌 이중 방어선의 존재 증명).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.oracle_mesh_read_return_routes import (
    EXECUTION_MODE_MESH,
    _engine_pc_files_target,
    _DIRECTORY_UNUSABLE,
)

ACCOUNT_REF = "acct_owner_6695"
WORKSPACE_REF = "ws_6695"
MAP_ROW = {
    "account_ref": ACCOUNT_REF,
    "device_id": "pc@mesh+7",
    "node_ref": "pc@mesh+7",
    "root_ref": "root-6695",
    "path_relative": "보고서.txt",
    "file_path": "C:/granted/보고서.txt",
    "command_exec": True,
}
LINK_ROW = {
    "link_id": "link-6695",
    "user_id": ACCOUNT_REF,
    "mesh_node_id": "pc@mesh+9",
    "label": "내 PC",
    "state": "active",
    "paused_at": None,
    "roots": [{"root_ref": None, "label": "granted", "path": "C:/granted",
               "state": "active"}],
}


class _MapSource:
    configured = True
    execution_mode = EXECUTION_MODE_MESH

    def __init__(self, *, answers: bool = True, raises: bool = False):
        self._answers = answers
        self._raises = raises
        self.asked: list[dict] = []

    def command_target(self, *, account_ref, device_id=None):
        self.asked.append({"account_ref": account_ref, "device_id": device_id})
        if self._raises:
            raise RuntimeError("map channel broken")
        return dict(MAP_ROW) if self._answers else None


class _Identity:
    async def resolve_connector_owner_scope(self, *, session_id):
        return {"account_ref": ACCOUNT_REF, "workspace_ref": WORKSPACE_REF}


class _Pairing:
    """Directory fake: `links`가 답이고, 없으면 디렉터리 자체가 불가능."""

    def __init__(self, links=None, unusable=False, raises=False):
        self._links = links
        self._unusable = unusable
        self._raises = raises
        self.asked: list[dict] = []

    async def links_for_owner(self, *, user_id):
        self.asked.append({"user_id": user_id})
        if self._raises:
            raise RuntimeError("directory down")
        if self._unusable:
            return "not-a-list"
        return list(self._links or [])


def _request(*, pairing, source, lane_on=None):
    state = SimpleNamespace(
        oracle_mesh_return_source=source,
        control_plane_identity_authority=_Identity(),
        pc_device_pairing_store=pairing,
    )
    if lane_on is not None:
        state.oracle_mesh_legacy_map_lane = lane_on
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _run(request, *, selected=None):
    return asyncio.run(_engine_pc_files_target(
        request, session=SimpleNamespace(session_id="sess-6695"),
        selected_device_id=selected, user_id="usr_6695",
    ))


def _refusal_code(response) -> str:
    import json
    return json.loads(response.body)["error"]["code"]


# -- default: today's behaviour ----------------------------------------------

def test_by_default_a_linkless_account_still_reaches_the_map() -> None:
    pairing = _Pairing(links=[])
    source = _MapSource()
    target, refusal = _run(_request(pairing=pairing, source=source))
    assert refusal is None
    assert target["authorized"] is True
    assert target["target"]["node_ref"] == "pc@mesh+7"
    assert target["roots"][0]["path"] == "C:/granted"
    # The absent switch reads as enabled — the deployment never set it.
    assert source.asked, "the map must still be consulted by default"


def test_an_explicit_enabled_value_keeps_today_behaviour() -> None:
    target, refusal = _run(_request(
        pairing=_Pairing(links=[]), source=_MapSource(), lane_on=True,
    ))
    assert refusal is None and target["authorized"] is True


# -- switch off: the ownership link is the only authority ---------------------

def test_with_the_switch_off_a_linkless_command_is_refused() -> None:
    source = _MapSource()
    target, refusal = _run(_request(
        pairing=_Pairing(links=[]), source=source, lane_on=False,
    ))
    assert target is None and refusal is None
    # The map is not even asked: the directory already answered "no link".
    assert source.asked == []


def test_with_the_switch_off_an_unusable_directory_fails_closed() -> None:
    for broken in (_Pairing(unusable=True), _Pairing(raises=True)):
        target, refusal = _run(_request(
            pairing=broken, source=_MapSource(), lane_on=False,
        ))
        assert target is None
        assert _refusal_code(refusal) == "oracle_mesh_device_directory_unavailable"


def test_with_the_switch_off_an_ownership_link_still_works() -> None:
    source = _MapSource()
    target, refusal = _run(_request(
        pairing=_Pairing(links=[LINK_ROW]), source=source, lane_on=False,
    ))
    assert refusal is None
    assert target["authorized"] is True
    assert target["target"]["node_ref"] == "pc@mesh+9"
    assert target["target"]["link_id"] == "link-6695"
    assert source.asked == [], "the map must stay out of a linked call"


def test_the_switch_gate_sits_in_front_of_a_map_that_lost_the_memo() -> None:
    """채널 소스 합성이 스위치를 놓쳐 맵이 여전히 답하는 회귀를 상정해도,
    이 사이트의 게이트가 명령을 막는다(이중 방어)."""
    source = _MapSource()  # command_target answers a row unconditionally
    target, refusal = _run(_request(
        pairing=_Pairing(links=[]), source=source, lane_on=False,
    ))
    assert target is None and refusal is None
    assert source.asked == []


# -- switch on, directory unusable: today's exact semantics -------------------

def test_by_default_an_unusable_directory_refuses_when_the_map_breaks() -> None:
    target, refusal = _run(_request(
        pairing=_Pairing(raises=True), source=_MapSource(raises=True),
    ))
    assert target is None
    assert _refusal_code(refusal) == "oracle_mesh_device_directory_unavailable"


def test_by_default_an_unusable_directory_still_falls_back_to_the_map() -> None:
    target, refusal = _run(_request(
        pairing=_Pairing(unusable=True), source=_MapSource(),
    ))
    assert refusal is None
    assert target["authorized"] is True
    assert target["target"]["node_ref"] == "pc@mesh+7"


def test_the_directory_unusable_constant_keeps_its_meaning() -> None:
    assert _DIRECTORY_UNUSABLE == "directory_unusable"
