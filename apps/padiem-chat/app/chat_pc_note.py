"""The PC sentence a Chat turn carries (#7165).

The sentence follows the server's verified state instead of a fixed
assumption, because there are three states and they read differently:

* the turn carries PC tools -> describe the connected PC as usable;
* the account's PC is verified connected but this turn carries no tool ->
  say so, and never claim the PC is not connected;
* no verified PC is reachable -> guide the connection.

Before this table a connected-PC turn whose lane carried no tool received the
"PC is not connected, guide the connection" sentence, and the model answered
"PADIEM is a remote AI and cannot reach your computer" while the owner's PC
was connected (#7165, partial attempt #7181).
"""
from __future__ import annotations

import re
from typing import Any

PC_TOOLS_PRESENT_NOTE = (
    "[PC 연결] 이번 턴에는 연결된 PC 도구가 함께 제공됩니다. 사용자가 PC·컴퓨터 "
    "작업을 요청하면 연결된 PC에서 드라이브·파일·브라우저 작업을 수행할 수 있습니다. "
    "이 대화에 없는 셸 명령 실행은 약속하지 말고 Claw의 PC 명령 실행으로 안내하세요. "
    "'원격 AI라 컴퓨터에 접속할 수 없다'고 답하지 마세요. 실제 결과는 도구 실행 "
    "결과로만 답하세요."
)
PC_TOOLS_CONNECTED_NOTE = (
    "[PC 연결] 이번 턴에는 PC 실행 도구가 붙지 않았지만, 이 계정의 PC는 서버에서 "
    "연결 상태가 확인되었습니다. '원격 AI라 컴퓨터에 접속할 수 없다'고 답하지 마세요. "
    "연결 문제가 아니라 이 대화의 실행 범위 때문에 도구가 붙지 않은 것이므로, 그 "
    "차이를 설명하고 셸 명령 실행은 Claw의 PC 명령 실행으로 안내하세요."
)
PC_TOOLS_ABSENT_NOTE = (
    "[PC 연결] 이번 턴에는 PC 도구가 제공되지 않았고, 서버에서 확인된 PC 연결도 "
    "없습니다. '원격 AI라 컴퓨터에 접속할 수 없다'고 단정하지 말고, 사용자가 PC "
    "작업을 요청하면 내 컴퓨터(Claw)에서 PC를 연결하는 방법을 안내하세요."
)


def pc_turn_note(pc_tools: Any, *, pc_connected: bool = False) -> str:
    """The PC sentence for this turn: tools first, then the verified PC state."""

    if pc_tools:
        return PC_TOOLS_PRESENT_NOTE
    return PC_TOOLS_CONNECTED_NOTE if pc_connected else PC_TOOLS_ABSENT_NOTE


#: Presentation-only trigger for the PC sentence. It never opens the PC lane or
#: a tool: it only decides whether a turn that talks about the computer should
#: receive the PC sentence (#7165). The wording itself is chosen by the offered
#: tools and the verified connection, never by this pattern.
_PC_MENTION = re.compile(
    r"(컴퓨터|내\s*PC|로컬\s*PC|\bpc\b|whoami|명령|실행해|드라이브|파일|폴더"
    r"|바탕화면|다운로드)",
    re.IGNORECASE,
)


def pc_note_applies(user_text: Any, pc_tools: Any) -> bool:
    """Whether this turn should carry the PC sentence at all."""

    if pc_tools:
        return True
    return isinstance(user_text, str) and bool(_PC_MENTION.search(user_text))
