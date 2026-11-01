"""#6011·#6460 — 여러 PC 기기 선택·표시 실사용 시험 (컴1 로컬 261102).

컴1에서 두 개의 허용 루트(A·B)를 가진 시험 PC 두 대를 상정한 장면을, 실제
pc_device_pairing_store(SQLite)와 실제 기기 디렉터리·선택 라우트로 검증한다.
커넥터 바이너리 자체의 루프백 페어링은 이 저장소가 고정해 둔 보안 경계
(customer_enrollment.py: customer setup URL은 chat.padiem.net 고정이고
"No operator environment option or caller supplied URL", broker URL 문법은
https-only) 때문에 이 시험에서 대행하지 않는다 — 기기 상태는 실제 링크·클레임·
해제 경로로 만든다.

장면 (CTO 지시 261102):
  1. 기기 목록: 두 PC가 이름과 함께 보이고, 온라인 증명이 없으면 그렇게 말한다
     (usable=False·ACTION_REQUIRED — 가짜 CONNECTED 금지 원칙).
  2. 선택 전환: A를 골라 저장 → B로 바꾸면 정확히 B만 저장(섞임 없음).
  3. 선택 없음: 두 링크에 선택이 없으면 아무것도 고르지 않는다(질문).
  4. 한 대 끊김: B 해제 → 목록에서 B 소멸, A는 유지·선택 가능.
  5. 재연결: B를 다시 클레임하면 목록에 돌아온다.
  6. 브라우저 UI(기기 선택 UI 44px·14px·390): 로컬 러너가 연결 포트를
     구성하지 않고(claw_local_connect_port=None → local_connect_unconfigured),
     커넥터 페어링도 위 경계로 차단되어 이 세션에서 UI까지 구축하지 못했다 —
     strict xfail로 남긴다.

대표 PC·운영 서버·컴2는 접촉하지 않았다. 모든 기기 노드 id는 시험용 값이다.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

import pytest

import test_5172_mesh_device_id_boundary as directory   # noqa: E402
import test_5573_pc_device_pairing as pairing           # noqa: E402
from test_5573_pc_two_pcs import NODE_A, NODE_B, _linked  # noqa: E402

from app.claw_device_directory_routes import (          # noqa: E402
    CLAW_DEVICE_DIRECTORY_PATH,
    CLAW_PC_SELECT_PATH,
)
from app.pc_work_context import (                       # noqa: E402
    _EXEC_READY,
    _link_execution_target,
)

LABEL_A = "시험PC-A"
LABEL_B = "시험PC-B"
OWNER = directory.OWNER
WORKSPACE = directory.WORKSPACE


def _two_pcs():
    """시험PC-A·시험PC-B 두 링크가 있는 실제 SQLite 스토어와 함께 돌려준다."""
    store = pairing.store()
    _linked(store, owner=OWNER, node=NODE_A, label=LABEL_A)
    _linked(store, owner=OWNER, node=NODE_B, label=LABEL_B)
    return store


def _link_id(store, *, node: str) -> str | None:
    rows = pairing.run(store.list_links(user_id=OWNER))
    for row in rows:
        if row.get("mesh_node_id") == node:
            return str(row.get("link_id") or row.get("id") or "")
    return None


def test_two_paired_pcs_are_listed_by_name_with_honest_online_state() -> None:
    store = _two_pcs()
    app, settings = directory.make_app()
    app.state.pc_device_pairing_store = store

    with directory._session_pair():
        listed = directory._get(app, settings).json()

    rows = {row["deviceId"]: row for row in listed["devices"]}
    assert NODE_A in rows and NODE_B in rows, listed
    assert rows[NODE_A]["deviceName"] == LABEL_A
    assert rows[NODE_B]["deviceName"] == LABEL_B
    # 하트비트 증명이 없는 하니스 상태에서 디렉터리는 온라인을 거짓으로
    # 말하지 않는다 — 사용자에게 필요한 동작이 필요하다고만 안내한다.
    for row in (rows[NODE_A], rows[NODE_B]):
        assert row["selectable"] is True
        assert row["usable"] is False
        assert row["state"] == "ACTION_REQUIRED"


def test_device_selection_switches_exactly_and_never_mixes() -> None:
    store = _two_pcs()
    selection = directory.SelectionStore()
    app, settings = directory.make_app(selection_store=selection)
    app.state.pc_device_pairing_store = store

    with directory._session_pair():
        first = directory._post_select(app, settings, {"device_id": NODE_A})
        second = directory._post_select(app, settings, {"device_id": NODE_B})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["selectedDeviceId"] == NODE_A
    assert second.json()["selectedDeviceId"] == NODE_B
    # A를 골랐다가 B로 바꾼 기록 — B 저장 안에 A의 흔적이 섞여 있으면 안 된다.
    assert selection.saves == [(OWNER, WORKSPACE, NODE_A), (OWNER, WORKSPACE, NODE_B)]


def test_two_links_with_no_choice_ask_instead_of_guessing() -> None:
    links = [
        {"mesh_node_id": NODE_A, "label": LABEL_A},
        {"mesh_node_id": NODE_B, "label": LABEL_B},
    ]
    # 소유자의 이름("시험PC-A의 파일 목록 보여줘")만이 실행 대상을 정한다.
    assert _link_execution_target(links, None) is None
    assert _link_execution_target(links, NODE_A).device_id == NODE_A
    assert _link_execution_target(links, NODE_A).status == _EXEC_READY
    assert _link_execution_target(links, NODE_B).device_id == NODE_B
    assert _link_execution_target([], NODE_B) is None
    assert _link_execution_target(links, "node/meshdomain/somebody-else") is None


def test_revoking_b_leaves_a_listed_selectable_and_b_comes_back_on_repair() -> None:
    store = _two_pcs()
    app, settings = directory.make_app()
    app.state.pc_device_pairing_store = store

    b_link_id = _link_id(store, node=NODE_B)
    assert b_link_id, "두 번째 PC의 링크 행이 만들어져야 한다"
    revoked = pairing.run(store.revoke_link(user_id=OWNER, link_id=b_link_id, now=pairing._now()))
    assert revoked is True or revoked, revoked

    with directory._session_pair():
        after_revoke = directory._get(app, settings).json()
        selection = directory.SelectionStore()
        app.state.claw_pc_device_selection_store = selection
        saved = directory._post_select(app, settings, {"device_id": NODE_A})
    rows = {row["deviceId"]: row for row in after_revoke["devices"]}
    assert NODE_B not in rows, after_revoke
    assert rows[NODE_A]["deviceName"] == LABEL_A
    assert rows[NODE_A]["selectable"] is True
    assert saved.status_code == 200, saved.text

    # 다시 연결: 해제된 링크는 같은 표식으로 자동 복귀되지 않는다(complete_claim
    # 은 발급된 코드의 install_tag와 일치할 때만 접수 — 임의 태그는 None). 정석
    # 재연결은 새 페어링 코드 발급 → 새 표식 클레임이다.
    arbitrary = pairing.run(store.complete_claim_from_observation(
        agent_name=f"{LABEL_B}-install-tag-repair", mesh_node_id=NODE_B, now=pairing._now(),
    ))
    assert arbitrary is None, "해제된 링크의 임의 표식 재클레임은 무시되어야 한다"
    reissued = pairing.run(store.issue_code(user_id=OWNER, issued_at=pairing._now()))
    repaired = pairing.run(store.complete_claim_from_observation(
        agent_name=reissued["install_tag"], mesh_node_id=NODE_B, now=pairing._now(),
    ))
    assert repaired, repaired
    with directory._session_pair():
        after_repair = directory._get(app, settings).json()
    rows = {row["deviceId"]: row for row in after_repair["devices"]}
    assert NODE_A in rows and NODE_B in rows, after_repair
    assert rows[NODE_B]["selectable"] is True


@pytest.mark.xfail(strict=True, reason=(
    "브라우저 UI 장면(기기 목록·선택 UI 44px·14px·390): 로컬 러너가 연결 포트를 "
    "구성하지 않아(claw_local_connect_port=None → local_connect_unconfigured) 실제 "
    "UI 흐름을 세우려면 비운영 브로커 증거 호스트 부트 + 포트 구성이 필요하다. "
    "커넥터 바이너리의 루프백 페어링은 보안 경계(고정 운영 origin·https-only)로 "
    "의도적으로 차단되어 있다 — 이 시험은 UI 구축이 이루어지면 통과로 전환한다."
))
def test_browser_ui_device_selection_scene_390() -> None:
    assert False, "UI 장면 미구축 — 위 xfail reason 참조"
