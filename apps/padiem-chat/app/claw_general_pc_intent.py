"""B54 Claw general: PC intent detection helpers (#7809 2/13).

Declarations moved byte-for-byte from claw_general_routes; only their module
location and dependency imports change. The entry module re-exports every name.
"""

from __future__ import annotations

import re

from .claw_desktop_intent import (
    DESKTOP_EXCEPTION_WORDS,
    desktop_exception_matched,
    explicit_pc_instruction,
    screen_coordinates,
)


def _requested_local_txt_path(user_text: str) -> tuple[bool, str | None]:
    """Narrow first-party PC TXT read intent: no model or browser-made grant."""
    compact = "".join(user_text.lower().split())
    if not any(marker in compact for marker in (
        "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "mypc", "mycomputer",
    )):
        return False, None
    if not re.search("읽어|보여|열어|확인해|read|open|show", user_text, re.I):
        return False, None
    if ".txt" not in user_text.lower():
        return False, None
    matches = []
    for word in user_text.split():
        token = word.strip(".,!?()[]'\\\"“”‘’")
        for particle in ("에서", "를", "을", "은", "도", "이"):
            if token.lower().endswith(".txt" + particle):
                token = token[:-len(particle)]
                break
        if token.lower().endswith(".txt"):
            matches.append(token)
    return True, matches[0] if len(matches) == 1 else None


_COMMAND_PC_MARKERS = (
    "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "com1", "mypc", "mycomputer",
)
#: Imperative forms only: a description of a command must not execute it.
_COMMAND_VERBS = ("실행해", "실행하", "run ", "execute ")
#: #4139: a command is ordinary text — Korean, quotes, tabs and several lines
#: are allowed, and there is no product length rule. The former 512-character
#: and then 8,192-character caps were trial limits that rejected normal work, so
#: the size of a command is bounded by the transport it arrives on
#: (MAX_CLAW_GENERAL_BODY_BYTES) and by the row it is stored in, both checked at
#: their own boundary. Here only the characters that break the lane are refused:
#: NUL and CR (neither survives the exec/transcript path) and the other C0
#: controls and DEL.
_COMMAND_BODY = re.compile(r"[^\x00-\x08\x0b-\x1f\x7f]+")


def _requested_local_command(user_text: str) -> tuple[bool, str | None]:
    """Explicit, delimited terminal command for the verified owner PC.

    #4139 terminal lane. The command must be BOTH named as a PC action and
    written in exactly one backtick span, so ordinary prose ("내 PC에서 실행
    계획을 알려줘") never becomes a remote execution. Anything ambiguous is not
    this lane and falls through to the model.
    """
    if not isinstance(user_text, str) or not user_text:
        return False, None
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if not any(marker in compact for marker in _COMMAND_PC_MARKERS):
        return False, None
    if not any(verb in lowered for verb in _COMMAND_VERBS):
        return False, None
    # A delimited command may span several lines; only a backtick, NUL or CR
    # ends the span, so a multi-line script is ordinary input. The span itself
    # carries no length rule — the request envelope bounds it.
    matches = re.findall(r"`([^`\x00\r]*)`", user_text)
    if len(matches) != 1:
        return False, None
    command = matches[0].strip()
    if _COMMAND_BODY.fullmatch(command) is None:
        return False, None
    return True, command


#: #4139: a natural-language PC query needs no backtick. The user asks about
#: their verified PC in prose ("내 PC에 데이터베이스가 있나?") and Claw runs a
#: bounded inventory command on that PC instead of answering from model memory.
#: Conservative: only clear PC-state questions with a recognizable subject map
#: to a command; everything else falls through to the model.
_NATURAL_PC_QUERY_MARKERS = (
    "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "com1", "mypc", "mycomputer",
)
_NATURAL_PC_QUERY_NOUNS = (
    "데이터베이스", "db", "파일", "폴더", "디렉터리", "프로그램", "서비스",
    "프로세스", "호스트", "hostname", "정보", "상태", "인벤토리",
    "드라이브", "디스크", "drive", "disk",
)
_NATURAL_PC_QUERY_VERBS = (
    "있", "뭐", "무엇", "확인", "조회", "목록", "리스트", "검색", "찾",
    "보여", "알려", "인벤토리", "어떻",
)


