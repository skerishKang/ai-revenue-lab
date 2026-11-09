"""#7273 후속: one calendar-product rule for both chat routes.

Representative decision (2026-11-09): "캘린더·일정" is answered by the PADIEM
workspace calendar by default; only an explicit "구글 캘린더" names the
external Google one. The streaming body and the orchestration route must
resolve the SAME decision function — these tests fail when either surface
keeps (or grows) its own branch.
"""
from __future__ import annotations

import hashlib
import inspect
import json

import pytest

from app import calendar_product_rule, chat_routes, orchestration_routes
from app.calendar_product_rule import (
    PRODUCT_GOOGLE,
    PRODUCT_PADIEM,
    calendar_turn_product,
    native_calendar_turn_key,
)

# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("이번 주 일정 알려줘", PRODUCT_PADIEM),
        ("내일 일정 뭐야", PRODUCT_PADIEM),
        ("오늘 일정 등록해줘", PRODUCT_PADIEM),
        ("이번 주 스케줄 알려줘", PRODUCT_PADIEM),
        ("구글 캘린더에서 이번 주 일정 찾아줘", PRODUCT_GOOGLE),
        ("Google Calendar this week", PRODUCT_GOOGLE),
        ("구글 드라이브에서 견적서 찾아줘", None),
        ("드라이브에서 견적서 찾아줘", None),
        ("지메일 확인해줘", None),
        ("구글 메일 확인해줘", None),
        ("안녕", None),
        ("", None),
        (None, None),
    ],
)
def test_the_rule_names_one_product_per_ask(text, expected):
    assert calendar_turn_product(text) == expected


def test_a_timezone_never_moves_the_product():
    # Without a timezone the planner answers its own clarification; the ask is
    # still a PADIEM-calendar ask.
    assert calendar_turn_product("이번 주 일정 알려줘") == PRODUCT_PADIEM
    assert (
        calendar_turn_product("이번 주 일정 알려줘", timezone_name="Asia/Seoul")
        == PRODUCT_PADIEM
    )
    assert (
        calendar_turn_product(
            "구글 캘린더에서 이번 주 일정 찾아줘", timezone_name="Asia/Seoul"
        )
        == PRODUCT_GOOGLE
    )


def test_the_turn_key_keeps_the_stream_routes_existing_formula():
    key = native_calendar_turn_key(
        uid="usr_x",
        conversation_id="chat_y",
        message_count=3,
        latest_user_text="이번 주 일정 알려줘",
        timezone_name="Asia/Seoul",
    )
    digest = hashlib.sha256(
        "|".join(("이번 주 일정 알려줘", "Asia/Seoul", "")).encode("utf-8")
    ).hexdigest()[:16]
    assert key == f"chat-usr_x-chat_y-3-{digest}"


# ---------------------------------------------------------------------------
# One function, both routes
# ---------------------------------------------------------------------------


def test_both_routes_resolve_the_very_same_function_object():
    assert (
        chat_routes.calendar_turn_product
        is calendar_product_rule.calendar_turn_product
    )
    assert (
        orchestration_routes.calendar_turn_product
        is calendar_product_rule.calendar_turn_product
    )
    assert (
        chat_routes.native_calendar_turn_key
        is orchestration_routes.native_calendar_turn_key
        is calendar_product_rule.native_calendar_turn_key
    )


def test_each_route_body_calls_the_shared_rule_and_its_own_native_path():
    stream_source = inspect.getsource(chat_routes._api_chat_stream_body)
    orchestration_source = inspect.getsource(
        orchestration_routes._answer_orchestration
    )
    native_source = inspect.getsource(orchestration_routes._answer_native_calendar)
    assert "calendar_turn_product(latest_user_text" in stream_source
    assert "calendar_turn_product(user_text" in orchestration_source
    assert "_answer_native_calendar(" in orchestration_source
    assert "try_native_calendar_chat(" in native_source
    # No surface keeps a private yes/no naming branch beside the rule.
    assert "google_calendar_named(latest_user_text)" not in stream_source
    assert "google_calendar_named(latest_turn_text)" not in orchestration_source


# ---------------------------------------------------------------------------
# Behaviour through the real orchestration route (no model, no network)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestration_answers_a_plain_ask_with_the_padiem_calendar(monkeypatch):
    from test_chat_connector_turn_routing import _install, _payload, _request

    bridge = _install(monkeypatch)
    calls: list[object] = []

    async def _native(request, store, uid, messages, timezone_name=None, turn_key=None):
        calls.append(timezone_name)
        return {
            "answer": "네이티브 일정 1건입니다.",
            "answer_status": "answered_with_native_calendar",
        }

    monkeypatch.setattr(orchestration_routes, "try_native_calendar_chat", _native)
    response = await orchestration_routes.api_orchestration(
        _request(_payload("이번 주 일정 알려줘"))
    )

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["answer"].startswith("네이티브 일정")
    assert calls == [None]
    assert bridge.requests == []


@pytest.mark.asyncio
async def test_orchestration_states_the_missing_connection_for_named_google(monkeypatch):
    from test_chat_connector_turn_routing import (
        CALENDAR_QUESTION,
        _install,
        _patch_truth,
        _payload,
        _request,
    )
    from app.chat_connector_tools import GOOGLE_CALENDAR_CONNECT_NOTE

    bridge = _install(monkeypatch)
    _patch_truth(monkeypatch, overrides={}, authority=False)
    native_calls: list[str] = []

    async def _native(*args, **kwargs):
        native_calls.append("called")
        return {"answer": "should not happen"}

    monkeypatch.setattr(orchestration_routes, "try_native_calendar_chat", _native)
    response = await orchestration_routes.api_orchestration(
        _request(_payload(CALENDAR_QUESTION))
    )

    assert response.status_code == 200
    assert json.loads(response.body)["answer"] == GOOGLE_CALENDAR_CONNECT_NOTE
    assert native_calls == []
    assert bridge.requests == []


@pytest.mark.asyncio
async def test_orchestration_hands_named_google_back_when_the_grant_is_active(monkeypatch):
    from test_chat_connector_turn_routing import (
        CALENDAR_QUESTION,
        CONNECTED,
        _install,
        _patch_truth,
        _payload,
        _request,
    )

    bridge = _install(monkeypatch)
    _patch_truth(
        monkeypatch,
        overrides={"drive": ("not_connected", None), "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    response = await orchestration_routes.api_orchestration(
        _request(_payload(CALENDAR_QUESTION))
    )

    assert response.status_code == 409
    assert (
        json.loads(response.body)["error"]["code"] == "orchestration_not_applicable"
    )
    assert bridge.requests == []
