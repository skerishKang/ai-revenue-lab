"""#7273: the external Google calendar is never answered by the internal one.

PADIEM's own calendar store and a connected Google calendar are two different
products. Before this change the internal branch ("구글 캘린더에서 …") answered
first and finished the turn, so a grant-active owner asked Google for a week of
events and received the internal store's empty clarification instead.

The rule is a closed naming list, one product per ask:

* the turn names the external calendar -> the connector lane (grant active) or
  the missing-connection guidance (no grant); the internal branch never runs;
* the turn does not name it -> the internal branch answers exactly as before,
  including the pre-existing rule that a *general* read ask from a grant-active
  owner is served by the connected Google calendar (#7088 후속).
"""

from __future__ import annotations

import pytest

from app import chat_connector_tools as connector_tools
from app.chat_connector_tools import (
    GOOGLE_CALENDAR_CONNECT_NOTE,
    google_calendar_named,
)
from test_chat_connector_calendar_drive_e2e_261107 import (  # noqa: F401 - harness
    CALENDAR_QUESTION,
    CALENDAR_TITLE,
    _B14Gateway,
    _GoogleToolEngine,
    _client,
    _patch_grant,
    _post,
)

GOOGLE_CALENDAR_QUESTION = "구글 캘린더에서 이번 주 일정 찾아줘"
PLAIN_CALENDAR_QUESTION = "이번 주 일정 알려줘"


# ---------------------------------------------------------------------------
# The naming list is closed: these are the only expressions that switch product.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "구글 캘린더에서 이번 주 일정 찾아줘",
        "구글캘린더 일정 보여줘",
        "구글  캘린더 이번주",
        "Google Calendar this week",
        "google calendar 일정",
        "GOOGLE CALENDAR EVENTS",
    ],
)
def test_the_external_calendar_naming_list(text: str) -> None:
    assert google_calendar_named(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        None,
        "이번 주 일정 알려줘",
        "캘린더 보여줘",
        "오늘 일정 등록해줘",
        "구글 드라이브에서 견적서 찾아줘",
        "구글 메일 확인해줘",
        "Google Drive files",
        "지메일 읽어줘",
    ],
)
def test_the_internal_calendar_keeps_every_other_ask(text) -> None:
    assert google_calendar_named(text) is False


def test_the_two_calendars_never_share_an_answer() -> None:
    """A mixed sentence names Google, so it belongs to the external product."""

    assert google_calendar_named("구글 캘린더 말고 내 PADIEM 일정 보여줘") is True


# ---------------------------------------------------------------------------
# Behaviour through the real route.
# ---------------------------------------------------------------------------


def _calendar_gateway(monkeypatch: pytest.MonkeyPatch) -> _B14Gateway:
    return _B14Gateway(
        tool_name="calendar_read",
        tool_arguments={
            "calendarId": "primary",
            "timeMin": "2026-11-09T00:00:00+09:00",
            "timeMax": "2026-11-16T00:00:00+09:00",
        },
        answer=f"Google 캘린더에서 '{CALENDAR_TITLE}' 일정을 확인했습니다.",
        expected_context_title=CALENDAR_TITLE,
    )


def _spy_native(monkeypatch: pytest.MonkeyPatch, *, answer: str = "자체 캘린더 답변"):
    """Replace the internal calendar execution and record whether it ran."""

    from app import chat_routes

    calls: list[str] = []

    async def _native(request, store, uid, messages, timezone_name=None, turn_key=None):
        calls.append(str(turn_key))
        return {"answer": answer}

    monkeypatch.setattr(chat_routes, "try_native_calendar_chat", _native)
    return calls


def test_naming_google_hands_the_turn_to_the_connector_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grant(monkeypatch, drive=False, calendar=True)
    native_calls = _spy_native(monkeypatch)
    gateway = _calendar_gateway(monkeypatch)

    with _client(gateway, _GoogleToolEngine()) as client:
        response = _post(client, GOOGLE_CALENDAR_QUESTION, tier="max")

    assert response.status_code == 200, response.text
    # The external product answered: the tool was declared and executed.
    assert gateway.requests and gateway.requests[0].get("tools")
    assert [tool["function"]["name"] for tool in gateway.requests[0]["tools"]] == [
        "calendar_read"
    ]
    assert CALENDAR_TITLE in response.text
    # The internal calendar was never consulted for this ask.
    assert native_calls == []


