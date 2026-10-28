"""#5785 — SNS 홍보(sns) tool contract, runnable on its own.

Group: ``sns``. Scope is the existing text/draft feature only. The photo
composition is #5728's contract and stays there
(``test_5728_sns_photo_compose.py``); this module does not repeat it. What it
adds is the part no test covered: the per-platform prompt the tool sends to the
existing ``/api/chat``, the platform titles, the save path, and the fact that a
platform switch keeps the user's own edit.

Run alone::

    .venv/Scripts/python.exe -m pytest tests/test_5785_sns_tool.py -q
    python scripts/util3_test_groups.py sns
"""

from __future__ import annotations

import pytest

from _5785_util_runner import run

EVENT = "마을 한마음 축제"


@pytest.fixture(scope="module")
def sns() -> dict:
    return run("sns")


def test_the_blog_prompt_carries_the_event_text_and_reader(sns: dict) -> None:
    prompt = sns["blogPrompt"]
    assert prompt.startswith("다음 행사 정보를 바탕으로 블로그 게시글")
    assert f"행사명: {EVENT}" in prompt
    assert "날짜·장소: 10월 3일 · 항구 광장" in prompt
    assert "주요 내용: 주민 노래자랑과 먹거리 장터가 열렸습니다." in prompt
    assert "메모: 사진은 마을 신문에도 씁니다." in prompt
    assert "대상 독자: 지역 주민" in prompt
    assert "문체: 캐주얼하고 친근한" in prompt
    assert "제목, 본문, 해시태그를 구분하여 작성해 주세요." in prompt


def test_each_platform_asks_for_its_own_format(sns: dict) -> None:
    # One feature, three formats: the guide must change with the tab and the
    # event text must stay identical across them.
    assert "블로그 게시글: 800-1200자" in sns["blogPrompt"]
    assert "페이스북 게시글: 300-500자" in sns["fbPrompt"]
    assert "인스타그램 게시글: 150-300자" in sns["igPrompt"]
    for prompt in (sns["fbPrompt"], sns["igPrompt"]):
        assert f"행사명: {EVENT}" in prompt


def test_the_result_title_names_the_chosen_platform(sns: dict) -> None:
    assert sns["platformTitles"] == ["블로그 게시글", "페이스북 게시글"]


def test_the_saved_draft_is_named_after_the_platform_card(sns: dict) -> None:
    # The save name comes from the result heading, so a Facebook draft is not
    # silently filed as a blog post.
    assert sns["savedName"] == "블로그 게시글.txt"


def test_saving_stores_the_edited_draft(sns: dict) -> None:
    assert sns["savedBody"] == sns["edited"]
    assert "#마을축제 #임미란" in sns["savedBody"]


def test_switching_platform_keeps_the_draft_the_user_typed(sns: dict) -> None:
    switched = sns["afterSwitch"]
    assert switched["event"] == EVENT
    assert switched["output"] == sns["edited"]
    assert switched["title"] == "페이스북 게시글"


def test_the_group_touches_only_the_existing_endpoints(sns: dict) -> None:
    assert set(sns["endpoints"]) <= {
        "GET /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/chat",
        "POST /api/projects/p1/files",
        # #5895: whether a PC is linked, read through the existing pairing list.
        "GET /api/pc/pairings",
    }
    assert "POST /api/chat" in sns["endpoints"]
    assert not sns["alerts"]


# #5895: the SNS screen carries the same 고츄기 row on its own draft.
@pytest.fixture(scope="module")
def revise() -> dict:
    return run("revise")


def test_the_sns_revision_sends_its_own_draft_and_ask(revise: dict) -> None:
    payload = revise["snsPayload"]
    assert payload["util"] == "sns"
    prompt = payload["messages"][0]["content"]
    assert "더 짧게 줄여 주세요" in prompt
    assert "--- 고칠 초안 ---" in prompt
    assert "생성된 초안 본문입니다." in prompt


def test_the_sns_revision_replaces_the_draft(revise: dict) -> None:
    assert revise["snsRevised"] == "수정된 SNS 본문입니다."
    assert not revise["pageErrors"]
