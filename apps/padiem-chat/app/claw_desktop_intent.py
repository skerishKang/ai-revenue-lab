"""When a sentence may move the owner's PC (#7561).

The Claw general lane turns a few plain sentences into keyboard input, clicks,
screen captures and the model-driven desktop loop. A sentence becomes such a
candidate only when BOTH hold:

* it names the owner's PC explicitly ("내 PC", "내 컴퓨터", "COM1", "my PC" ...);
* it is written as an instruction, not a question or a request to explain.

A value to type that spans several lines or is long goes through a
confirmation card first, by the same rule the PC command card uses (one line,
``DIRECT_COMMAND_MAX_CHARS`` characters or fewer runs at once).

The model-driven loop is held to the same standard. Only the owner's own
sentence starts input: a loop step may type, click or press keys only inside a
run the owner's sentence staged as a desktop task, and the value a step types
passes the same exception and size checks as the owner's own sentence. Model
output and pasted documents never start a PC action on their own.
"""
from __future__ import annotations

import re
from typing import Any

from .pc_command_confirmation import DIRECT_COMMAND_MAX_CHARS

__all__ = [
    "ACTION_DESKTOP_TASK",
    "ACTION_DESKTOP_TYPE",
    "DESKTOP_EXCEPTION_WORDS",
    "desktop_exception_matched",
    "desktop_type_confirmation_card",
    "direct_typing_eligible",
    "explicit_pc_instruction",
    "is_instruction",
    "loop_step_refusal",
    "names_owner_pc",
    "screen_coordinates",
]

#: The run row a desktop-task sentence stages; loop input needs this row.
ACTION_DESKTOP_TASK = "desktop_task"
#: The run row a typed value waiting for its confirmation card stages.
ACTION_DESKTOP_TYPE = "desktop_type"

#: How the owner names their own PC. Whitespace is removed before matching.
PC_MARKERS = (
    "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "com1", "mypc", "mycomputer",
)

#: A request to explain, compare or answer is never an instruction to the PC,
#: even when it names one ("내 PC 화면 캡처하는 방법 알려줘").
_QUESTION_WORDS = (
    "어떻게", "방법", "하는 법", "하는법", "설명", "알려", "의미", "뜻이", "뜻은",
    "왜", "뭐야", "뭔가", "뭘까", "무엇", "차이", "예시", "궁금", "모르",
    "인가요", "나요", "까요", "을까", "ㄹ까", "될까", "되나", "되요?", "돼?",
    "how ", "how to", "what ", "why ", "explain", "difference",
)

#: Korean request endings, and verb forms that are themselves an imperative.
_KOREAN_REQUEST_ENDINGS = (
    "줘", "줘요", "주세요", "주십시오", "주실래요", "줄래", "줄래요",
    "해라", "하세요", "하십시오", "해봐", "해 봐",
)
_KOREAN_IMPERATIVE_VERBS = (
    "클릭해", "입력해", "타이핑해", "눌러", "열어", "찍어", "캡처해", "캡쳐해",
    "실행해", "저장해", "적어", "닫아", "바꿔", "보여", "선택해", "이동해",
    "붙여넣기해", "붙여 넣어",
)
#: A terse command that is only the action noun ("내 PC 화면 캡처").
_KOREAN_TERSE_COMMANDS = ("캡처", "캡쳐", "스크린샷")
_ENGLISH_IMPERATIVE = re.compile(
    r"^(?:please\s+)?(?:type|click|press|hit|capture|screenshot|take|open|show)\b",
)
_TRAILING = re.compile(r"[\s.!~。…·]+$")


def names_owner_pc(text: str) -> bool:
    """Whether the text names the owner's own PC explicitly."""
    if not isinstance(text, str) or not text:
        return False
    compact = "".join(text.lower().split())
    return any(marker in compact for marker in PC_MARKERS)


def is_instruction(text: str) -> bool:
    """Whether the (last line of the) text is written as an instruction.

    A question mark anywhere, or a request to explain, rules it out. The
    sentence must then end in a request form ("…해 줘", "…주세요"), an
    imperative verb ("눌러", "입력해") or a bare capture command; English must
    start with an imperative verb.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    if "?" in text or "？" in text:
        return False
    lowered = text.lower()
    if any(word in lowered for word in _QUESTION_WORDS):
        return False
    last = _TRAILING.sub("", text.strip().splitlines()[-1].strip())
    if not last:
        return False
    if _ENGLISH_IMPERATIVE.match(last.lower()):
        return True
    return (last.endswith(_KOREAN_REQUEST_ENDINGS)
            or last.endswith(_KOREAN_IMPERATIVE_VERBS)
            or last.endswith(_KOREAN_TERSE_COMMANDS))


def explicit_pc_instruction(text: str, *, single_line: bool = True) -> bool:
    """Both conditions of #7561: the owner's PC is named and it is an instruction.

    ``single_line`` (the default for clicks, keys, captures and desktop tasks)
    also refuses a turn with a line break: a pasted block is never read as one
    instruction. Typing passes ``single_line=False`` and sends a multi-line
    turn to the confirmation card instead.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    if single_line and "\n" in text.strip():
        return False
    return names_owner_pc(text) and is_instruction(text)


