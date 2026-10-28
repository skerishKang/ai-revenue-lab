"""#5785 — 축사·인사말(speech) tool contract, runnable on its own.

Group: ``speech``. Scope is the existing feature only: the shipped form fields,
the prompt the tool sends to the existing ``/api/chat``, the draft the user
edits, and the save/reopen path through the existing project-file store.

Reused instead of duplicated:
- ``test_5608_util_page_visibility_and_reopen.py`` already pins the util-page
  state entry, the save-button placement, the saved-list projection and the
  reopen handler reading ``data.file.content``. This module does not repeat those
  assertions; it exercises the generate → edit → save → reopen chain end to end
  and the prompt contract that file never covered.

Run alone::

    .venv/Scripts/python.exe -m pytest tests/test_5785_speech_tool.py -q
    python scripts/util3_test_groups.py speech
"""

from __future__ import annotations

import pytest

from _5785_util_runner import run

EVENT = "제78주년 광복절 기념식"


@pytest.fixture(scope="module")
def speech() -> dict:
    return run("speech")


def test_the_form_sends_every_field_it_shows(speech: dict) -> None:
    prompt = speech["prompt"]
    assert prompt.startswith("다음 행사 정보를 바탕으로 축사/인사말 초안을 작성해 주세요.")
    assert f"행사명: {EVENT}" in prompt
    assert "행사 날짜: 2026-08-15" in prompt
    assert "장소: 시청 대강당" in prompt
    assert "행사 성격: 기념식" in prompt
    assert "참석 대상: 지역 주민과 보훈 가족" in prompt
    assert "작성자/직책: 국회의원 임미란" in prompt
    assert "주요 메시지: 감사의 마음과 다음 세대의 책임" in prompt
    assert "강조 내용: 독립운동가 후손" in prompt


def test_the_length_and_tone_choices_reach_the_prompt_as_text(speech: dict) -> None:
    # The select values are codes; the model must receive the readable choice.
    assert "분량: 길게(1000자 내외)" in speech["prompt"]
    assert "말투: 따뜻하고 친근한" in speech["prompt"]


def test_a_pasted_style_sample_is_fenced_as_a_sample_not_an_instruction(
    speech: dict,
) -> None:
    prompt = speech["prompt"]
    assert "아래는 사용자의 기존 축사/인사말 샘플입니다" in prompt
    body = prompt.split("---\n", 1)[1].split("\n---", 1)[0]
    assert body.strip() == "존경하는 지역민 여러분, 오늘 이 자리는…"


def test_the_generation_call_uses_the_existing_chat_contract(speech: dict) -> None:
    payload = speech["chatPayload"]
    assert payload["mode"] == "auto"
    assert [m["role"] for m in payload["messages"]] == ["user"]
    assert payload["messages"][0]["content"] == speech["prompt"]


def test_the_generated_draft_reaches_the_editor(speech: dict) -> None:
    assert speech["generated"].startswith("생성된 초안 본문입니다.")
    # The editor holds the model answer, never the prompt that was sent.
    assert speech["generated"] != speech["prompt"]


def test_saving_keeps_the_user_edit_not_the_raw_answer(speech: dict) -> None:
    assert speech["savedBody"] == speech["edited"]
    assert "[편집: 마무리 인사 추가]" in speech["savedBody"]
    assert speech["savedBody"] != speech["generated"]


def test_the_saved_draft_is_named_after_the_event(speech: dict) -> None:
    assert speech["savedName"] == f"{EVENT}.txt"


def test_the_saved_draft_is_listed_and_reopens_byte_for_byte(speech: dict) -> None:
    assert speech["savedListLabels"], "the saved list must offer the stored draft"
    assert EVENT in speech["savedListLabels"][0]
    assert speech["reopened"] == speech["edited"]


def test_a_stored_speech_can_be_picked_as_the_style_reference(speech: dict) -> None:
    # #5731: each saved row carries a 참고로 선택 action that fills the style
    # sample textarea with the stored body — no copy-paste needed — and the
    # next generation fences that body as the sample, exactly like a pasted
    # one.
    assert speech["refSelected"], "the reference action must fill the style field"
    assert speech["refSelectedMatchesSaved"] is True, speech["refSelected"]
    assert speech["refPromptCarriesSample"] is True


def test_reentering_the_tool_lists_the_previously_stored_speeches(
    speech: dict,
) -> None:
    # #5731: the saved list must exist on tool re-entry too, not only right
    # after a save — the stored history is the point of the feature.
    assert speech["reentryListCount"], "re-entry must load the stored speech list"
    assert EVENT in speech["reentryListLabels"][0]


def test_the_group_touches_only_the_existing_endpoints(speech: dict) -> None:
    allowed = {
        "GET /api/projects",
        "POST /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/projects/p1/files",
        "POST /api/chat",
        # #5895: whether a PC is linked, read through the existing pairing list.
        "GET /api/pc/pairings",
    }
    # Reopening reads the one stored draft through the existing detail route.
    allowed.add("GET /api/projects/p1/files/f1")
    assert set(speech["endpoints"]) <= allowed, speech["endpoints"]
    assert "POST /api/chat" in speech["endpoints"]
    assert not speech["alerts"]


# #5895: the 고츄기 pass — one instruction revises the draft the editor
# already holds, through the same /api/chat lane generation uses.
@pytest.fixture(scope="module")
def revise() -> dict:
    return run("revise")


def test_a_revision_instruction_sends_the_draft_and_the_ask(revise: dict) -> None:
    prompt = revise["revisePayload"]["messages"][0]["content"]
    assert "마무리 인사를 격식 있게 다듬어 주세요" in prompt
    assert "--- 고칠 초안 ---" in prompt
    assert "생성된 초안 본문입니다." in prompt, "the prompt must carry the draft the editor held"


def test_the_revision_replaces_the_draft_and_clears_the_ask(revise: dict) -> None:
    assert revise["revised"].startswith("수정된 초안 본문입니다.")
    assert revise["askCleared"] is True


def test_an_empty_instruction_sends_nothing(revise: dict) -> None:
    assert revise["guardCalls"] == 0


def test_a_failed_revision_keeps_the_owner_draft_and_says_so(revise: dict) -> None:
    assert revise["failureKeptDraft"] is True
    assert revise["failureAlerts"], "a failed revise must be visible, not silent"
    assert all(a.startswith("수정 실패: ") for a in revise["failureAlerts"])


def test_the_revision_uses_the_existing_chat_contract(revise: dict) -> None:
    payload = revise["revisePayload"]
    assert payload["mode"] == "auto"
    assert payload["util"] == "speech"
    assert [m["role"] for m in payload["messages"]] == ["user"]


def test_the_revision_touches_only_the_existing_endpoints(revise: dict) -> None:
    allowed = {
        "GET /api/projects",
        "POST /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/projects/p1/files",
        "POST /api/chat",
        "GET /api/pc/pairings",
    }
    assert set(revise["endpoints"]) <= allowed, revise["endpoints"]
    assert "POST /api/chat" in revise["endpoints"]
    assert not revise["pageErrors"]
