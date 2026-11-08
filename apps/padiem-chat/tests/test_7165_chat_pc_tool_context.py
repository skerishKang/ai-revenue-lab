"""#7165: the Chat system context follows the PC tools actually offered.

The model used to answer "PADIEM is a remote AI, it cannot reach your computer"
even on a turn where the PC tools were on the wire. The sentence is now chosen
from the turn's own tool tuple: tools present -> the connected PC is described
as usable (with the shell-command lane pointed at Claw), tools absent -> the
model explains the missing PC capability and guides the connection instead of
inventing a "remote AI" limit.
"""
from __future__ import annotations

import asyncio

from starlette.testclient import TestClient

from app.auth import SESSION_COOKIE, create_session_token
from app.chat_pc_drive import CHAT_PC_TOOL_DEFINITIONS
from app.chat_routes import (
    PC_TOOLS_ABSENT_NOTE,
    PC_TOOLS_PRESENT_NOTE,
    pc_note_applies,
    pc_turn_note,
)

from test_5574_frontend_pc_route_harness import (
    CHROME_5574_TEXT,
    GENERAL_5574_TEXT,
    OWNER,
    _AnsweringB14,
    _PcHarness,
)

BASE = "https://chat.example-5574.test"


def _stream_context(*, tools_declared: bool, text: str = CHROME_5574_TEXT) -> str:
    harness = _PcHarness(tools_declared=tools_declared, b14=_AnsweringB14())
    asyncio.run(harness.seed_identity())
    app, config = harness.create_app(orchestration=False)
    with TestClient(app, base_url=BASE) as client:
        client.cookies.set(
            SESSION_COOKIE, create_session_token(config, OWNER),
            domain="chat.example-5574.test", path="/",
        )
        response = client.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": text}]},
        )
        assert response.status_code == 200, response.text
    assert len(harness.b14.calls) == 1, harness.b14.calls
    return harness.b14.calls[0]["additional_system_context"] or ""


def test_a_turn_with_pc_tools_describes_the_connected_pc_as_usable() -> None:
    context = _stream_context(tools_declared=True)
    assert PC_TOOLS_PRESENT_NOTE in context
    assert PC_TOOLS_ABSENT_NOTE not in context
    # The old wrong answer is named and forbidden, not left to the model.
    assert "원격 AI" in context

def test_a_turn_without_pc_tools_guides_the_connection_not_a_remote_ai_limit() -> None:
    context = _stream_context(tools_declared=False, text=CHROME_5574_TEXT)
    assert PC_TOOLS_ABSENT_NOTE in context
    assert PC_TOOLS_PRESENT_NOTE not in context
    assert "연결하는 방법" in context


def test_the_note_is_chosen_by_the_offered_tools_not_by_fixed_text() -> None:
    assert pc_turn_note(CHAT_PC_TOOL_DEFINITIONS) == PC_TOOLS_PRESENT_NOTE
    assert pc_turn_note(()) == PC_TOOLS_ABSENT_NOTE