_COORDINATES = re.compile(r"(?<![\d.,，])(\d{1,5})\s*[,，]\s*(\d{1,5})(?![\d.,，])")
#: A number written with a unit or currency is an amount, not a coordinate.
_UNIT_AFTER = re.compile(r"\s*(?:원|달러|엔|위안|유로|개|명|건|번째|번|%|퍼센트|km|kg|mb|gb|px)",
                         re.IGNORECASE)


def screen_coordinates(text: str) -> tuple[int, int] | None:
    """The one ``x,y`` pair the sentence writes, or None.

    A thousands-separated amount ("1,000원") is not a coordinate: a value
    followed by a unit is refused, and so is a second number written with a
    leading zero. More than one pair is ambiguous and refused.
    """
    if not isinstance(text, str):
        return None
    found = []
    for match in _COORDINATES.finditer(text):
        second = match.group(2)
        if len(second) > 1 and second.startswith("0"):
            continue
        if _UNIT_AFTER.match(text, match.end()):
            continue
        found.append((int(match.group(1)), int(second)))
    if len(found) != 1:
        return None
    x, y = found[0]
    if not (0 <= x <= 65535 and 0 <= y <= 65535):
        return None
    return x, y


#: A request that names one of these is never started from a plain sentence
#: or from a loop step: the owner is asked first, in the conversation.
DESKTOP_EXCEPTION_WORDS = (
    "비밀번호", "패스워드", "password", "카드 번호", "카드번호", "otp", "인증번호",
    "계정 변경", "계정 설정", "권한 변경", "관리자 권한",
    "삭제", "포맷", "초기화", "되돌릴 수 없는",
    "보내기", "보내 줘", "발송", "게시", "전송", "메일 보내", "메시지 보내",
)


def desktop_exception_matched(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    lowered = text.lower()
    return any(word in lowered for word in DESKTOP_EXCEPTION_WORDS)


def direct_typing_eligible(value: Any) -> bool:
    """One line and short: typed without a card. Same rule as PC commands."""
    return (isinstance(value, str) and 0 < len(value) <= DIRECT_COMMAND_MAX_CHARS
            and "\n" not in value and "\r" not in value)


def desktop_type_confirmation_card(value: str) -> str:
    """The card for a long or multi-line value. Nothing is typed before '네'."""
    lines = value.count("\n") + 1
    preview = value if len(value) <= 300 else value[:300] + "…"
    return (
        "PC 입력 확인: 내 PC에 다음 내용을 입력할까요? (%d줄, %d자) "
        "입력하려면 '네'라고 답해 주세요.\n\n%s" % (lines, len(value), preview)
    )


def _loop_op(desktop_op: str) -> str:
    head = desktop_op.split("\n", 1)[0].strip().lower()
    return head[len("desktop:"):] if head.startswith("desktop:") else head


def loop_step_refusal(run: Any, desktop_op: Any, desktop_text: Any = None) -> str | None:
    """The refusal code for one Engine-chosen desktop step, or None to proceed.

    A capture only looks, so any owner-staged run may take one. Input (type,
    keys, click) runs only inside a run the owner's own sentence staged as a
    desktop task. A typed value must be one short line and must not name an
    exception family: a long or multi-line value would need the owner's card,
    which a loop step cannot show, so the step is refused instead.
    """
    if not isinstance(run, dict) or not isinstance(desktop_op, str):
        return "desktop_run_unverified"
    op = _loop_op(desktop_op)
    if op == "capture":
        return None
    if run.get("action") != ACTION_DESKTOP_TASK:
        return "desktop_input_not_requested"
    value = desktop_text
    if value is None and op == "type":
        _head, _sep, value = desktop_op.partition("\n")
    if op == "type":
        if not direct_typing_eligible(value):
            return "desktop_value_needs_confirmation"
        if desktop_exception_matched(value):
            return "desktop_exception_needs_owner"
    return None