def _natural_pc_query_command(user_text: str) -> str | None:
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if any(marker in compact for marker in ("데이터베이스", "db")):
        return (
            "Get-ChildItem -Path C:\\ -Recurse -Include *.db,*.sqlite,*.sqlite3,"
            "*.mdf,*.ldb -ErrorAction SilentlyContinue | Select-Object -First 50 "
            "| ForEach-Object { $_.FullName }"
        )
    if any(marker in compact for marker in ("드라이브", "디스크", "drive", "disk")):
        # Cmdlet-only: no native exit is observed, so the lane records the
        # honest no_exit_code termination. The drive list itself is carried
        # as JSON in the transcript.
        return (
            "Get-PSDrive -PSProvider FileSystem | "
            "Select-Object Name,Root,Used,Free | ConvertTo-Json"
        )
    if "hostname" in lowered or "호스트" in lowered:
        return "hostname.exe"
    return None


def _requested_natural_pc_query(user_text: str) -> tuple[bool, str | None]:
    """Natural-language PC state query for the verified owner PC.

    #4139. No backtick is required: a clear question about the verified PC's
    state ("내 PC에 데이터베이스가 있나?") becomes one bounded command on that
    PC. Ambiguous prose falls through to the model, so ordinary chat never
    becomes remote execution.
    """
    if not isinstance(user_text, str) or not user_text:
        return False, None
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if not any(marker in compact for marker in _NATURAL_PC_QUERY_MARKERS):
        return False, None
    if not any(noun in lowered for noun in _NATURAL_PC_QUERY_NOUNS):
        return False, None
    if not any(verb in lowered for verb in _NATURAL_PC_QUERY_VERBS):
        return False, None
    # A backtick command is the explicit lane; do not double-handle it.
    if "`" in user_text:
        return False, None
    command = _natural_pc_query_command(user_text)
    if command is None:
        return False, None
    return True, command


# #6460: a document kind is a file noun too, so "내 PC에서 견적 들어간 엑셀
# 찾아줘" reaches the PC file tools instead of ordinary chat.
_PC_FILE_NOUNS = (
    "파일", "폴더", "디렉터리", "디렉토리", "txt", "문서", "엑셀", "xlsx",
    "워드", "docx", "한글", "hwpx", "pdf", "csv", "스프레드시트", "프레젠테이션",
)
_PC_FILE_VERBS = ("목록", "리스트", "보여", "읽", "내용", "설명", "찾", "열어", "검색")


def _requested_natural_pc_files(user_text: str) -> bool:
    """Natural-language PC folder/file task for the model's file tools.

    This only selects the model-driven PC file plan; the model chooses the
    folder/file arguments from the verified context and uses the actual tool
    results. A surface drive question stays on the drive lane, and a backtick
    command stays on the explicit terminal lane.
    """
    if not isinstance(user_text, str) or not user_text:
        return False
    if "`" in user_text:
        return False
    # An explicit named .txt path keeps the existing single-file TXT lane
    # (which resolves the deployment-mapped file); the model file plan is for
    # folder listing + a file chosen from the actual listing.
    if _requested_local_txt_path(user_text)[0]:
        return False
    compact = "".join(user_text.lower().split())
    if not any(marker in compact for marker in _NATURAL_PC_QUERY_MARKERS):
        return False
    lowered = user_text.lower()
    if not any(noun in lowered for noun in _PC_FILE_NOUNS):
        return False
    if not any(verb in lowered for verb in _PC_FILE_VERBS):
        return False
    if any(noun in lowered for noun in ("드라이브", "디스크", "drive", "disk")):
        return False
    return True


_DESKTOP_PC_MARKERS = (
    "내pc", "내컴퓨터", "로컬pc", "로컬컴퓨터", "com1", "mypc", "mycomputer",
)
#: Desktop verbs only: a description of the screen must not operate it.
_DESKTOP_VERBS = (
    "캡처", "스크린샷", "화면", "클릭", "입력", "타이핑",
    "키보드", "마우스", "메모장", "눌러", "보여",
)


#: #6460 S1: "show me my PC screen" is a read of the same verified PC. These
#: words select the capture lane; nothing here can ever choose another op.
_SCREEN_VIEW_NOUNS = ("화면", "스크린", "screen")
_SCREEN_VIEW_VERBS = (
    "캡처", "스크린샷", "찍", "보여", "봐", "capture", "screenshot", "observe",
)
#: Any of these means the turn asks to operate the PC, which this lane never
#: does. The explicit backtick grammar keeps its own input path.
_SCREEN_INPUT_WORDS = (
    "클릭", "눌러", "입력", "타이핑", "키보드", "마우스", "키 입력",
    "click", "type", "press", "keys",
)


