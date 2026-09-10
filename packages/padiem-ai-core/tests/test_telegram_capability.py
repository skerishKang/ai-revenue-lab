"""Core Telegram capability contract tests (#2353).

Network-free. Stubs the trusted ``TelegramReadPort`` boundary with a
recording fake; zero provider calls, zero bot tokens, zero sends.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from padiem_ai_core.connector_registry import validate_connector_tools
from padiem_ai_core.contracts import ApprovalPolicy, ToolSideEffect
from padiem_ai_core.telegram_capability import (
    TELEGRAM_API_HOST,
    TELEGRAM_BASE_URL,
    TELEGRAM_CALLBACK_DATA_MAX_BYTES,
    TELEGRAM_CANONICAL_TOOL_IDS,
    TELEGRAM_CONNECTOR_ID,
    TELEGRAM_DESCRIPTOR,
    TELEGRAM_GET_BOT_INFO_TOOL_ID,
    TELEGRAM_GET_CHAT_INFO_TOOL_ID,
    TELEGRAM_PROVIDER_CLOUD_DOWNLOAD_LIMIT_BYTES,
    TELEGRAM_PROVIDER_CLOUD_SEND_DOCUMENT_LIMIT_BYTES,
    TELEGRAM_RAW_BOT_TOKEN_IN_CORE,
    TELEGRAM_READONLY_AUTH_SCOPE,
    TELEGRAM_READ_TOOL_IDS,
    TELEGRAM_SEND_AUTH_SCOPE,
    MAX_TELEGRAM_CHATS,
    MAX_TELEGRAM_FILE_BYTES,
    MAX_TELEGRAM_FILES_PER_UPDATE,
    MAX_TELEGRAM_MESSAGE_CHARS,
    MAX_TELEGRAM_SENDERS_PER_CHAT,
    TelegramBotInfo,
    TelegramCapability,
    TelegramCapabilityClassification,
    TelegramCapabilityGrant,
    TelegramChatInfo,
    TelegramContractError,
    build_telegram_read_handlers,
    capability_requires_send_approval,
    classify_telegram_tool_id,
    core_auth_scopes_for_capability,
    register_telegram_read_tools,
    telegram_capability_snapshot,
    telegram_read_tool_specs,
)
from padiem_ai_core.tool_registry import RegisteredTool, ToolRegistrySnapshot
from padiem_ai_core.tool_runtime import ToolRuntime

BINDING_REF = "binding_telegram_1"
ACTOR_REF = "actor_1"
PAIRED_CHAT_ID = -1001234567890


def run(coro):
    return asyncio.run(coro)


class FakeTelegramPort:
    """In-memory trusted port double. No network, no bot token."""

    def __init__(self, *, json_responses: list[dict] | None = None) -> None:
        self.json_responses: list[dict] = list(json_responses or [])
        self.calls: list[dict] = []

    def get_json(self, **kwargs):
        self.calls.append(kwargs)
        if not self.json_responses:
            raise AssertionError("unexpected provider JSON call")
        return self.json_responses.pop(0)


def telegram_handlers(port: FakeTelegramPort, **kwargs) -> dict:
    return build_telegram_read_handlers(
        port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF, **kwargs
    )


def bot_me(bot_id: int = 777, username: str = "padiem_beta_bot") -> dict:
    return {"ok": True, "result": {"id": bot_id, "username": username, "first_name": "Padiem", "is_bot": True}}


def chat_result(chat_id: int = PAIRED_CHAT_ID, chat_type: str = "supergroup") -> dict:
    return {"ok": True, "result": {"id": chat_id, "type": chat_type, "title": "Padiem Ops"}}


# --- Core contract surface ---


def test_specs_are_read_only_and_bounded() -> None:
    specs = telegram_read_tool_specs()
    assert tuple(spec.id for spec in specs) == TELEGRAM_READ_TOOL_IDS
    for spec in specs:
        assert spec.side_effect is ToolSideEffect.READ
        assert spec.approval_policy is ApprovalPolicy.NOT_REQUIRED
        assert spec.auth_scope == (TELEGRAM_READONLY_AUTH_SCOPE,)
    assert all("send" not in spec.id and "edit" not in spec.id for spec in specs)


def test_canonical_tool_ids_and_descriptor_conform_to_core_registries() -> None:
    entries = tuple(
        RegisteredTool.from_spec(canonical_tool_id=canonical_id, runtime_spec=spec)
        for canonical_id, spec in zip(TELEGRAM_CANONICAL_TOOL_IDS, telegram_read_tool_specs())
    )
    tool_registry = ToolRegistrySnapshot.from_entries(entries)
    validated = validate_connector_tools(TELEGRAM_DESCRIPTOR, tool_registry)
    assert validated.connector_id == TELEGRAM_CONNECTOR_ID
    assert validated.canonical_tool_ids == TELEGRAM_CANONICAL_TOOL_IDS


def test_bounds_mirror_reviewed_b54_contract() -> None:
    assert MAX_TELEGRAM_CHATS == 128
    assert MAX_TELEGRAM_SENDERS_PER_CHAT == 128
    assert MAX_TELEGRAM_MESSAGE_CHARS == 20_000
    assert MAX_TELEGRAM_FILE_BYTES == 10 * 1024 * 1024
    assert MAX_TELEGRAM_FILES_PER_UPDATE == 8
    assert TELEGRAM_PROVIDER_CLOUD_DOWNLOAD_LIMIT_BYTES == 20 * 1024 * 1024
    assert TELEGRAM_PROVIDER_CLOUD_SEND_DOCUMENT_LIMIT_BYTES == 50 * 1024 * 1024
    assert TELEGRAM_CALLBACK_DATA_MAX_BYTES == 64


def test_classify_telegram_tool_id_is_fail_closed() -> None:
    for tool_id in TELEGRAM_READ_TOOL_IDS + TELEGRAM_CANONICAL_TOOL_IDS:
        assert classify_telegram_tool_id(tool_id) is TelegramCapabilityClassification.READ
    for tool_id in (
        "telegram.send_message",
        "sendMessage",
        "sendDocument",
        "editMessageText",
        "answerCallbackQuery",
        "setWebhook",
        "deleteMessage",
        "tool:telegram:bot.send_message@1",
    ):
        assert classify_telegram_tool_id(tool_id) is TelegramCapabilityClassification.WRITE_OR_MATERIAL
    for tool_id in ("telegram.unknown_read", "tool:telegram:bot.mystery@1"):
        assert classify_telegram_tool_id(tool_id) is TelegramCapabilityClassification.UNKNOWN
    with pytest.raises(TelegramContractError):
        classify_telegram_tool_id("")
    with pytest.raises(TelegramContractError):
        classify_telegram_tool_id("bad id with spaces")


def test_capability_scopes_and_approval_semantics() -> None:
    assert core_auth_scopes_for_capability(TelegramCapability.READ) == (TELEGRAM_READONLY_AUTH_SCOPE,)
    assert core_auth_scopes_for_capability(TelegramCapability.SEND_MESSAGE) == (TELEGRAM_SEND_AUTH_SCOPE,)
    assert capability_requires_send_approval(TelegramCapability.READ) is False
    assert capability_requires_send_approval(TelegramCapability.SEND_DOCUMENT) is True
    assert capability_requires_send_approval(TelegramCapability.ANSWER_CALLBACK) is True


def test_grant_never_mints_write_or_token_authority() -> None:
    grant = TelegramCapabilityGrant(
        connector_id=TELEGRAM_CONNECTOR_ID,
        binding_ref=BINDING_REF,
        granted_capabilities=(TelegramCapability.READ,),
    )
    snapshot = grant.safe_dict()
    assert snapshot["write_authority"] is False
    assert snapshot["bot_token_present"] is False
    assert snapshot["mints_approval_authority"] is False
    with pytest.raises(TelegramContractError):
        TelegramCapabilityGrant(
            connector_id=TELEGRAM_CONNECTOR_ID,
            binding_ref=BINDING_REF,
            granted_capabilities=(TelegramCapability.READ, TelegramCapability.READ),
        )
    with pytest.raises(TelegramContractError):
        TelegramCapabilityGrant(
            connector_id=TELEGRAM_CONNECTOR_ID,
            binding_ref=BINDING_REF,
            granted_capabilities=("telegram.send",),  # type: ignore[arg-type]
        )


def test_snapshot_is_deterministic_and_fail_closed() -> None:
    first = telegram_capability_snapshot()
    assert first == telegram_capability_snapshot()
    assert json.dumps(first, sort_keys=True)
    assert first["write_tools_present"] is False
    assert first["registered_write_tools"] == []
    assert first["raw_bot_token_in_core"] is False
    assert first["production_send_authority_minted"] is False
    assert first["callback_data_is_approval_authority"] is False
    assert first["webhook_and_getupdates_simultaneous"] is False
    assert first["live_provider_calls"] == 0
    assert TELEGRAM_RAW_BOT_TOKEN_IN_CORE is False


# --- projections ---


def test_bot_info_projection_requires_official_bot_identity() -> None:
    bot = TelegramBotInfo(bot_id="777", username="padiem_beta_bot", first_name="Padiem")
    assert bot.safe_dict()["is_bot"] is True
    assert bot.safe_dict()["bot_token_present"] is False
    with pytest.raises(TelegramContractError):
        TelegramBotInfo(bot_id="not-numeric", username="padiem_beta_bot", first_name="Padiem")
    with pytest.raises(TelegramContractError):
        TelegramBotInfo(bot_id="777", username="ab", first_name="Padiem")


def test_chat_info_projection_bounds_and_types() -> None:
    chat = TelegramChatInfo(chat_id=PAIRED_CHAT_ID, chat_type="supergroup", title="Padiem Ops")
    assert chat.safe_dict()["message_content_present"] is False
    with pytest.raises(TelegramContractError):
        TelegramChatInfo(chat_id=0, chat_type="private")
    with pytest.raises(TelegramContractError):
        TelegramChatInfo(chat_id=PAIRED_CHAT_ID, chat_type="broadcast")
    with pytest.raises(TelegramContractError):
        TelegramChatInfo(chat_id=PAIRED_CHAT_ID, chat_type="private", username="x y")


# --- handlers ---


def test_get_bot_info_projects_bounded_identity() -> None:
    port = FakeTelegramPort(json_responses=[bot_me()])
    handlers = telegram_handlers(port)
    result = run(handlers[TELEGRAM_GET_BOT_INFO_TOOL_ID]({}))
    assert result["provider"] == "telegram"
    assert result["result_status"] == "OK"
    assert result["bot"]["bot_id"] == "777"
    assert result["bot"]["username"] == "padiem_beta_bot"
    assert result["bot_token_present"] is False
    assert result["write_capability_granted"] is False
    call = port.calls[0]
    assert call["base_url"] == TELEGRAM_BASE_URL
    assert call["path"] == "/getMe"
    assert call["required_scopes"] == (TELEGRAM_READONLY_AUTH_SCOPE,)
    assert call["binding_ref"] == BINDING_REF
    assert call["actor_ref"] == ACTOR_REF


def test_get_bot_info_rejects_non_bot_and_provider_error() -> None:
    port = FakeTelegramPort(
        json_responses=[
            {"ok": True, "result": {"id": 777, "username": "padiem_beta_bot", "first_name": "P", "is_bot": False}},
            {"ok": False, "description": "Bot was deleted"},
        ]
    )
    handlers = telegram_handlers(port)
    with pytest.raises(TelegramContractError):
        run(handlers[TELEGRAM_GET_BOT_INFO_TOOL_ID]({}))
    with pytest.raises(TelegramContractError) as exc_info:
        run(handlers[TELEGRAM_GET_BOT_INFO_TOOL_ID]({}))
    assert "deleted" not in str(exc_info.value)


def test_get_chat_info_enforces_server_paired_allowlist() -> None:
    port = FakeTelegramPort(json_responses=[chat_result()])
    handlers = telegram_handlers(port, paired_chat_ids=(PAIRED_CHAT_ID,))
    result = run(handlers[TELEGRAM_GET_CHAT_INFO_TOOL_ID]({"chatId": PAIRED_CHAT_ID}))
    assert result["chat"]["chat_id"] == PAIRED_CHAT_ID
    assert result["arbitrary_private_chat_read"] is False
    assert port.calls[0]["path"] == "/getChat"
    assert port.calls[0]["query"] == {"chat_id": str(PAIRED_CHAT_ID)}

    handlers_unpaired = telegram_handlers(FakeTelegramPort(), paired_chat_ids=(PAIRED_CHAT_ID,))
    with pytest.raises(TelegramContractError):
        run(handlers_unpaired[TELEGRAM_GET_CHAT_INFO_TOOL_ID]({"chatId": -1009999999999}))


def test_get_chat_info_rejects_provider_identity_mismatch() -> None:
    port = FakeTelegramPort(json_responses=[chat_result(chat_id=123456)])
    handlers = telegram_handlers(port)
    with pytest.raises(TelegramContractError):
        run(handlers[TELEGRAM_GET_CHAT_INFO_TOOL_ID]({"chatId": PAIRED_CHAT_ID}))


def test_get_chat_info_rejects_malformed_arguments() -> None:
    port = FakeTelegramPort()
    handlers = telegram_handlers(port)
    for arguments in ({}, {"chatId": "not-an-int"}, {"chatId": True}, {"chatId": 0}, {"chatId": 1, "extra": 2}):
        with pytest.raises(TelegramContractError):
            run(handlers[TELEGRAM_GET_CHAT_INFO_TOOL_ID](arguments))
    assert port.calls == []


def test_port_exception_is_sanitized_never_leaks_token() -> None:
    class ExplodingPort:
        def get_json(self, **kwargs):
            raise RuntimeError(
                "GET https://api.telegram.org/bot123:SECRET-TOKEN/getMe failed: timeout"
            )

    handlers = telegram_handlers(ExplodingPort())
    with pytest.raises(TelegramContractError) as exc_info:
        run(handlers[TELEGRAM_GET_BOT_INFO_TOOL_ID]({}))
    message = str(exc_info.value)
    assert "SECRET-TOKEN" not in message
    assert "api.telegram.org" not in message
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_registration_is_read_only_on_shared_runtime() -> None:
    runtime = ToolRuntime()
    port = FakeTelegramPort()
    registered = register_telegram_read_tools(
        runtime, port, binding_ref=BINDING_REF, actor_ref=ACTOR_REF
    )
    assert registered == TELEGRAM_READ_TOOL_IDS
    assert runtime.registered_tool_ids == TELEGRAM_READ_TOOL_IDS
    assert all(not spec.id.startswith("telegram.send") for spec in telegram_read_tool_specs())


def test_host_constant_is_official_api_only() -> None:
    assert TELEGRAM_API_HOST == "api.telegram.org"
    assert TELEGRAM_BASE_URL == "https://api.telegram.org"
    assert TELEGRAM_CONNECTOR_ID == "connector:telegram:bot@1"
