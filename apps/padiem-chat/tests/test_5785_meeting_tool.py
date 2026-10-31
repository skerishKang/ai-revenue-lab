"""#5785 — 회의정리·활동집(meeting) tool contract, runnable on its own.

Group: ``meeting``. Covers the existing feature only: the summary prompt, the
saved record, the 활동 기록 archive, reopening a stored record, and the 활동집
(book) draft built from the records the user selects.

A real defect found while writing this group was pinned as a strict xfail there
(``util-menu.js`` meeting generation ended with the SNS preview lines
``previewBox`` / ``renderPreview``, which are declared inside the SNS builder).
The stray call is now removed, so the test asserts a clean page-error list.

Run alone::

    .venv/Scripts/python.exe -m pytest tests/test_5785_meeting_tool.py -q
    python scripts/util3_test_groups.py meeting
"""

from __future__ import annotations

import pytest

from _5785_util_runner import run

TITLE = "10월 주민 민원 회의"


@pytest.fixture(scope="module")
def meeting() -> dict:
    return run("meeting")


def test_the_summary_prompt_names_the_sections_it_asks_for(meeting: dict) -> None:
    prompt = meeting["prompt"]
    assert prompt.startswith("다음 회의 내용을 정리해 주세요.")
    assert f"회의명: {TITLE}" in prompt
    assert "회의 일시: 2026-10-24T10:00" in prompt
    assert "참석자: 비서실장, 지역 담당" in prompt
    assert "회의 내용:\n항구 도로 보수 일정과 버스 노선 조정을 논의했습니다." in prompt
    for section in ("회의 요약", "주요 논의사항", "결정사항", "후속 업무", "미해결 사항"):
        assert section in prompt


def test_the_summary_reaches_the_editor(meeting: dict) -> None:
    assert meeting["generated"].startswith("생성된 초안 본문입니다.")
    assert meeting["generated"] != meeting["prompt"]


def test_saving_stores_the_edited_record_named_after_the_meeting(
    meeting: dict,
) -> None:
    # The first save in the scenario is the meeting record; the later book
    # save uses the book name rule and is pinned separately.
    assert f"{TITLE}.txt" in meeting["savedRecordNames"]
    record = meeting["savedRecordBodies"][f"{TITLE}.txt"]
    assert record == meeting["edited"]


def test_the_archive_lists_the_record_with_a_book_selector(meeting: dict) -> None:
    labels = meeting["archiveLabels"]
    assert any("선택 기록으로 책/활동집 초안 생성" in label for label in labels)
    assert any(TITLE in label and ".txt" in label for label in labels)
    assert meeting["archiveHasCheckbox"] is True


def test_reopening_a_record_restores_the_stored_body(meeting: dict) -> None:
    # The harness clears the editor first, so this is a real restore.
    assert meeting["reopened"] == meeting["edited"]
    assert not meeting["alerts"], meeting["alerts"]


def test_the_book_draft_keeps_each_record_as_a_named_source(meeting: dict) -> None:
    prompt = meeting["bookPrompt"]
    assert prompt.startswith("다음은 사용자가 선택한 활동 기록 본문입니다.")
    assert f"[기록: {TITLE}.txt]" in prompt
    assert meeting["edited"] in prompt
    # The no-fabrication boundary travels with the request.
    assert "원본 기록에 없는 사건, 날짜, 발언을 사실처럼 추가하지 마세요" in prompt
    assert "각 장 끝에 근거가 된 기록 파일명을 표시하세요" in prompt
    assert meeting["bookOutput"].startswith("생성된 초안 본문입니다.")


def test_the_record_order_is_rearrangeable_and_drives_the_book(meeting: dict) -> None:
    # #5608: up/down moves re-arrange the record list itself, and the book
    # builder reads that arrangement — what the user sees is the sequence
    # the AI receives.
    assert meeting["orderBefore"][0].startswith(TITLE)
    assert meeting["orderAfter"][0].startswith("11월 마을 총회")
    assert meeting["bookOrderPromptCarriesArrangedOrder"] is True, meeting["bookOrderPrompt"]


def test_the_book_draft_saves_under_its_own_name_and_reopens(meeting: dict) -> None:
    # #5608: the 활동집 저장 action persists the edited draft through the
    # existing project-file channel under the book name rule, so books never
    # mix with meeting records; a fresh session lists and restores it.
    assert meeting["bookSavedName"], "the book draft must persist"
    assert meeting["bookSavedName"].startswith("활동집 - ")
    assert meeting["bookSavedName"].endswith(".txt")
    assert meeting["reentryBookListCount"] >= 1
    assert meeting["reentryBookRestored"] == meeting["bookOutput"]
    # The re-entered session still lists the stored meeting records too.
    assert meeting["reentryRecordCount"] >= 2


def test_the_group_touches_only_the_existing_endpoints(meeting: dict) -> None:
    allowed = {
        "GET /api/projects",
        "POST /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/projects/p1/files",
        "POST /api/chat",
    }
    # Reopening the record and building the book both read the existing detail
    # route for the stored drafts; f3 is the saved activity book.
    allowed.update({"GET /api/projects/p1/files/f1", "GET /api/projects/p1/files/f2", "GET /api/projects/p1/files/f3"})
    assert set(meeting["endpoints"]) <= allowed, meeting["endpoints"]
    assert "POST /api/chat" in meeting["endpoints"]


def test_meeting_generation_does_not_reference_the_sns_preview(meeting: dict) -> None:
    assert meeting["pageErrors"] == []


def test_the_form_is_built_with_the_save_status_above_its_buttons(meeting: dict) -> None:
    """Same #6257 order fault as the SNS builder, on the meeting side: the
    status line was inserted against an actions row that was not a child yet,
    so the panel never got its form. See ``test_5785_sns_tool.py`` for the
    full read-back rationale.
    """
    build = meeting["formBuild"]
    assert build["built"] is True, build
    assert build["loaded"] == "1", build
    assert build["statusAboveActions"] is True, build


def test_activity_book_period_selects_dates_and_preserves_manual_changes() -> None:
    result = run("meeting_period")
    assert result["initial"] == ["mp1", "mp2"]
    assert result["manual"] == ["mp1"]
    assert result["order"] == ["mp2", "mp1", "mp3"]
    assert result["emptySelected"] == []
    assert result["empty"] == "해당 기간의 회의 기록이 없습니다."
    assert result["quickLabels"] == ["이번 달", "지난달", "이번 분기", "올해"]
    assert result["pageErrors"] == []
