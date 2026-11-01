"""External notification channels, pinned by mock tests (#6460-3 sweep).

No real network: every adapter receives an ``httpx.MockTransport`` through the
injection seam the production code already defines. These tests pin, per
channel: the one request a healthy send makes (URL, payload shape), the
fail-safe behavior when the provider refuses or the credential is absent, and
the fact that no provider error text ever reaches a user-facing answer.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.b66_signup_notifications import B66SignupNotifier, deliver_after_signup
from app.password_reset_delivery import build_email_delivery

_TELEGRAM_TOKEN = "123456:" + "A" * 45
_TELEGRAM_CHAT = "-123456"
_DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1234567890123456789/" + "Z" * 45
_RESEND_KEY = "re_" + "q" * 20
_SENDER = "notify@example.com"
_RECIPIENT = "admin@example.test"


class _Outbox:
    """The durable outbox seam the notifier records deliveries against."""

    def __init__(self):
        self.pending: set[str] = set()
        self.delivered: set[tuple[str, str]] = set()

    async def pending_signup_for_user(self, user_id: str) -> bool:
        return user_id in self.pending

    async def delivered_signup_channel(self, user_id: str, channel: str) -> bool:
        return (user_id, channel) in self.delivered

    async def record_signup_alert_channel(self, user_id: str, channel: str) -> None:
        self.delivered.add((user_id, channel))

    async def finalize_signup_alert(self, user_id: str, channels: tuple[str, ...]) -> None:
        self.pending.discard(user_id)


def _notifier(outbox: _Outbox, handler, **channels) -> B66SignupNotifier:
    return B66SignupNotifier(
        outbox, http_transport=httpx.MockTransport(handler), **channels
    )


def test_email_channel_sends_one_resend_request_with_the_bearer_credential():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["accept"] = request.headers.get("Accept")
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json={"id": "probe"})

    outbox = _Outbox()
    outbox.pending.add("usr_new")
    notifier = _notifier(
        outbox, handler,
        resend_api_key=_RESEND_KEY, email_from=_SENDER, email_to=_RECIPIENT,
    )
    assert set(notifier.channels) == {"email"}
    assert asyncio.run(notifier.notify_one("usr_new")) == {"sent": 1, "failed": 0}

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["auth"] == "Bearer " + _RESEND_KEY
    assert captured["accept"] == "application/json"
    payload = captured["body"]
    assert payload["from"] == _SENDER
    assert payload["to"] == [_RECIPIENT]
    assert payload["subject"] == "[B66] 신규 회원가입 알림"
    assert "회원가입" in payload["text"]
    assert _RESEND_KEY not in json.dumps(payload)


def test_resend_provider_refusal_is_a_failed_delivery_never_an_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid api key"})

    outbox = _Outbox()
    outbox.pending.add("usr_new")
    notifier = _notifier(
        outbox, handler,
        resend_api_key=_RESEND_KEY, email_from=_SENDER, email_to=_RECIPIENT,
    )
    assert asyncio.run(notifier.notify_one("usr_new")) == {"sent": 0, "failed": 1}
    assert notifier.channels  # the channel stays configured for the retry


def test_telegram_channel_posts_to_the_bot_api_with_the_chat_payload():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json={"ok": True})

    outbox = _Outbox()
    outbox.pending.add("usr_new")
    notifier = _notifier(
        outbox, handler,
        telegram_bot_token=_TELEGRAM_TOKEN, telegram_chat_id=_TELEGRAM_CHAT,
    )
    assert asyncio.run(notifier.notify_one("usr_new")) == {"sent": 1, "failed": 0}

    assert captured["url"] == (
        "https://api.telegram.org/bot" + _TELEGRAM_TOKEN + "/sendMessage"
    )
    payload = captured["body"]
    assert payload["chat_id"] == _TELEGRAM_CHAT
    assert "회원가입" in payload["text"]
    assert payload["disable_web_page_preview"] is True
    assert _TELEGRAM_TOKEN not in payload["text"]


def test_discord_channel_posts_to_the_configured_webhook_without_mentions():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.read().decode("utf-8"))
        return httpx.Response(204)

    outbox = _Outbox()
    outbox.pending.add("usr_new")
    notifier = _notifier(outbox, handler, discord_webhook_url=_DISCORD_WEBHOOK)
    assert asyncio.run(notifier.notify_one("usr_new")) == {"sent": 1, "failed": 0}

    assert captured["url"] == _DISCORD_WEBHOOK
    payload = captured["body"]
    assert "회원가입" in payload["content"]
    assert payload["allowed_mentions"] == {"parse": []}


def test_malformed_credentials_register_no_channel_and_call_nothing():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    outbox = _Outbox()
    outbox.pending.add("usr_new")
    notifier = _notifier(
        outbox, handler,
        telegram_bot_token="not-a-bot-token", telegram_chat_id="-1",
        discord_webhook_url="https://evil.example/webhook",
        resend_api_key="sk-not-a-resend-key", email_from="not-an-email",
        email_to="also-not-an-email",
    )
    assert notifier.channels == {}
    assert asyncio.run(notifier.notify_one("usr_new")) == {"sent": 0, "failed": 0}
    assert calls == []


def test_a_notifier_without_the_email_channel_never_touches_resend():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    outbox = _Outbox()
    outbox.pending.add("usr_new")
    notifier = _notifier(
        outbox, handler,
        telegram_bot_token=_TELEGRAM_TOKEN, telegram_chat_id=_TELEGRAM_CHAT,
    )
    assert asyncio.run(notifier.notify_one("usr_new")) == {"sent": 1, "failed": 0}
    assert [url for url in calls if "api.resend.com" in url] == []


def test_notification_failure_never_breaks_the_login_that_triggered_it():
    class _Broken:
        async def notify_one(self, user_id: str) -> dict[str, int]:
            raise RuntimeError("synthetic notifier collapse")

    request = type("Request", (), {"app": type("App", (), {"state": type("State", (), {"b66_signup_notifier": _Broken()})()})()})()
    assert asyncio.run(deliver_after_signup(request, "usr_anywhere")) is None


def test_an_absent_mail_key_builds_no_transport_and_no_fake_success():
    assert build_email_delivery(resend_api_key="", email_from="") is None
    assert build_email_delivery(resend_api_key=_RESEND_KEY, email_from="") is None
    assert build_email_delivery(resend_api_key="", email_from=_SENDER) is None
    # A malformed key is the same honest "this deployment cannot send mail".
    assert build_email_delivery(resend_api_key="sk_not_resend", email_from=_SENDER) is None


def test_the_signup_notifier_never_copies_secrets_into_its_payloads():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.host] = request.read().decode("utf-8")
        return httpx.Response(200)

    outbox = _Outbox()
    outbox.pending.add("usr_new")
    notifier = _notifier(
        outbox, handler,
        telegram_bot_token=_TELEGRAM_TOKEN, telegram_chat_id=_TELEGRAM_CHAT,
        discord_webhook_url=_DISCORD_WEBHOOK,
        resend_api_key=_RESEND_KEY, email_from=_SENDER, email_to=_RECIPIENT,
    )
    asyncio.run(notifier.notify_one("usr_new"))
    blob = json.dumps(seen)
    for secret in (_TELEGRAM_TOKEN, _RESEND_KEY, _DISCORD_WEBHOOK.rsplit("/", 1)[1]):
        assert secret not in blob
