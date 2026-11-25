"""#8699 — 첫 세션 확인이 늦거나 한 번 실패해도 로그아웃 화면을 그리지 않는다.

출발 관찰: 로그인된 브라우저가 앱 첫 진입 때 게스트 화면이 잠깐 보였다가
새로고침하면 돌아왔다. 서버의 내부 신원 확인은 세 번째 시도에 성공하는데,
첫 ``/api/auth/status`` 응답이 ``ready:false``로 오면 클라이언트가 이를
로그아웃 판정으로 받아 곧바로 게스트 화면을 칠하고 있었다.

이 시험은 모듈 하네스가 실제 배포된 ``chat-auth-module.js``를 실행해,
첫 응답이 준비되지 않았거나 한 번 실패했을 때 두 번째 응답 전까지 중립
(pending) 화면이 유지되는지를 본다. 문구는 바뀌지 않는다.
"""
from __future__ import annotations

from _r5_auth_module_harness import status_observations


def _flight(status_map, key):
    flight = status_map[key]
    assert flight["calls"] == 2, "a first unfinished check must be asked once more"
    before = [row["before"] for row in flight["snapshots"] if "before" in row]
    assert all(row["accountState"] == "pending" for row in before), before
    assert all(row["loginHidden"] is True for row in before), before
    return flight


def test_first_not_ready_answer_does_not_paint_a_sign_out_screen():
    flight = _flight(status_observations(), "lateFirst")
    final = flight["final"]
    assert final["accountState"] == "signed_in"
    assert final["loginHidden"] is True
    assert final["loginText"] == "logout"       # 문구 키가 그대로 (문구 변경 없음)
    assert final["accountName"] == "Kim"


def test_first_failed_answer_does_not_paint_a_sign_out_screen():
    flight = _flight(status_observations(), "failedFirst")
    final = flight["final"]
    assert final["accountState"] == "signed_in"
    assert final["loginText"] == "logout"
    assert final["accountName"] == "Kim"


def test_two_not_ready_answers_decide_on_the_second_one():
    flight = status_observations()["twiceNotReady"]
    assert flight["calls"] == 2
    assert flight["final"]["accountState"] == "unavailable"
