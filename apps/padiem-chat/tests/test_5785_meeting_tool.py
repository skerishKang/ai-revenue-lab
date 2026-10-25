"""#5785 — 회의정리·활동집(meeting) tool contract, runnable on its own.

Group: ``meeting``. Covers the existing feature only: the summary prompt, the
saved record, the 활동 기록 archive, reopening a stored record, and the 활동집
(book) draft built from the records the user selects.

One real defect was found while writing this group and is pinned below as a
strict xfail instead of being fixed here: ``util-menu.js`` meeting generation
ends with the SNS preview lines (``previewBox`` / ``renderPreview``), which are
declared inside the SNS builder. A browser logs the resulting ReferenceError as
an unhandled rejection and keeps the answer on screen, so the user-visible
summary still works; the stray call is #5608/#5731 territory, and this issue is
scoped to test infrastructure.

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
    assert meeting["savedName"] == f"{TITLE}.txt"
    assert meeting["savedBody"] == meeting["edited"]


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


def test_the_group_touches_only_the_existing_endpoints(meeting: dict) -> None:
    allowed = {
        "GET /api/projects",
        "POST /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/projects/p1/files",
        "POST /api/chat",
    }
    # Reopening the record and building the book both read the existing detail
    # route for the stored draft.
    allowed.add("GET /api/projects/p1/files/f1")
    assert set(meeting["endpoints"]) <= allowed, meeting["endpoints"]
    assert "POST /api/chat" in meeting["endpoints"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "util-menu.js meeting gen() ends with the SNS preview lines "
        "(previewBox/renderPreview), which are scoped to buildSns; the browser "
        "logs 'previewBox is not defined' after the summary is rendered. "
        "Removing the stray call is #5608/#5731 work, not #5785 test scope."
    ),
)
def test_meeting_generation_does_not_reference_the_sns_preview(meeting: dict) -> None:
    assert meeting["pageErrors"] == []
