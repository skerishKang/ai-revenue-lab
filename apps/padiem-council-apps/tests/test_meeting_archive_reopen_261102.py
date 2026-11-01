"""#6446 의원3종 실사용 E2E에서 남은 두 조각의 회귀 고정.

① 회의정리 보관함·다시 열기
   실제 계약(`/api/projects/{pid}/files`)으로 저장 → 재진입 목록 → 행 열기 → 내보내기
   단추 활성까지 확인한다. 보관함은 `doc_kind` 가 기록된 새 기록과, 종류가 없던 시절의
   이름 규칙 기록을 모두 읽어야 한다 — 이미 저장된 옛 이름 파일이 사라지면 안 된다.
   다시 열기는 본문만이 아니라 회의명·회의 일시까지 되돌린다. 제목이 비면 내보내기 기본
   이름이 "회의_회의_날짜"가 되고, 이어서 저장하면 이미 있는 기록과 겹쳐 새 이름을 묻는다.

② 390px 카드 진입
   좁은 화면에서는 상단 nav 가 숨고(901px부터 열린다) 카드가 곧 메뉴다. 카드를 누르면 그
   도구가 열리고, 스크롤 기준은 카드 틀이 아니라 연 도구 본문이어야 한다. 카드 틀을 화면
   맨 위로 올리면 방금 연 도구의 첫 입력이 접힌 아래로 밀려 "아무 일도 없었다"로 보인다.

The observations come from the shipped module driven against a recording fake of the
EXISTING project-file contract, so these are executed behaviours, not string matches.
"""
from __future__ import annotations

from _council_module import run

OBS = run("meeting_archive")


def test_a_record_stored_before_kinds_existed_is_still_listed() -> None:
    # 하위호환: doc_kind 이전에 저장된 "예전 회의 기록.txt" 는 이름 규칙으로 분류된다.
    assert any(label.startswith("예전 회의 기록.txt") for label in OBS["labelsB"]), OBS["labelsB"]


def test_a_saved_meeting_is_listed_after_reentry_and_keeps_its_kind() -> None:
    assert any(label.startswith("11월 민원 회의.txt") for label in OBS["labelsB"]), OBS["labelsB"]
    assert ["11월 민원 회의.txt", "meeting"] in OBS["storedKinds"], OBS["storedKinds"]
    # 저장 직후의 목록에도 같은 기록이 한 번만 있다(두 번 저장되지 않는다).
    assert [label for label in OBS["labelsA"] if "11월 민원 회의" in label] == [
        label for label in OBS["labelsB"] if "11월 민원 회의" in label
    ]


def test_reopening_restores_the_edited_body_the_meeting_name_and_the_time() -> None:
    assert OBS["reopened"] == OBS["draft"], OBS["reopened"]
    assert OBS["reopenedTitle"] == "11월 민원 회의", OBS["reopenedTitle"]
    assert OBS["reopenedWhen"] == "2026-11-01T14:00", OBS["reopenedWhen"]
    # 본문이 돌아왔으므로 내보내기(HWPX·DOCX)가 바로 가능하다.
    assert OBS["exportArmed"] is True


def test_a_card_opens_the_tool_itself_not_just_the_card_frame() -> None:
    assert OBS["bodyScrolled"] is True, "the opened tool body must be the scroll target"
    assert OBS["sectionScrolled"] is False, "scrolling the card frame hides the first field"
    assert OBS["alerts"] == [] and OBS["pageErrors"] == []


def test_the_lane_reuses_the_existing_contract_only() -> None:
    assert set(OBS["endpoints"]) <= {
        "GET /api/auth/status",
        "GET /api/pc/pairings",
        "POST /api/chat/stream",
        "GET /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/projects/p1/files",
        "GET /api/projects/p1/files/f1",
        "GET /api/projects/p1/files/f2",
    }, OBS["endpoints"]
