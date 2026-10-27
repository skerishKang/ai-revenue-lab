"""The real council-app.js runs the reused contracts end to end.

Behavioural harness contract (same pattern as apps/padiem-chat's
_5785_util_runner.py): the shipped ``static/council-app.js`` executes in a
Node VM against a recording fake of the EXISTING endpoints, and these tests
own the assertions.
"""

from __future__ import annotations
import base64

from _council_module import run

SPEECH_PROMPT_TAIL = (
    "분량: 보통(600자 내외)\n"
    "말투: 공식적이고 격식 있는\n"
    "\n축사 초안을 작성해 주세요. 행사 성격에 맞는 공식 축사 형식으로 작성하고, 인사말과 마무리 인사를 포함해 주세요."
)


def test_every_tool_generates_through_the_one_model_lane() -> None:
    observed = run("generate")
    assert observed["initSignedIn"] is True
    assert observed["badge"] == "로그인됨"
    for prompt in (
        observed["speech"]["prompt"],
        observed["sns"]["prompt"],
        observed["meeting"]["prompt"],
        observed["book"]["prompt"],
    ):
        assert prompt["mode"] == "auto"
        assert prompt["tier"] == "free"
        assert [m["role"] for m in prompt["messages"]] == ["user"]
        assert prompt["messages"][0]["content"].strip()
        assert set(prompt) == {"messages", "mode", "tier", "util"}


def test_every_tool_declares_which_utility_it_is() -> None:
    """The #5916 execution boundary: a declared scope skips the calendar branch."""
    observed = run("generate")
    assert observed["speech"]["prompt"]["util"] == "speech"
    assert observed["sns"]["prompt"]["util"] == "sns"
    assert observed["meeting"]["prompt"]["util"] == "meeting"
    # The book draft is a meeting-lane generation too (same scope on main).
    assert observed["book"]["prompt"]["util"] == "meeting"


def test_a_meeting_text_with_calendar_vocabulary_still_reaches_the_model() -> None:
    """회의 원문에 확인/추가/일정이 있어도 캘린더 오분류가 아닌 생성 결과를 돌려준다."""
    observed = run("calendar_words")
    calendar_answers = (
        "시간대(예: Asia/Seoul)",
        "날짜·시간을 알려주세요",
        "시작 시간을 알려주세요",
        "회의의 일정 범위",
    )
    for row in observed["cases"]:
        assert row["prompt"]["util"] == "meeting", row
        assert row["prompt"]["mode"] == "auto" and row["prompt"]["tier"] == "free"
        for phrase in calendar_answers:
            assert phrase not in row["output"], (row["userText"], phrase)
        assert row["output"].startswith("생성된 초안 본문입니다."), row
    assert not observed["pageErrors"], observed["pageErrors"]


def test_generation_reaches_each_editor() -> None:
    observed = run("generate")
    assert observed["speech"]["output"].startswith("생성된 초안 본문입니다.")
    assert observed["sns"]["output"].startswith("생성된 초안 본문입니다.")
    assert observed["sns"]["title"] == "인스타그램 게시글"
    assert observed["meeting"]["output"].startswith("생성된 초안 본문입니다.")
    assert observed["book"]["output"].startswith("생성된 초안 본문입니다.")


def test_the_tools_send_the_shipped_prompt_templates() -> None:
    observed = run("generate")
    speech = observed["speech"]["prompt"]["messages"][0]["content"]
    assert speech.startswith("다음 행사 정보를 바탕으로 축사/인사말 초안을 작성해 주세요.")
    assert speech.endswith(SPEECH_PROMPT_TAIL)
    sns = observed["sns"]["prompt"]["messages"][0]["content"]
    assert sns.startswith("다음 행사 정보를 바탕으로 인스타그램 게시글: 150-300자, 짧고 임팩트 있는, 해시태그 10-15개, 이모지 풍부을 작성해 주세요.")
    meeting = observed["meeting"]["prompt"]["messages"][0]["content"]
    assert meeting.startswith("다음 회의 내용을 정리해 주세요.")
    assert "5. 미해결 사항" in meeting
    book = observed["book"]["prompt"]["messages"][0]["content"]
    assert book.startswith("다음은 사용자가 선택한 활동 기록 본문입니다. 각 기록의 이름을 출처로 유지하세요.")
    assert "원본 기록에 없는 사건, 날짜, 발언을 사실처럼 추가하지 마세요" in book


def test_the_sns_prompt_carries_the_photo_composition() -> None:
    """The #5728 prompt line names the stored photos and the platform placement."""
    observed = run("generate")
    sns = observed["sns"]["prompt"]["messages"][0]["content"]
    assert "첨부 사진: 2장 (현장1.png, 현장2.jpg)" in sns
    # instagram treats photos as separate post media — no in-body image notes.
    assert "사진은 본문과 구분된 게시물 미디어로 첨부됩니다." in sns
    assert "이미지 위치 설명은 넣지 마세요" in sns


def test_saving_stores_each_draft_through_the_project_file_channel() -> None:
    observed = run("generate")
    # speech draft + two stored photo originals + the roster + the sns draft
    # + the meeting record. The roster rewrite replaces its previous file, so
    # exactly one "SNS 사진 구성.json" survives.
    assert observed["savedCount"] == 6
    assert observed["savedNames"] == [
        "제78주년 광복절 기념식.txt",
        "현장1.png",
        "현장2.jpg",
        "인스타그램 게시글.txt",
        "SNS 사진 구성.json",
        "10월 주민 민원 회의.txt",
    ]


