"""HttpxTelegramReadPort contract tests (#2353).

All tests use ``httpx.MockTransport`` so no real network call is ever made.
The bot token is a fake sentinel; assertions prove it never leaks through
exception strings, causes or contexts.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from padiem_ai_core.telegram_capability import (
    TELEGRAM_BASE_URL,
    TELEGRAM_READONLY_AUTH_SCOPE,
)
from app.telegram_port_httpx import (
    ALLOWED_TELEGRAM_METHOD_PATHS,
    ENGINE_TELEGRAM_BOT_TOKEN,
    ENGINE_TELEGRAM_PAIRED_CHAT_IDS,
    HttpxTelegramReadPort,
    parse_paired_chat_ids,
)

FAKE_TOKEN = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAA"
PAIRED_CHAT_ID = -1001234567890
PORT_KWARGS = {"bot_token": FAKE_TOKEN, "paired_chat_ids": frozenset({PAIRED_CHAT_ID})}

ME_RESPONSE = httpx.Response(200, json={"ok": True, "result": {"id": 123456, "username": "padiem_beta_bot", "first_name": "P", "is_bot": True}})
CHAT_RESPONSE = httpx.Response(200, json={"ok": True, "result": {"id": PAIRED_CHAT_ID, "type": "supergroup", "title": "Padiem Ops"}})


def _handler(provider_responses: list[httpx.Response], recorded: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append((str(request.url), request.method))
        return provider_responses.pop(0)

    return httpx.MockTransport(handler)


def _run(coro):
    return asyncio.run(coro)


def _get(port, *, path="/getMe", query=None, scopes=(TELEGRAM_READONLY_AUTH_SCOPE,), base_url=TELEGRAM_BASE_URL):
    return _run(port.get_json(
        binding_ref="bind:tg", actor_ref="actor:1",
        required_scopes=scopes, base_url=base_url,
        path=path, query=query or {}, timeout_seconds=30,
        max_response_bytes=128_000,
    ))


def test_secret_names_declared_not_values() -> None:
    assert ENGINE_TELEGRAM_BOT_TOKEN == "ENGINE_TELEGRAM_BOT_TOKEN"
    assert ENGINE_TELEGRAM_PAIRED_CHAT_IDS == "ENGINE_TELEGRAM_PAIRED_CHAT_IDS"


def test_get_me_projects_bounded_official_api_call() -> None:
    calls: list = []
    port = HttpxTelegramReadPort(**PORT_KWARGS, transport=_handler([ME_RESPONSE], calls))
    body = _get(port)
    assert body["result"]["is_bot"] is True
    assert calls[0][0].startswith("https://api.telegram.org/bot")
    assert calls[0][1] == "GET"


def test_get_chat_allowed_for_paired_chat_only() -> None:
    calls: list = []
    port = HttpxTelegramReadPort(**PORT_KWARGS, transport=_handler([CHAT_RESPONSE], calls))
    body = _get(port, path="/getChat", query={"chat_id": str(PAIRED_CHAT_ID)})
    assert body["result"]["id"] == PAIRED_CHAT_ID
    assert len(calls) == 1


def test_unpaired_chat_fails_closed_without_network() -> None:
    calls: list = []
    port = HttpxTelegramReadPort(**PORT_KWARGS, transport=_handler([], calls))
    with pytest.raises(ValueError) as exc_info:
        _get(port, path="/getChat", query={"chat_id": "-1009999999999"})
    assert str(exc_info.value) == "chat_not_paired"
    assert calls == []


def test_empty_allowlist_blocks_every_chat_read() -> None:
    port = HttpxTelegramReadPort(
        bot_token=FAKE_TOKEN, paired_chat_ids=frozenset(), transport=_handler([], [])
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port, path="/getChat", query={"chat_id": str(PAIRED_CHAT_ID)})
    assert str(exc_info.value) == "chat_not_paired"


def test_chat_id_zero_or_non_numeric_rejected() -> None:
    port = HttpxTelegramReadPort(
        bot_token=FAKE_TOKEN,
        paired_chat_ids=frozenset({PAIRED_CHAT_ID, 0}),
        transport=_handler([], []),
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port, path="/getChat", query={"chat_id": "0"})
    assert str(exc_info.value) == "chat_not_paired"
    with pytest.raises(ValueError) as exc_info:
        _get(port, path="/getChat", query={"chat_id": "not-a-number"})
    assert str(exc_info.value) == "chat_id_invalid"


def test_scope_not_permitted_rejected() -> None:
    port = HttpxTelegramReadPort(**PORT_KWARGS, transport=_handler([], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port, scopes=(TELEGRAM_READONLY_AUTH_SCOPE, "telegram.send"))
    assert str(exc_info.value) == "scope_not_permitted"


def test_method_not_permitted_rejected() -> None:
    port = HttpxTelegramReadPort(**PORT_KWARGS, transport=_handler([], []))
    assert ALLOWED_TELEGRAM_METHOD_PATHS == frozenset({"/getMe", "/getChat"})
    for path in ("/sendMessage", "/sendDocument", "/editMessageText", "/answerCallbackQuery", "/setWebhook"):
        with pytest.raises(ValueError) as exc_info:
            _get(port, path=path)
        assert str(exc_info.value) == "method_not_permitted"


def test_host_not_permitted_rejected() -> None:
    port = HttpxTelegramReadPort(**PORT_KWARGS, transport=_handler([], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port, base_url="https://evil.example.com")
    assert str(exc_info.value) == "host_not_permitted"


def test_response_too_large_aborts_stream() -> None:
    big = httpx.Response(200, content=b"x" * (128_001))
    port = HttpxTelegramReadPort(**PORT_KWARGS, transport=_handler([big], []))
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "response_too_large"


def test_provider_http_5xx_mapped_without_body() -> None:
    port = HttpxTelegramReadPort(
        **PORT_KWARGS, transport=_handler([httpx.Response(500, content=b"internal")], [])
    )
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    assert str(exc_info.value) == "provider_http_500"


def test_network_exception_never_leaks_token_url() -> None:
    class ExplodingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"connect failed for {request.url}")

    port = HttpxTelegramReadPort(**PORT_KWARGS, transport=ExplodingTransport())
    with pytest.raises(ValueError) as exc_info:
        _get(port)
    message = str(exc_info.value)
    assert FAKE_TOKEN not in message
    assert "api.telegram.org" not in message
    assert "bot" not in message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_invalid_token_shape_rejected_at_construction() -> None:
    for bad in ("", "nocolon", "abc:DEF", "12345:" + "A" * 20 + " spaces"):
        with pytest.raises(ValueError) as exc_info:
            HttpxTelegramReadPort(bot_token=bad, paired_chat_ids=frozenset({1}))
        assert str(exc_info.value) == "bot_token_invalid"


def test_parse_paired_chat_ids_is_bounded_and_fail_closed() -> None:
    assert parse_paired_chat_ids(None) == frozenset()
    assert parse_paired_chat_ids("  ") == frozenset()
    assert parse_paired_chat_ids(f"{PAIRED_CHAT_ID}, 777 ,") == frozenset({PAIRED_CHAT_ID, 777})
    with pytest.raises(ValueError) as exc_info:
        parse_paired_chat_ids("not-a-chat-id")
    assert str(exc_info.value) == "chat_id_invalid"
    with pytest.raises(ValueError):
        parse_paired_chat_ids("0")