def _requested_read_only_screen_view(user_text: str) -> bool:
    """Read-only screen capture intent for the verified owner PC (#6460 S1).

    No backtick: "내 PC 화면 보여줘" and "지금 화면 캡처해 줘" are ordinary
    requests. The matcher is deliberately narrow — a PC marker plus a screen
    word and a view verb, or a bare screen-capture phrase — and it refuses any
    turn that also names an input action, names a file/txt, asks about drives
    or belongs to the browser lane. Anything ambiguous falls through to the
    model exactly as before.
    """
    if not isinstance(user_text, str) or not user_text:
        return False
    if "`" in user_text:
        return False
    lowered = user_text.lower()
    if any(word in lowered for word in _SCREEN_INPUT_WORDS):
        return False
    if not any(noun in lowered for noun in _SCREEN_VIEW_NOUNS):
        return False
    # A turn that names the browser belongs to the browser lane or the model.
    if "브라우저" in lowered or re.search(r"\bbrowser\b", lowered):
        return False
    # The other PC lanes own their own requests; this one never borrows them.
    if _requested_natural_pc_files(user_text) or _requested_local_txt_path(user_text)[0]:
        return False
    if _requested_natural_pc_query(user_text)[0]:
        return False
    from .pc_browser_intent import requested_pc_browser
    if requested_pc_browser(user_text):
        return False
    # #7561: a screen capture is a PC action, so the sentence must name the
    # owner's PC and be written as an instruction. "스크린샷 찍는 법" or a
    # bare "화면 캡처" without a PC never takes a capture.
    if not explicit_pc_instruction(user_text):
        return False
    return any(verb in lowered for verb in _SCREEN_VIEW_VERBS)


#: #6460: the closed key combos the executor already reviewed (kagent
#: ``_KEY_SEQUENCES``). Anything else stays on the explicit backtick grammar.
_DESKTOP_KEY_PHRASES = (
    (("엔터", "enter", "리턴"), "enter"),
    (("이스케이프", "esc", "탈출"), "esc"),
    (("탭 키", "탭키", "tab"), "tab"),
    (("백스페이스", "backspace"), "backspace"),
    (("delete 키", "딜리트", "삭제 키", "삭제키"), "delete"),
    (("ctrl+s", "컨트롤 s", "저장 키", "저장키"), "ctrl+s"),
    (("ctrl+c", "컨트롤 c", "복사 키", "복사키"), "ctrl+c"),
    (("ctrl+v", "컨트롤 v", "붙여넣기"), "ctrl+v"),
    (("ctrl+a", "컨트롤 a", "전체 선택"), "ctrl+a"),
)
#: #6460 step 2: free text may be typed, but only when the sentence itself
#: carries the value, and the value never enters the dispatch row.
_DESKTOP_TYPING_WORDS = (
    "입력", "타이핑", "type", "타이프",
)
_QUOTED_TEXT_RE = re.compile(r"['\"“”‘’]([^'\"“”‘’\x00\r]{1,20000})['\"“”‘’]")
_MAX_TYPED_CHARS = 20000

#: A request that names one of these is not executed from this lane: the owner
#: is asked first, in the conversation, exactly once.
_DESKTOP_EXCEPTION_WORDS = DESKTOP_EXCEPTION_WORDS


def _desktop_exception_question(user_text: str) -> str | None:
    """The one conversational check the owner asked for (#6460).

    Credential entry, account/permission changes, irreversible destruction and
    anything that sends outside the PC are never started from a plain sentence.
    Everything else runs on the pre-delegated authority without a button.
    """
    if not desktop_exception_matched(user_text):
        return None
    return (
        "이 작업은 비밀번호·계정 변경·되돌릴 수 없는 삭제·외부 발송 중 하나에 해당할 수 있어 "
        "바로 실행하지 않았습니다. 정확히 무엇을 실행하면 될지 한 번만 알려 주세요."
    )


def _requested_desktop_control(user_text: str) -> tuple[bool, str | None]:
    """Plain-language single desktop action for the verified owner PC (#6460).

    Only what the sentence itself fully determines: one reviewed key combo, or
    one click at coordinates the owner wrote. An action that needs the screen
    (``메모장 열고 …``) is not guessed here — it belongs to the model-driven
    desktop lane. Free text is typed only when the sentence quotes the value:
    the value travels once through the one-shot store and the audit row
    keeps a length and a digest prefix, never the text.
    """
    if not isinstance(user_text, str) or not user_text:
        return False, None
    if "`" in user_text:
        return False, None
    lowered = user_text.lower()
    wants_typing = any(word in lowered for word in _DESKTOP_TYPING_WORDS)
    # #7561: every action needs the owner's PC named AND an instruction, on
    # one line. Only a quoted value to type may span lines (it then goes
    # through the confirmation card): the text around it must still be one
    # instruction line, so a pasted document never qualifies.
    quoted = _QUOTED_TEXT_RE.findall(user_text) if wants_typing else []
    instruction = (_QUOTED_TEXT_RE.sub("", user_text, count=1)
                   if len(quoted) == 1 else user_text)
    if not explicit_pc_instruction(instruction):
        return False, None
    if _requested_natural_pc_files(user_text) or _requested_local_txt_path(user_text)[0]:
        return False, None
    if _requested_natural_pc_query(user_text)[0]:
        return False, None
    from .pc_browser_intent import requested_pc_browser
    if requested_pc_browser(user_text):
        return False, None
    wants_click = any(word in lowered for word in ("클릭", "click", "눌러"))
    one_line = "\n" not in user_text.strip()
    coordinates = screen_coordinates(user_text) if wants_click and one_line else None
    if coordinates is not None:
        return True, "desktop:click\n%d,%d" % coordinates
    if wants_typing:
        if len(quoted) == 1 and 0 < len(quoted[0]) <= _MAX_TYPED_CHARS:
            return True, "desktop:type\n" + quoted[0]
        return False, None
    for phrases, combo in _DESKTOP_KEY_PHRASES:
        if any(phrase in lowered for phrase in phrases):
            return True, "desktop:keys\n" + combo
    return False, None