def test_the_photo_roster_v2_carries_order_positions_draft_and_platform() -> None:
    """The #5728/#5924 roster contract, restated on the council app's own DOM."""
    observed = run("generate")
    roster = observed["sns"]["roster"]
    assert roster is not None, "the roster file must exist after the composition"
    assert roster["version"] == 2
    assert [p["name"] for p in roster["photos"]] == ["현장1.png", "현장2.jpg"]
    assert roster["photos"][0]["position"] == "0"
    assert roster["photos"][1]["position"] == "auto"
    assert roster["draft"]["platform"] == "instagram"
    assert roster["draft"]["text"] == observed["sns"]["output"]
    assert observed["sns"]["photoCountText"] == "2장"


def test_the_saved_speech_list_offers_itself_as_the_style_reference() -> None:
    """#5731: stored speeches are pickable style references on re-entry too."""
    observed = run("generate")
    labels = observed["speech"]["savedListLabels"]
    assert len(labels) == 1
    assert labels[0].startswith("제78주년 광복절 기념식.txt (")
    assert observed["speech"]["refSelectedMatchesSaved"] is True
    # The picked manuscript IS the stored draft body, not a summary of it.
    assert observed["speech"]["refSelected"] == observed["speech"]["output"]
    # The next generation fences it as the style sample, like a pasted one.
    assert observed["speech"]["refPromptCarriesSample"] is True


def test_reopening_a_stored_record_restores_its_body() -> None:
    observed = run("generate")
    # The archive reader fetches the stored record and puts its body back.
    assert observed["meeting"]["reopened"].startswith("생성된 초안 본문입니다")
    assert observed["meeting"]["reopened"] == observed["meeting"]["output"]


def test_the_session_cookie_contract_travels_on_every_chat_call() -> None:
    observed = run("generate")
    assert observed["chatCredentials"], "generation calls must exist"
    assert set(observed["chatCredentials"]) == {"include"}


def test_the_tools_touch_only_the_existing_endpoints() -> None:
    observed = run("generate")
    exact = {
        "GET /api/auth/status",
        "POST /api/chat",
        "GET /api/projects",
        "POST /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/projects/p1/files",
    }
    # The photo contract adds the detail/original reads and the deletes the
    # roster rewrite needs — all on the SAME project-file authority (#5936 §3).
    prefixes = (
        "GET /api/projects/p1/files/",
        "DELETE /api/projects/p1/files/",
    )
    endpoints = set(observed["endpoints"])
    assert "POST /api/chat" in endpoints
    for endpoint in endpoints:
        assert endpoint in exact or endpoint.startswith(prefixes), endpoint
    assert not observed["pageErrors"], observed["pageErrors"]
    assert observed["alerts"] == []


def test_reentry_restores_the_composition_and_delete_stays_in_sync() -> None:
    """#5728 re-entry: roster v2 order/positions/draft/platform come back once,
    a removal deletes the stored original, and the next session never sees it."""
    observed = run("restore")
    restored = observed["restored"]
    # the saved speech is offered again on re-entry, with its 참고로 선택 action
    assert len(restored["speechLabelsB"]) == 1
    assert restored["speechLabelsB"][0].startswith("재진입 복원 검증 행사.txt (")
    assert restored["speechRefCountB"] == 1
    # photos come back in the roster order with the blog insertion positions
    assert restored["photoCountB"] == "3장"
    assert restored["photoNamesB"] == ["중간.jpg", "앞.png", "끝.webp"]
    assert restored["positionsB"] == ["0", "auto", "end"]
    # the restored thumbnails are the stored ORIGINALS, byte for byte
    assert restored["thumbsMatchOriginals"] is True
    expected_thumbs = [
        "data:image/png;base64," + base64.b64encode(b"bytes-middle").decode("ascii"),
        "data:image/png;base64," + base64.b64encode(b"bytes-front").decode("ascii"),
        "data:image/png;base64," + base64.b64encode(b"bytes-end").decode("ascii"),
    ]
    assert restored["thumbsB"] == expected_thumbs
    # the saved draft and its platform come back with the result visible
    assert restored["draftB"] == observed["snsDraftA"]
    assert restored["titleB"] == "블로그 게시글"
    assert restored["resultHiddenB"] is False
    assert restored["previewShownB"] is True

    after_delete = observed["afterDelete"]
    assert after_delete["deleteRequested"] is True
    assert after_delete["middleStillStored"] is False
    roster = after_delete["rosterAfterDelete"]
    assert roster is not None and roster["version"] == 2
    assert [p["name"] for p in roster["photos"]] == ["앞.png", "끝.webp"]
    # the saved draft rides the rewrite — a photo change never drops it
    assert roster["draft"]["text"].startswith("생성된 초안 본문입니다.")
    assert roster["draft"]["platform"] == "blog"

    session_c = observed["sessionC"]
    assert session_c["countC"] == "2장"
    assert session_c["namesC"] == ["앞.png", "끝.webp"]
    # the draft re-saved under instagram restores under instagram
    assert session_c["titleC"] == "인스타그램 게시글"
    assert session_c["draftC"] == roster["draft"]["text"]
    assert not observed["pageErrors"], observed["pageErrors"]
    assert observed["alerts"] == []


def test_server_errors_surface_their_message_and_fail_loudly() -> None:
    observed = run("errors")
    assert {row["name"]: row["output"] for row in observed["outputs"]} == {
        "server_message": "생성 실패: 관리자 인증을 확인해 주세요.",
        "no_message": "생성 실패: HTTP 502",
        "non_string": "생성 실패: HTTP 403",
        "not_json": "생성 실패: HTTP 503",
    }
    assert not observed["pageErrors"], observed["pageErrors"]
