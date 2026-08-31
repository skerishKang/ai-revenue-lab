from __future__ import annotations

import pytest

from app.chat_modes import (
    CHAT_MODE_CATALOG,
    DEFAULT_CHAT_MODE,
    ChatMode,
    ChatModeError,
    chat_modes_api_payload,
    get_chat_mode_descriptor,
    list_chat_modes,
    resolve_chat_mode,
)


def test_default_mode_is_auto_and_provider_neutral():
    assert DEFAULT_CHAT_MODE is ChatMode.AUTO
    assert resolve_chat_mode(None) is ChatMode.AUTO
    assert resolve_chat_mode("   ") is ChatMode.AUTO


def test_supported_modes_are_stable_product_ids():
    assert [item.mode.value for item in CHAT_MODE_CATALOG] == [
        "auto",
        "fast",
        "balanced",
        "deep",
    ]
    assert resolve_chat_mode(" FAST ") is ChatMode.FAST
    assert get_chat_mode_descriptor("deep").mode is ChatMode.DEEP


def test_browser_catalog_contains_no_provider_or_model_authority():
    catalog = list_chat_modes()
    assert [item["id"] for item in catalog] == ["auto", "fast", "balanced", "deep"]
    assert all(set(item) == {"id", "label", "description"} for item in catalog)
    serialized = repr(catalog).lower()
    for forbidden in (
        "provider",
        "model_id",
        "upstream_model",
        "route_id",
        "credential",
        "poolside",
        "laguna",
        "agnes",
    ):
        assert forbidden not in serialized


def test_api_payload_does_not_claim_unimplemented_mode_execution():
    payload = chat_modes_api_payload()
    assert payload["default_mode"] == "auto"
    assert payload["accepted_request_mode_ids"] == ["auto"]
    assert [item["id"] for item in payload["modes"]] == [
        "auto",
        "fast",
        "balanced",
        "deep",
    ]
    serialized = repr(payload).lower()
    for forbidden in (
        "provider",
        "model_id",
        "upstream_model",
        "route_id",
        "credential",
        "poolside",
        "laguna",
        "agnes",
    ):
        assert forbidden not in serialized


def test_unknown_mode_fails_closed_without_provider_hint():
    with pytest.raises(ChatModeError) as info:
        resolve_chat_mode("poolside")
    assert info.value.code == "unknown_chat_mode"
    assert "poolside" not in info.value.safe_message.lower()
    assert "model" not in info.value.safe_message.lower()
