"""#7841: 분명한 PC 작업 턴은 도구를 부르게 하고, 부정문은 쓰기 의도가 아니다.

운영 실측(카나리 run 43845249212): path=model_first_direct, pc_lane_closed=none,
pc_tools_offered=5, tool_called=0. 문장 "...어떤 파일도 변경하지 않습니다." 의
'변경하지 않습니다' 가 쓰기 의도로 읽혀 쓰기 도구까지 실렸고, 모델은 아무 도구도
부르지 않고 글로 답했다.

여기서 고정하는 것: (1) 부정문은 쓰기 의도가 아니다, (2) '분명한 PC 작업' 판정,
(3) 그 판정일 때만 강제 선택이 실린다, (4) 판정이 아닌 턴은 예전과 같다.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from app import chat_pc_drive

ROUTES = Path(__file__).resolve().parents[1] / "app" / "orchestration_routes.py"

#: 운영에서 실제로 문제가 된 문장. 쓰기 낱말이 부정으로만 등장한다.
CANARY_SENTENCE = (
    "연결된 PC의 C:\\ 최상위 항목 목록만 나열해 주세요. "
    "파일 내용은 읽지 않고, 어떤 파일도 변경하지 않습니다."
)


# --- 1) 부정문은 쓰기 의도가 아니다 -------------------------------------------

DENIED = [
    CANARY_SENTENCE,
    "삭제하지 말고 목록만 보여줘",
    "저장하지 않고 그대로 확인만 해줘",
    "이름은 바꾸지 마",
    "파일을 수정하지 않고 보기만 할게",
    "Do not delete anything, just list the files.",
    "show me the folder without editing anything",
]

REQUESTED = [
    "이 파일 이름 바꿔 줘",
    "저장해 줘",
    "로그 파일 삭제해 줘",
    "바탕화면에 있는 파일 옮겨 줘",
    "write the summary to notes.txt",
    "예전 파일 지워 줘",
    # 한 문장이 한 가지 변경을 부정하고 다른 변경을 요청하면 여전히 쓰기 턴이다.
    "변경하지 않습니다. 대신 저장해 주세요",
]


def test_a_denied_write_word_is_not_a_write_request():
    for text in DENIED:
        assert chat_pc_drive.pc_write_intent(text) is False, text


def test_a_real_write_request_is_still_a_write_request():
    for text in REQUESTED:
        assert chat_pc_drive.pc_write_intent(text) is True, text


def test_the_write_tool_is_not_offered_on_the_canary_sentence():
    names = {tool.name for tool in chat_pc_drive.pc_tools_for_turn(CANARY_SENTENCE)}

    assert "files_write" not in names, names
    # 네 개의 읽기 도구는 그대로 남는다.
    assert names == {"query_drives", "files_list", "files", "browser"}, names


def test_a_real_write_turn_still_carries_the_write_tool():
    names = {tool.name for tool in chat_pc_drive.pc_tools_for_turn("이 파일 이름 바꿔 줘")}

    assert "files_write" in names, names


def test_a_non_string_turn_is_never_a_write_request():
    for value in (None, 0, [], {}):
        assert chat_pc_drive.pc_write_intent(value) is False


# --- 2) '분명한 PC 작업' 판정 -------------------------------------------------

# (문장, 지목된 기기, 기기 선택 요청, 기대값)
TABLE = [
    (CANARY_SENTENCE, False, False, True),
    ("C드라이브 목록 보여줘", False, False, True),
    ("내 PC에서 폴더 열어 줘", False, False, True),
    ("바탕화면 파일 찾아줘", False, False, True),
    ("문서 폴더 확인해 줘", False, False, True),
    ("드라이브 목록 나열해 줘", False, False, True),
    ("다운로드 폴더 읽어 줘", False, False, True),
    ("list the files on my PC", False, False, True),
    ("show me the desktop folder", False, False, True),
    ("open the folder on my pc", False, False, True),
    ("find the file on the drive", False, False, True),
    ("이 파일 이름 바꿔 줘", False, False, True),
    # 기기만 지목돼도 PC 작업이다.
    ("그거 해 줘", True, False, True),
    ("그거 해 줘", False, True, True),
    # 일반 질문은 아니다.
    ("파일 형식 설명해 줘", False, False, False),
    ("PC가 뭐야", False, False, False),
    ("드라이브가 뭔지 알려줘", False, False, False),
    ("안녕", False, False, False),
    ("요약해 줘", False, False, False),
    ("오늘 날씨 어때", False, False, False),
    ("what is a file format", False, False, False),
    ("explain how drives work", False, False, False),
    ("", False, False, False),
    # #7841: 외부 서비스를 말한 턴은 PC 작업이 아니다. 그 낱말이 "파일 찾아 줘"
    # 를 남의 드라이브 일로 만든다.
    ("구글 드라이브에서 파일 찾아 줘", False, False, False),
    ("Gmail 첨부 목록 보여 줘", False, False, False),
    ("캘린더 일정 확인해 줘", False, False, False),
    ("find files in google drive", False, False, False),
    ("OneDrive 폴더 목록 나열해 줘", False, False, False),
    # PC 낱말과 외부 이름이 한 문장에 있으면 여전히 False 다: 주소가 남의
    # 드라이브일 수 있고, 기기를 지목하지 않았다. 기기를 지목하면(아래 두 줄)
    # 그 지목이 이긴다.
    ("내 PC에서 구글 폴더 열어 줘", False, False, False),
    ("구글 드라이브 말고 내 PC에서 찾아 줘", True, False, True),
    ("구글 드라이브에서 파일 찾아 줘", False, True, True),
]


def test_the_clear_pc_work_table():
    for text, named, requested, expected in TABLE:
        got = chat_pc_drive.pc_task_intent(
            text, named_device=named, requested_device=requested
        )
        assert got is expected, (text, named, requested, got)
    assert len(TABLE) >= 20


def test_a_named_device_outranks_the_cloud_service_words():
    """기기 지목은 문장의 서비스 이름보다 세다(대표가 기계를 가리켰다)."""

    assert chat_pc_drive.pc_task_intent(
        "구글 드라이브에서 파일 찾아 줘", named_device=True
    ) is True
    assert chat_pc_drive.pc_task_intent(
        "구글 드라이브에서 파일 찾아 줘", requested_device=True
    ) is True
    # 지목이 없으면 서비스 이름이 이긴다.
    assert chat_pc_drive.pc_task_intent("구글 드라이브에서 파일 찾아 줘") is False


def test_the_predicate_keeps_its_two_shapers():
    params = inspect.signature(chat_pc_drive.pc_task_intent).parameters

    assert set(params) == {"user_text", "named_device", "requested_device"}
    assert params["named_device"].default is False
    assert params["requested_device"].default is False


# --- 3) 판정일 때만 강제 선택이 실린다 ----------------------------------------

def test_the_router_asks_for_a_tool_only_on_a_clear_pc_turn():
    source = ROUTES.read_text(encoding="utf-8")

    assert "FORCED_REQUIRED = \"required\"" in source
    start = source.index("tool_choice = \"auto\"")
    pressed = source.index("tool_choice = \"required\"")
    assert start < pressed, (start, pressed)
    # 판정 함수 호출과 그 결과가 강제로 바뀌는 자리가 같은 블록 안에 있다.
    block = source[start:pressed]
    assert "if tools and pc_task_intent(" in block, block
    assert "timing.set_forced(FORCED_REQUIRED)" in source


def test_the_default_choice_stays_auto_so_other_turns_do_not_change():
    source = ROUTES.read_text(encoding="utf-8")

    # 세 함수(스트림 열기·JSON·NDJSON) 모두 기본값은 auto 다.
    assert source.count('tool_choice: str = "auto"') == 3
    # 도구가 없으면 선택을 싣지 않는다(종전과 같은 요청).
    opener = source[source.index("async def _model_first_open_stream("):]
    opener = opener[: opener.index("async def _answer_model_first(")]
    assert "if tools:" in opener
    assert opener.count("tool_choice=tool_choice") == 1


def test_no_extra_question_is_asked_when_the_provider_takes_the_choice():
    source = ROUTES.read_text(encoding="utf-8")

    # 강제 선택을 지원하므로 같은 모델에 두 번 묻는 경로를 만들지 않는다.
    assert "retry" not in source.split("_answer_model_first")[0][-400:]
    assert source.count("set_forced(") == 1


def test_the_forced_field_only_carries_the_three_names():
    from app.orchestration_timing import OrchestrationTiming

    timing = OrchestrationTiming()
    assert " forced=none " in timing.line()
    timing.set_forced("required")
    assert " forced=required " in timing.line()
    timing.set_forced("retry")
    assert " forced=retry " in timing.line()
    # 이름이 아닌 값은 거부된다.
    timing.set_forced("tool_name_secret")
    assert " forced=retry " in timing.line()


def test_the_write_denial_rule_is_one_matcher():
    # 래칫: 판정 규칙이 늘어나지 않도록 부정 규칙은 세 개의 좁은 정규식뿐이다.
    names = [
        name
        for name in dir(chat_pc_drive)
        if re.fullmatch(r"_PC_WRITE_DENIAL(_EN_(BEFORE|AFTER))?", name)
    ]
    assert sorted(names) == [
        "_PC_WRITE_DENIAL",
        "_PC_WRITE_DENIAL_EN_AFTER",
        "_PC_WRITE_DENIAL_EN_BEFORE",
    ], names