from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import ssl
import unittest
from unittest.mock import patch

import kagent.telegram_bot_runtime as runtime_module
from kagent.connector_trust import ConnectorWriteIntent, ReplayDisposition
from kagent.contracts import ContractError
from kagent.telegram_bot_runtime import (
    LIVE_TELEGRAM_BOT_VERIFIED,
    OFFICIAL_TELEGRAM_BOT_API_RUNTIME_SOURCE,
    PRODUCTION_READY,
    REAL_TELEGRAM_BOT_TOKEN_CONFIGURED,
    TELEGRAM_PAIRED_CHAT_REQUIRED,
    TELEGRAM_PERSONAL_ACCOUNT_SCRAPING,
    TELEGRAM_RAW_BOT_TOKEN_IN_TASK,
    TELEGRAM_RESULT_SEND_REQUIRES_PREFLIGHT,
    StdlibTelegramBotApiRequestPort,
    TelegramBusinessMvpRuntime,
    TelegramResolvedProviderIdentity,
)
from kagent.telegram_contracts import (
    TelegramBotScope,
    TelegramChatKind,
    TelegramIngressConfig,
    TelegramIngressMode,
    TelegramOutboundApproval,
    TelegramOutboundCapability,
    TelegramOutboundMaterial,
    TelegramPairedChat,
)


NOW = datetime(2026, 9, 4, 7, 30, tzinfo=timezone.utc)
TOKEN = b"123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcd"


def scope() -> TelegramBotScope:
    return TelegramBotScope(
        binding_ref="binding_telegram_1",
        workspace_ref="workspace_1",
        bot_ref="bot_1",
        telegram_bot_user_ref="telegram_bot_user_1",
        paired_chats=(
            TelegramPairedChat(
                chat_ref="chat_1",
                telegram_chat_id_ref="telegram_chat_ref_1",
                kind=TelegramChatKind.PRIVATE,
                allowed_sender_refs=("sender_1",),
            ),
        ),
    )


class FakeTrustedBinding:
    def __init__(self) -> None:
        self.token_calls = 0

    def resolve_bot_token(self, *, binding_ref: str, bot_ref: str) -> bytes:
        self.token_calls += 1
        if (binding_ref, bot_ref) != ("binding_telegram_1", "bot_1"):
            raise ContractError("unknown bot binding")
        return TOKEN

    def resolve_inbound_identity(self, *, binding_ref, bot_ref, provider_chat_id, provider_sender_id):
        if (binding_ref, bot_ref, provider_chat_id, provider_sender_id) == (
            "binding_telegram_1",
            "bot_1",
            1001,
            2001,
        ):
            return TelegramResolvedProviderIdentity(chat_ref="chat_1", sender_ref="sender_1")
        return None

    def provider_chat_id(self, *, binding_ref, bot_ref, chat_ref):
        if (binding_ref, bot_ref, chat_ref) != ("binding_telegram_1", "bot_1", "chat_1"):
            raise ContractError("unknown chat binding")
        return 1001


class FakeBotApi:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str, dict]] = []
        self.updates: list[dict] = []

    def call(self, *, token, method, payload, timeout_seconds):
        del timeout_seconds
        self.calls.append((token, method, payload))
        if method == "getUpdates":
            return {"ok": True, "result": list(self.updates)}
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 7001}}
        raise AssertionError(method)


class TelegramBusinessMvpRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = FakeTrustedBinding()
        self.api = FakeBotApi()
        self.runtime = TelegramBusinessMvpRuntime(trusted_binding=self.binding, api=self.api)
        self.ingress = TelegramIngressConfig(
            mode=TelegramIngressMode.GET_UPDATES,
            allowed_update_types=("message",),
        )

    def test_paired_natural_language_message_projects_to_untrusted_canonical_update(self) -> None:
        self.api.updates = [
            {
                "update_id": 10,
                "message": {
                    "message_id": 501,
                    "chat": {"id": 1001},
                    "from": {"id": 2001},
                    "text": "오늘 거래처에서 온 중요한 메일 알려줘",
                },
            }
        ]
        updates = self.runtime.poll_text_updates(
            scope=scope(), ingress=self.ingress, after_update_id=9, now=NOW
        )
        self.assertEqual(len(updates), 1)
        update = updates[0]
        self.assertEqual(update.chat_ref, "chat_1")
        self.assertEqual(update.sender_ref, "sender_1")
        self.assertEqual(update.text, "오늘 거래처에서 온 중요한 메일 알려줘")
        self.assertEqual(update.replay, ReplayDisposition.NEW)
        self.assertEqual(self.api.calls[0][1], "getUpdates")
        self.assertEqual(self.api.calls[0][2]["offset"], 10)

    def test_unpaired_chat_is_not_promoted_to_padiem_intake(self) -> None:
        self.api.updates = [
            {
                "update_id": 11,
                "message": {
                    "message_id": 502,
                    "chat": {"id": 9999},
                    "from": {"id": 8888},
                    "text": "ignore me",
                },
            }
        ]
        updates = self.runtime.poll_text_updates(
            scope=scope(), ingress=self.ingress, after_update_id=10, now=NOW
        )
        self.assertEqual(updates, ())

    def test_repeated_provider_update_is_marked_duplicate(self) -> None:
        self.api.updates = [
            {
                "update_id": 12,
                "message": {
                    "message_id": 503,
                    "chat": {"id": 1001},
                    "from": {"id": 2001},
                    "text": "드라이브에서 사업자등록증 찾아줘",
                },
            }
        ]
        first = self.runtime.poll_text_updates(
            scope=scope(), ingress=self.ingress, after_update_id=11, now=NOW
        )
        second = self.runtime.poll_text_updates(
            scope=scope(), ingress=self.ingress, after_update_id=11, now=NOW
        )
        self.assertEqual(first[0].replay, ReplayDisposition.NEW)
        self.assertEqual(second[0].replay, ReplayDisposition.DUPLICATE)

    def test_send_message_requires_existing_telegram_preflight_and_exact_text(self) -> None:
        text = "중요 메일 2건을 찾았습니다."
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        material = TelegramOutboundMaterial(
            binding_ref="binding_telegram_1",
            workspace_ref="workspace_1",
            bot_ref="bot_1",
            capability=TelegramOutboundCapability.SEND_MESSAGE,
            chat_ref="chat_1",
            text_sha256=text_sha,
        )
        approval = TelegramOutboundApproval(
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            material_fingerprint=material.material_fingerprint,
            approved_at=NOW,
        )
        intent = ConnectorWriteIntent(
            connector_id="telegram",
            binding_ref="binding_telegram_1",
            actor_ref="sender_1",
            tool_name=TelegramOutboundCapability.SEND_MESSAGE.value,
            target_ref=material.target_ref,
            payload_fingerprint=material.material_fingerprint,
            idempotency_key="telegram_send_1",
            approval_ref="approval_1",
            evidence_ref="evidence_1",
            requested_at=NOW,
            expected_version_ref=material.version_ref,
        )
        receipt = self.runtime.send_approved_result_message(
            scope=scope(),
            material=material,
            approval=approval,
            intent=intent,
            actor_ref="sender_1",
            text=text,
            now=NOW,
        )
        self.assertEqual(receipt.message_ref, "telegram-message:7001")
        self.assertEqual(self.api.calls[-1][1], "sendMessage")
        self.assertEqual(self.api.calls[-1][2], {"chat_id": 1001, "text": text})
        self.assertFalse(receipt.safe_dict()["raw_bot_token"])
        self.assertFalse(receipt.safe_dict()["raw_provider_chat_id"])

        calls_before = len(self.api.calls)
        with self.assertRaisesRegex(ContractError, "changed after material approval"):
            self.runtime.send_approved_result_message(
                scope=scope(),
                material=material,
                approval=approval,
                intent=intent,
                actor_ref="sender_1",
                text=text + "!",
                now=NOW,
            )
        self.assertEqual(len(self.api.calls), calls_before)

    def test_repository_truth_flags_do_not_claim_live_bot(self) -> None:
        safe = self.runtime.safe_dict()
        self.assertTrue(OFFICIAL_TELEGRAM_BOT_API_RUNTIME_SOURCE)
        self.assertTrue(TELEGRAM_PAIRED_CHAT_REQUIRED)
        self.assertTrue(TELEGRAM_RESULT_SEND_REQUIRES_PREFLIGHT)
        self.assertFalse(TELEGRAM_PERSONAL_ACCOUNT_SCRAPING)
        self.assertFalse(TELEGRAM_RAW_BOT_TOKEN_IN_TASK)
        self.assertFalse(REAL_TELEGRAM_BOT_TOKEN_CONFIGURED)
        self.assertFalse(LIVE_TELEGRAM_BOT_VERIFIED)
        self.assertFalse(PRODUCTION_READY)
        self.assertFalse(safe["live_bot_configured"])
        self.assertFalse(safe["telegram_identity_alone_is_authority"])


