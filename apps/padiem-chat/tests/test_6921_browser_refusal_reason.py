"""#6921: a 422 from the browser chat contract names WHY in the journal.

Until now every refusal of /api/chat/stream and /api/chat was journaled as
``status 422, error_code invalid_request`` and nothing else, so the seven
422s of 2026-11-05 07:00 KST could not be diagnosed from the log. Each
refusal now carries a bounded ASCII reason label on the exception and the two
422 sites emit one ``ai_stage`` line with that label — never the body, the
user text or any request value.
"""
from __future__ import annotations

import json
import logging

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.request_contract import (
    BrowserRequestError,
    StaleChatClientError,
    _validate_payload,
    _validate_payload_parts,
)
from app.request_telemetry import _SAFE_VALUE

SESSION_SECRET = "issue-6921-session-secret-not-a-real-credential-000000"
USER_TEXT = "private-prompt-marker-6921"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="issue-6921.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


def _reason_of(payload) -> str:
    with pytest.raises(BrowserRequestError) as info:
        _validate_payload(payload)
    return info.value.reason


# --- the contract names every refusal ---------------------------------------

USER_TURN = {"role": "user", "content": "hello"}


@pytest.mark.parametrize(
    "payload, reason",
    [
        ("not an object", "body_not_object"),
        ({"messages": [USER_TURN], "role": "system"}, "unsupported_key:role"),
        ({"messages": [USER_TURN], "weird key!": 1}, "unsupported_key:other"),
        ({"messages": [USER_TURN], "util": "calendar"}, "util_scope_invalid"),
        ({"messages": [USER_TURN], "pc_run_id": "nope"}, "pc_run_id_invalid"),
        ({"messages": [USER_TURN], "calendar_turn_id": ""}, "calendar_turn_id_invalid"),
        ({"messages": [USER_TURN], "skill": ""}, "skill_shape"),
        ({"messages": [USER_TURN], "skill": "nonexistent-mode"}, "skill_unknown"),
        ({"messages": []}, "messages_empty"),
        ({"messages": [{"role": "user"}]}, "message_shape"),
        ({"messages": [{"role": "system", "content": "x"}]}, "message_role"),
        ({"messages": [{"role": "user", "content": "   "}]}, "message_empty"),
        ({"messages": [{"role": "assistant", "content": "x"}]}, "no_user_message"),
        ({"messages": [USER_TURN], "tool_input": "x"}, "tool_input_without_tool"),
        ({"messages": [USER_TURN], "tool": ""}, "tool_shape"),
        ({"messages": [USER_TURN], "tool": "no-such-tool"}, "tool_unknown"),
        ({"messages": [USER_TURN], "conversation_id": "claw_" + "b" * 32}, "conversation_or_project_id_invalid"),
        ({"messages": [USER_TURN], "custom": {"provider": "p", "model": "m"}, "tier": "free"}, "custom_with_tier"),
        ({"messages": [USER_TURN], "custom": {"provider": "p"}}, "custom_shape"),
        ({"messages": [USER_TURN], "custom": {"provider": "p", "model": "m", "reasoning_effort": "max"}}, "custom_reasoning_effort"),
    ],
)
def test_every_refusal_carries_its_own_reason(payload, reason):
    assert _reason_of(payload) == reason


def test_a_retired_client_contract_is_named_as_stale():
    with pytest.raises(StaleChatClientError) as info:
        _validate_payload_parts({"messages": [USER_TURN], "mode": "auto"})
    assert info.value.reason == "stale_client"
    assert info.value.code == "stale_chat_client"


def test_the_public_code_and_message_are_unchanged_by_the_reason():
    with pytest.raises(BrowserRequestError) as info:
        _validate_payload_parts({"messages": []})
    assert info.value.code == "invalid_request"
    assert str(info.value) == "대화 내용은 1개 이상 보내 주세요."
    assert BrowserRequestError("x").reason == "invalid_request"