#: #6460 step 3 — a task whose next action depends on what the screen shows is
#: run by the model-driven loop. A one-line instruction that names the owner's
#: PC and carries a task verb selects that lane (#7561). The
#: matcher decides only that the task belongs to that lane; every action is
#: chosen by the model after a fresh capture, and the four exception families
#: are asked once before the loop starts.
_DESKTOP_TASK_VERBS = (
    "열어", "적어", "적고", "써", "쓰고", "입력", "클릭", "눌러",
    "저장", "실행", "선택", "이동", "바꿔",
)


def _requested_desktop_task(user_text: str) -> bool:
    """Plain-language PC task that needs the screen to decide each step.

    The other PC lanes keep their own requests: files, drives, TXT paths, the
    browser and an explicit quoted value never enter this lane, and anything
    the sentence does not clearly make a PC task falls through to the model
    exactly as before.
    """
    if not isinstance(user_text, str) or not user_text:
        return False
    if "`" in user_text:
        return False
    lowered = user_text.lower()
    if not any(word in lowered for word in _DESKTOP_TASK_VERBS):
        return False
    if "브라우저" in lowered or re.search(r"\bbrowser\b", lowered):
        return False
    if any(word in lowered for word in ("파일", "폴더", "드라이브", "디스크")):
        return False
    if _requested_natural_pc_files(user_text) or _requested_local_txt_path(user_text)[0]:
        return False
    if _requested_natural_pc_query(user_text)[0]:
        return False
    from .pc_browser_intent import requested_pc_browser
    if requested_pc_browser(user_text):
        return False
    # #7561: an app name or "화면" alone is not a PC request. The sentence must
    # name the owner's PC and be one line written as an instruction.
    return explicit_pc_instruction(user_text)


def _requested_local_desktop(user_text: str) -> tuple[bool, str | None]:
    """Explicit, delimited desktop op for the verified owner PC.

    #4139 desktop lane. The turn must be BOTH named as a PC desktop action
    and written in exactly one backtick span holding one op
    (``capture`` | ``type:<text>`` | ``keys:<combo>`` | ``click:<x>,<y>``),
    so ordinary prose never becomes remote input. Anything ambiguous is not
    this lane and falls through to the model. The span is converted to the
    canonical ``desktop:<op>`` dispatch body and validated with the same
    grammar the executor enforces.
    """
    if not isinstance(user_text, str) or not user_text:
        return False, None
    lowered = user_text.lower()
    compact = "".join(lowered.split())
    if not any(marker in compact for marker in _DESKTOP_PC_MARKERS):
        return False, None
    if not any(verb in lowered for verb in _DESKTOP_VERBS):
        return False, None
    matches = re.findall(r"`([^`\x00\r]*)`", user_text)
    if len(matches) != 1:
        return False, None
    # #7561: the words around the span are one instruction line naming the
    # owner's PC; a span inside a pasted document never qualifies.
    if not explicit_pc_instruction(re.sub(r"`[^`\x00\r]*`", "", user_text, count=1)):
        return False, None
    span = matches[0].strip()
    head, sep, tail = span.partition(":")
    op = head.strip().lower()
    if op == "capture":
        canonical = "desktop:capture" if not sep else None
    elif op in ("type", "keys", "click"):
        canonical = "desktop:" + op + "\n" + tail.strip(" \t\n") if sep else None
    else:
        canonical = None
    if canonical is None:
        return False, None
    from .oracle_mesh_read_return_routes import _parse_desktop_op_text
    if _parse_desktop_op_text(canonical) is None:
        return False, None
    return True, canonical
