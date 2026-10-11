"""Optional durable new-signup alerts (server-side env, never browser credentials).

Migration 037 queues a signup event. This adapter sends to configured channels
only and records per-channel delivery. Missing credentials keep events queued.
No customer email or document content enters webhook payloads.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

_TELEGRAM_BOT = re.compile(r"^[0-9]{3,20}:[A-Za-z0-9_-]{25,120}$")
_TELEGRAM_CHAT = re.compile(r"^-?[0-9]{3,22}$")
_DISCORD = re.compile(r"^https://(?:discord\.com|discordapp\.com)/api/webhooks/[0-9]{10,25}/[A-Za-z0-9_-]{20,200}$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class B66SignupNotifier:
    def __init__(
        self, store: Any, *,
        telegram_bot_token: str = "", telegram_chat_id: str = "",
        discord_webhook_url: str = "", resend_api_key: str = "",
        email_from: str = "", email_to: str = "",
        http_transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.store = store
        self.http_transport = http_transport
        self.channels: dict[str, tuple[str, dict, dict]] = {}
        message = "B66 견적서: 새로운 회원가입이 접수되었습니다. 관리자 페이지에서 승인 상태를 확인해 주세요."
        if _TELEGRAM_BOT.fullmatch(telegram_bot_token or "") and _TELEGRAM_CHAT.fullmatch(telegram_chat_id or ""):
            self.channels["telegram"] = (
                "https://api.telegram.org/bot" + telegram_bot_token + "/sendMessage",
                {"chat_id":telegram_chat_id,"text":message,"disable_web_page_preview":True},
                {},
            )
        if _DISCORD.fullmatch(discord_webhook_url or ""):
            self.channels["discord"] = (
                discord_webhook_url,
                {"content":message,"allowed_mentions":{"parse":[]}},
                {},
            )
        if (isinstance(resend_api_key,str) and resend_api_key.startswith("re_")
            and _EMAIL.fullmatch(email_from or "") and _EMAIL.fullmatch(email_to or "")):
            self.channels["email"] = (
                "https://api.resend.com/emails",
                {"from":email_from,"to":[email_to],
                 "subject":"[B66] 신규 회원가입 알림","text":message},
                {"Authorization":"Bearer " + resend_api_key},
            )

    async def _send(self, channel: str, *, message: str | None = None,
                    subject: str | None = None) -> bool:
        url, data, headers = self.channels[channel]
        data = dict(data)
        if message is not None:
            if channel == "telegram":
                data["text"] = message
            elif channel == "discord":
                data["content"] = message
            elif channel == "email":
                data["text"] = message
                if subject is not None:
                    data["subject"] = subject
        try:
            async with httpx.AsyncClient(
                transport=self.http_transport,
                timeout=httpx.Timeout(4.0, connect=2.0),
                follow_redirects=False,
            ) as client:
                result = await client.post(
                    url, json=data, headers={"Accept":"application/json", **headers}
                )
                if result.status_code < 200 or result.status_code >= 300:
                    return False
                if channel == "telegram":
                    payload = result.json()
                    return isinstance(payload,dict) and payload.get("ok") is True
                return True
        except (httpx.HTTPError, ValueError, TypeError):
            return False

    async def notify_one(self, user_id: str) -> dict[str,int]:
        if not self.channels or not await self.store.pending_signup_for_user(user_id):
            return {"sent":0,"failed":0}
        sent, failed = 0, 0
        for channel in self.channels:
            if await self.store.delivered_signup_channel(user_id,channel):
                continue
            if await self._send(channel):
                await self.store.record_signup_alert_channel(user_id,channel)
                sent += 1
            else:
                failed += 1
        await self.store.finalize_signup_alert(user_id, tuple(self.channels))
        return {"sent":sent,"failed":failed}

    async def retry_pending(self, limit: int = 5) -> dict[str,int]:
        sent, failed = 0,0
        for uid in await self.store.signup_alert_candidates(limit):
            result = await self.notify_one(uid)
            sent += result["sent"]
            failed += result["failed"]
        return {"sent":sent,"failed":failed}


async def deliver_after_signup(request: Any, user_id: str) -> None:
    """Notification failures cannot invalidate an already verified login."""
    notifier = getattr(request.app.state, "b66_signup_notifier", None)
    if notifier is None:
        return
    try:
        await notifier.notify_one(user_id)
    except Exception:
        # The outbox remains; never reveal webhook secrets in logs or responses.
        return
