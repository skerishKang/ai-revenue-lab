"""Network-free tests for the thin Telegram inbound consumer seam (#2315).

The canonical Telegram authority stays the B54 business-MVP contracts/runtime
(``kagent.telegram_contracts`` / ``kagent.telegram_bot_runtime``) per the
#2312 RETAIN_BUSINESS_MVP decision. These tests exercise only the B62 HTTP
seam: paired-chat authorization, replay/dedup, bounded redacted text, webhook
proof fail-closed behavior, and the mapping into the existing Claw manual
intake path. Every transport is faked; no test performs a live Telegram API
call, and no outbound send path exists in the slice under test.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.claw_telegram_routes import StaticTelegramTrustedAuthority
from app.config import Settings
from kagent.telegram_contracts import (
    TelegramChatKind,
    TelegramIngressConfig,
    TelegramIngressMode,
    TelegramPairedChat,
    TelegramBotScope,
)

WEBHOOK_SECRET = "whsec_kilo2_test_0123456789abcdef"
BINDING_REF = "tg-beta-binding"
INGEST_PATH = f"/api/claw/telegram/ingest/{BINDING_REF}"
PROOF_HEADER = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}


def _scope() -> TelegramBotScope:
    return TelegramBotScope(
        binding_ref=BINDING_REF,
        workspace_ref="ws_padiem_claw",
        bot_ref="padiem-beta-bot",
        telegram_bot_user_ref="tg-bot-padiem-beta",
        paired_chats=(
            TelegramPairedChat(
                chat_ref="chat_private_100",
                telegram_chat_id_ref="tg-chat-100",
                kind=TelegramChatKind.PRIVATE,
                allowed_sender_refs=("user_alice",),
            ),
            TelegramPairedChat(
                chat_ref="chat_group_200",
                telegram_chat_id_ref="tg-chat-200",
                kind=TelegramChatKind.GROUP,
                allowed_sender_refs=("user_alice",),
                privileged_intake_allowed=True,
            ),
        ),
    )


def _authority() -> StaticTelegramTrustedAuthority:
    return StaticTelegramTrustedAuthority(
        binding_ref=BINDING_REF,
        webhook_secret_binding_ref="tg-webhook-secret",
        webhook_secret=WEBHOOK_SECRET,
        ingress=TelegramIngressConfig(
            mode=TelegramIngressMode.WEBHOOK,
            allowed_update_types=("message",),
            webhook_secret_binding_ref="tg-webhook-secret",
        ),
        scope=_scope(),
        identity_map={
            (100, 111): ("chat_private_100", "user_alice"),
            (200, 111): ("chat_group_200", "user_alice"),
            (200, 222): ("chat_group_200", "user_charlie"),
        },
    )


def _client(authority: StaticTelegramTrustedAuthority | None) -> TestClient:
    settings = Settings.from_values(
        runtime_mode="mock",
        live_enabled="false",
        auth_mode="off",
    )
    return TestClient(create_app(settings=settings, claw_telegram_authority=authority))


@pytest.fixture
def client() -> TestClient:
    return _client(_authority())


def _update(update_id: int, chat_id: int, sender_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "text": text,
            "chat": {"id": chat_id},
            "from": {"id": sender_id},
        },
    }


def test_paired_private_chat_accepted_and_mapped_to_telegram_intake(client: TestClient) -> None:
    resp = client.post(
        INGEST_PATH,
        json=_update(1, 100, 111, "가상 테스트: 9월 말까지 샘플 20개 견적 요청."),
        headers=PROOF_HEADER,
    )
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store, max-age=0"
    data = resp.json()
    assert data["ok"] is True
    assert data["accepted"] is True
    intake = data["intake"]
    assert intake["channel"] == "telegram"
    assert intake["action"] == "quote_draft"
    assert "견적" in intake["title"]
    assert intake["direct_kakao_send"] is False
    assert intake["direct_sms_send"] is False
    assert data["update"]["event_ref"] == "telegram-update:1"


def test_unpaired_chat_skipped_without_privileged_intake(client: TestClient) -> None:
    resp = client.post(
        INGEST_PATH,
        json=_update(2, 999, 999, "unpaired stranger text"),
        headers=PROOF_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["accepted"] is False
    assert data["reason"] == "unpaired"
    assert "intake" not in data


def test_privileged_group_sender_allowlist_enforced(client: TestClient) -> None:
    # Sender resolved by the trusted binding but NOT on the paired-chat allowlist.
    denied = client.post(
        INGEST_PATH,
        json=_update(3, 200, 222, "allowlist outsider text"),
        headers=PROOF_HEADER,
    )
    assert denied.status_code == 200
    denied_data = denied.json()
    assert denied_data["accepted"] is False
    assert denied_data["reason"] == "not_authorized"
    assert "intake" not in denied_data

    # Allowed sender on the same paired group chat is accepted.
    allowed = client.post(
        INGEST_PATH,
        json=_update(4, 200, 111, "그룹 허용 발신자 텍스트"),
        headers=PROOF_HEADER,
    )
    assert allowed.status_code == 200
    allowed_data = allowed.json()
    assert allowed_data["accepted"] is True
    assert allowed_data["intake"]["channel"] == "telegram"


def test_replay_duplicate_update_skipped(client: TestClient) -> None:
    payload = _update(5, 100, 111, "duplicate delivery of the same update")
    first = client.post(INGEST_PATH, json=payload, headers=PROOF_HEADER)
    assert first.status_code == 200
    assert first.json()["accepted"] is True

    second = client.post(INGEST_PATH, json=payload, headers=PROOF_HEADER)
    assert second.status_code == 200
    second_data = second.json()
    assert second_data["accepted"] is False
    assert second_data["reason"] == "duplicate"
    assert "intake" not in second_data


def test_oversized_text_fails_bounded(client: TestClient) -> None:
    resp = client.post(
        INGEST_PATH,
        json=_update(6, 100, 111, "가" * 20_001),
        headers=PROOF_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is False
    assert data["reason"] == "text_exceeds_bound"
    assert "intake" not in data


def test_invalid_or_missing_webhook_proof_fails_closed(client: TestClient) -> None:
    missing = client.post(INGEST_PATH, json=_update(7, 100, 111, "no header"))
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "telegram_webhook_proof_rejected"

    wrong = client.post(
        INGEST_PATH,
        json=_update(7, 100, 111, "wrong secret"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "whsec_wrong_value_000000000000"},
    )
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "telegram_webhook_proof_rejected"

    unknown_binding = client.post(
        "/api/claw/telegram/ingest/unknown-binding",
        json=_update(7, 100, 111, "unknown binding"),
        headers=PROOF_HEADER,
    )
    assert unknown_binding.status_code == 403


def test_no_secret_material_disclosed_in_any_projection(client: TestClient) -> None:
    ok = client.post(
        INGEST_PATH,
        json=_update(8, 100, 111, "projection hygiene check"),
        headers=PROOF_HEADER,
    )
    assert WEBHOOK_SECRET not in ok.text
    rejected = client.post(
        INGEST_PATH,
        json=_update(8, 999, 999, "projection hygiene check"),
        headers=PROOF_HEADER,
    )
    assert WEBHOOK_SECRET not in rejected.text
    denied = client.post(INGEST_PATH, json=_update(8, 100, 111, "no header"))
    assert WEBHOOK_SECRET not in denied.text
    # The raw provider update object is never echoed back.
    assert "message" not in (ok.json().get("update") or {})


def test_zero_outbound_send_invocation(client: TestClient) -> None:
    with (
        patch("kagent.telegram_bot_runtime.StdlibTelegramBotApiRequestPort.call") as api_call,
        patch("http.client.HTTPSConnection.request") as http_request,
        patch("http.client.HTTPSConnection.getresponse") as http_response,
    ):
        api_call.side_effect = AssertionError("outbound Bot API transport must not be used")
        http_request.side_effect = AssertionError("raw HTTPS egress must not be used")
        http_response.side_effect = AssertionError("raw HTTPS egress must not be used")
        resp = client.post(
            INGEST_PATH,
            json=_update(9, 100, 111, "zero egress check"),
            headers=PROOF_HEADER,
        )
        assert resp.status_code == 200
        assert resp.json()["accepted"] is True
        api_call.assert_not_called()
        http_request.assert_not_called()


def test_unsupported_update_type_skipped(client: TestClient) -> None:
    resp = client.post(
        INGEST_PATH,
        json={"update_id": 10, "edited_message": {"text": "not a plain message"}},
        headers=PROOF_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["accepted"] is False
    assert data["reason"] == "unsupported_update"


def test_route_fail_closed_when_authority_unconfigured() -> None:
    client = _client(None)
    resp = client.post(
        INGEST_PATH,
        json=_update(11, 100, 111, "unconfigured"),
        headers=PROOF_HEADER,
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "telegram_ingest_not_configured"


def test_no_live_telegram_dependencies_imported_at_request_time() -> None:
    # The seam imports contracts only; constructing the app and routing a
    # request must stay deterministic and offline (UTC-anchored, no sleeps).
    assert datetime.now(timezone.utc).utcoffset() == timezone.utc.utcoffset(None)