def test_reason_labels_are_journal_safe_and_never_echo_user_text():
    payloads = [
        {"messages": [USER_TURN], USER_TEXT: 1},
        {"messages": [USER_TURN], "role": USER_TEXT},
        {"messages": [{"role": USER_TEXT, "content": "x"}]},
        {"messages": [USER_TURN], "skill": USER_TEXT},
        {"messages": [USER_TURN], "tool": USER_TEXT},
    ]
    for payload in payloads:
        reason = _reason_of(payload)
        assert _SAFE_VALUE.fullmatch(reason), reason
        assert USER_TEXT not in reason


# --- the two 422 sites journal the reason ------------------------------------


def _attach(caplog):
    logger = logging.getLogger("padiem_chat.request")
    logger.addHandler(caplog.handler)
    return logger


def _stage_lines(caplog):
    lines = []
    for record in caplog.records:
        text = record.getMessage()
        if '"event":"ai_stage"' not in text:
            continue
        lines.append(json.loads(text))
    return lines


async def _post(app, path, content, content_type="application/json"):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        return await client.post(path, content=content, headers={"content-type": content_type})


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/chat/stream", "/api/chat"])
@pytest.mark.parametrize(
    "body, reason",
    [
        (json.dumps({"messages": [{"role": "user", "content": USER_TEXT}], "role": "system"}), "unsupported_key:role"),
        (json.dumps({"messages": [{"role": "user", "content": "   "}]}), "message_empty"),
        (json.dumps({"messages": [{"role": "user", "content": USER_TEXT}], "tier": "diamond"}), "unknown_product_tier"),
        ("{" + USER_TEXT, "json_decode"),
        (b"\xff\xfe" + USER_TEXT.encode(), "utf8_decode"),
    ],
)
async def test_a_422_leaves_one_journal_line_naming_the_reason(caplog, path, body, reason):
    logger = _attach(caplog)
    try:
        app = create_app(_settings())
        with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
            response = await _post(app, path, body)
    finally:
        logger.removeHandler(caplog.handler)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    stages = [line for line in _stage_lines(caplog) if line["stage"] == "browser.validate"]
    assert len(stages) == 1, caplog.text
    assert stages[0]["outcome"] == "error"
    assert stages[0]["code"] == reason
    assert stages[0]["request_id"]
    assert USER_TEXT not in caplog.text


async def _raw_post(app, path, body: bytes, headers: list[tuple[str, str]]):
    """A bare ASGI call: httpx rewrites Content-Length, so a malformed header
    can only reach the route this way."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        "client": ("127.0.0.1", 12345),
        "server": ("chat.example.test", 443),
    }
    sent = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    return status


@pytest.mark.asyncio
async def test_a_bad_content_length_header_is_journaled_too(caplog):
    logger = _attach(caplog)
    try:
        app = create_app(_settings())
        with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
            status = await _raw_post(
                app,
                "/api/chat/stream",
                json.dumps({"messages": [USER_TURN]}).encode(),
                [("host", "chat.example.test"), ("content-type", "application/json"), ("content-length", "abc")],
            )
    finally:
        logger.removeHandler(caplog.handler)

    assert status == 422
    stages = [line for line in _stage_lines(caplog) if line["stage"] == "browser.validate"]
    assert [line["code"] for line in stages] == ["content_length_invalid"]


@pytest.mark.asyncio
async def test_an_accepted_body_journals_no_refusal(caplog):
    logger = _attach(caplog)
    try:
        app = create_app(_settings())
        with caplog.at_level(logging.INFO, logger="padiem_chat.request"):
            response = await _post(app, "/api/chat/stream", json.dumps({"messages": [USER_TURN]}))
    finally:
        logger.removeHandler(caplog.handler)

    # The body passed the contract; whatever the route answers next (a guest
    # answer in the mock runtime, or a login challenge) is not a 422.
    assert response.status_code != 422
    assert not [line for line in _stage_lines(caplog) if line["stage"] == "browser.validate"]