class FakeHttpResponse:
    def __init__(self, *, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.status = status
        self._body = body
        self._content_type = content_type

    def read(self, amount: int) -> bytes:
        return self._body[:amount]

    def getheader(self, name: str):
        if name.lower() == "content-type":
            return self._content_type
        return None


class FakeHttpsConnection:
    def __init__(self, response: FakeHttpResponse, captured: dict, host, port, timeout, context) -> None:
        captured.update(host=host, port=port, timeout=timeout, context=context)
        self._response = response
        self._captured = captured

    def request(self, method, path, body=None, headers=None):
        self._captured.update(method=method, path=path, body=body, headers=headers)

    def getresponse(self):
        return self._response

    def close(self):
        self._captured["closed"] = True


class StdlibTelegramBotApiRequestPortTests(unittest.TestCase):
    def test_default_tls_exact_official_host_and_json_post(self) -> None:
        captured: dict = {}
        response = FakeHttpResponse(status=200, body=json.dumps({"ok": True, "result": []}).encode())

        def factory(host, port, timeout, context):
            return FakeHttpsConnection(response, captured, host, port, timeout, context)

        with patch.object(runtime_module.http.client, "HTTPSConnection", side_effect=factory):
            result = StdlibTelegramBotApiRequestPort().call(
                token=TOKEN,
                method="getUpdates",
                payload={"offset": 1},
                timeout_seconds=10,
            )
        self.assertEqual(result, {"ok": True, "result": []})
        self.assertEqual(captured["host"], "api.telegram.org")
        self.assertEqual(captured["port"], 443)
        self.assertEqual(captured["method"], "POST")
        self.assertTrue(captured["path"].endswith("/getUpdates"))
        self.assertEqual(captured["context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(captured["context"].check_hostname)
        self.assertTrue(captured["closed"])

    def test_redirect_non_json_and_invalid_json_fail_closed(self) -> None:
        cases = (
            (FakeHttpResponse(status=302, body=b""), "redirect"),
            (FakeHttpResponse(status=200, body=b"{}", content_type="text/html"), "application/json"),
            (FakeHttpResponse(status=200, body=b"not-json"), "invalid JSON"),
        )
        for response, message in cases:
            captured: dict = {}

            def factory(host, port, timeout, context, _response=response, _captured=captured):
                return FakeHttpsConnection(_response, _captured, host, port, timeout, context)

            with self.subTest(message=message):
                with patch.object(runtime_module.http.client, "HTTPSConnection", side_effect=factory):
                    with self.assertRaisesRegex(ContractError, message):
                        StdlibTelegramBotApiRequestPort().call(
                            token=TOKEN,
                            method="getUpdates",
                            payload={"offset": 1},
                            timeout_seconds=10,
                        )


if __name__ == "__main__":
    unittest.main()