def test_naming_google_works_without_a_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live shape: no ``timezone`` in the payload.

    Without a timezone the internal planner can only answer "which range?" —
    and before this change that clarification finished the turn, which is
    exactly what the 11-09 live recheck observed (0 events, no tool call).
    """

    _patch_grant(monkeypatch, drive=False, calendar=True)
    native_calls = _spy_native(monkeypatch)
    gateway = _calendar_gateway(monkeypatch)

    with _client(gateway, _GoogleToolEngine()) as client:
        response = client.post(
            "/api/chat/stream",
            json={
                "messages": [{"role": "user", "content": GOOGLE_CALENDAR_QUESTION}],
                "tier": "max",
            },
        )

    assert response.status_code == 200, response.text
    assert native_calls == []
    assert gateway.requests and gateway.requests[0].get("tools")
    assert CALENDAR_TITLE in response.text


def test_naming_google_without_a_grant_states_the_missing_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grant(monkeypatch, drive=False, calendar=False)
    native_calls = _spy_native(monkeypatch)
    gateway = _calendar_gateway(monkeypatch)

    with _client(gateway, _GoogleToolEngine()) as client:
        response = _post(client, GOOGLE_CALENDAR_QUESTION, tier="max")

    assert response.status_code == 200, response.text
    assert GOOGLE_CALENDAR_CONNECT_NOTE in response.text
    assert "event: done" in response.text
    # Neither product pretends to answer: no tools, no internal calendar, and
    # no model turn that could describe a schedule it never read.
    assert native_calls == []
    assert gateway.requests == []


def test_a_plain_calendar_ask_keeps_the_internal_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Google naming and no grant: exactly the pre-#7273 response path."""

    _patch_grant(monkeypatch, drive=False, calendar=False)
    native_calls = _spy_native(monkeypatch, answer="자체 캘린더에서 2건을 찾았습니다.")
    gateway = _calendar_gateway(monkeypatch)

    with _client(gateway, _GoogleToolEngine()) as client:
        response = _post(client, PLAIN_CALENDAR_QUESTION, tier="max")

    assert response.status_code == 200, response.text
    assert "자체 캘린더에서 2건을 찾았습니다." in response.text
    assert len(native_calls) == 1
    assert gateway.requests == []


def test_the_plain_question_stays_with_the_padiem_calendar_for_a_granted_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """대표 결정(#7273 후속): grant가 있어도 이름 없는 일정 질문은 PADIEM."""

    _patch_grant(monkeypatch, drive=False, calendar=True)
    native_calls = _spy_native(monkeypatch, answer="자체 캘린더에서 1건을 찾았습니다.")
    gateway = _calendar_gateway(monkeypatch)

    with _client(gateway, _GoogleToolEngine()) as client:
        response = _post(client, CALENDAR_QUESTION, tier="max")

    assert response.status_code == 200, response.text
    assert "자체 캘린더에서 1건을 찾았습니다." in response.text
    assert len(native_calls) == 1
    assert gateway.requests == [], "Google connector tools never answered this ask"


def test_the_naming_check_does_not_run_for_a_project_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project turn is never handed to the connector lane."""

    from app import chat_routes

    source = __import__("inspect").getsource(chat_routes._api_chat_stream_body)
    assert "browser_project_id is not None" in source
    assert "calendar_turn_product(latest_user_text" in source
    assert "GOOGLE_CALENDAR_CONNECT_NOTE" in source
    assert "calendar_read_reachable(request, uid=uid)" in source


def test_the_connect_note_is_user_facing_only() -> None:
    assert "Google 캘린더" in GOOGLE_CALENDAR_CONNECT_NOTE
    for forbidden in ("workspace", "authsession", "b62", "binding", "token"):
        assert forbidden not in GOOGLE_CALENDAR_CONNECT_NOTE
    assert connector_tools.CONNECTOR_UNAVAILABLE_NOTE != GOOGLE_CALENDAR_CONNECT_NOTE
