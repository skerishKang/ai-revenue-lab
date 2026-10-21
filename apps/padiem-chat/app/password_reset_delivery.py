"""Outbound delivery for the #5441 lost-password reset mail.

The reset mail is the only proof of email ownership this flow accepts, so the
delivery channel is a security surface, not a convenience:

* The transport is server-side only. The browser never holds a provider key.
* The delivery failure is never reported as a success. A request that could
  not be handed to a transport is refused with a retryable error instead of a
  fake "we sent it" answer.
* The reset token travels inside the mail body. It is never written to a log
  line, an audit row or an error message.

The provider is an HTTP transactional-mail API (the same shape the B66 signup
notifier already uses), because the Worker runtime reaches that API over
HTTPS. Two bindings are honoured:

* ``PADIEM_CHAT_PASSWORD_RESET_RESEND_API_KEY`` / ``PADIEM_CHAT_PASSWORD_RESET_EMAIL_FROM``
  — the dedicated reset pair;
* ``B66_ALERT_RESEND_API_KEY`` / ``B66_ALERT_EMAIL_FROM`` — the already
  provisioned owner-side fallback, so an account that already carries the
  shared notification credential can send reset mail with no second key.

If neither pair is configured the reset request route refuses the request
honestly. It never pretends a mail was sent.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

import httpx

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_RESEND_API_KEY = re.compile(r"^re_[A-Za-z0-9_-]{8,}$")

RESET_MAIL_SUBJECT = "[PADIEM] 비밀번호 재설정 안내"
RESET_MAIL_BODY = (
    "안녕하세요.\n\n"
    "PADIEM 계정의 비밀번호를 재설정해 달라는 요청이 접수되었습니다.\n"
    "아래 링크를 눌러 새 비밀번호를 직접 설정해 주세요.\n\n"
    "{link}\n\n"
    "- 이 링크는 1회만 사용할 수 있고, 잠시 뒤에 만료됩니다.\n"
    "- 요청하지 않으셨다면 이 메일을 무시해 주세요. "
    "계정 정보는 변경되지 않습니다.\n"
)


class EmailDelivery(Protocol):
    """One outbound transactional-mail transport."""

    async def send(self, *, to: str, subject: str, text: str) -> bool: ...


class ResendEmailDelivery:
    """Transactional mail over the provider's HTTPS API.

    The provider key never leaves the Worker. A non-2xx answer or a transport
    error is reported as a failed delivery, never as a success.
    """

    endpoint = "https://api.resend.com/emails"

    def __init__(
        self,
        *,
        api_key: str,
        email_from: str,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not _RESEND_API_KEY.fullmatch(api_key.strip()):
            raise ValueError("a valid transactional mail API key is required")
        if not isinstance(email_from, str) or not _EMAIL.fullmatch(email_from.strip()):
            raise ValueError("a valid sender address is required")
        self._api_key = api_key.strip()
        self._email_from = email_from.strip()
        self._http_transport = http_transport

    async def send(self, *, to: str, subject: str, text: str) -> bool:
        if not isinstance(to, str) or not _EMAIL.fullmatch(to.strip()):
            return False
        payload = {
            "from": self._email_from,
            "to": [to.strip()],
            "subject": subject,
            "text": text,
        }
        try:
            async with httpx.AsyncClient(
                transport=self._http_transport,
                timeout=httpx.Timeout(6.0, connect=3.0),
                follow_redirects=False,
            ) as client:
                result = await client.post(
                    self.endpoint,
                    json=payload,
                    headers={
                        "Accept": "application/json",
                        "Authorization": "Bearer " + self._api_key,
                    },
                )
        except (httpx.HTTPError, ValueError, TypeError):
            return False
        return 200 <= result.status_code < 300


def build_reset_mail_text(link: str) -> str:
    return RESET_MAIL_BODY.format(link=link)


def build_email_delivery(
    *,
    resend_api_key: str = "",
    email_from: str = "",
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> EmailDelivery | None:
    """Build the configured delivery transport, or ``None`` when unconfigured.

    ``None`` is an honest "this deployment cannot send mail" answer. The reset
    request route turns it into a retryable refusal instead of a fake success.
    """

    api_key = (resend_api_key or "").strip()
    sender = (email_from or "").strip()
    if not api_key or not sender:
        return None
    try:
        return ResendEmailDelivery(
            api_key=api_key,
            email_from=sender,
            http_transport=http_transport,
        )
    except ValueError:
        return None


__all__ = [
    "EmailDelivery",
    "RESET_MAIL_BODY",
    "RESET_MAIL_SUBJECT",
    "ResendEmailDelivery",
    "build_email_delivery",
    "build_reset_mail_text",
]
