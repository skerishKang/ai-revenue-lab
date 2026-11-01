"""Transactional-mail channel settings read from the host process environment.

The Worker resolves the same names from trusted bindings (``app/worker_config.py``
``MAIL_API_KEY_BINDING_NAMES`` / ``MAIL_FROM_BINDING_NAMES``); the CPython host on
COM2 reads them from systemd's ``EnvironmentFile``. One credential, one
reuse-first order, no second issuance.

Nothing here logs or formats a key: :func:`resolve_mail_channel` hands the raw
values back to its caller only, and an absent name stays empty so the caller can
fail closed instead of pretending to send.
"""
from __future__ import annotations

from collections.abc import Mapping

#: Reuse-first order, identical to ``worker_config.MAIL_API_KEY_BINDING_NAMES``.
#: The already provisioned owner-side names come first, so a deployment never has
#: to mint a second credential for the lost-password reset mail.
MAIL_API_KEY_NAMES: tuple[str, ...] = (
    "B66_ALERT_RESEND_API_KEY",
    "PADIEM_CHAT_PASSWORD_RESET_RESEND_API_KEY",
    "PADIEM_RESEND_API_KEY",
)
MAIL_FROM_NAMES: tuple[str, ...] = (
    "B66_ALERT_EMAIL_FROM",
    "PADIEM_CHAT_PASSWORD_RESET_EMAIL_FROM",
    "PADIEM_RESEND_EMAIL_FROM",
)
B66_ALERT_EMAIL_TO_NAME = "B66_ALERT_EMAIL_TO"
B66_ALERT_TELEGRAM_BOT_TOKEN_NAME = "B66_ALERT_TELEGRAM_BOT_TOKEN"
B66_ALERT_TELEGRAM_CHAT_ID_NAME = "B66_ALERT_TELEGRAM_CHAT_ID"
B66_ALERT_DISCORD_WEBHOOK_URL_NAME = "B66_ALERT_DISCORD_WEBHOOK_URL"


def _first(names: tuple[str, ...], env: Mapping[str, str]) -> str:
    for name in names:
        value = env.get(name, "")
        value = value.strip() if isinstance(value, str) else ""
        if value:
            return value
    return ""


def resolve_mail_channel(env: Mapping[str, str]) -> tuple[str, str]:
    """Return ``(api_key, sender)`` using the first non-empty name of each list."""
    return _first(MAIL_API_KEY_NAMES, env), _first(MAIL_FROM_NAMES, env)


def resolve_b66_channel(env: Mapping[str, str]) -> dict[str, str]:
    """Return the optional B66 signup-alert channel values; missing ones stay empty."""
    return {
        "telegram_bot_token": _first((B66_ALERT_TELEGRAM_BOT_TOKEN_NAME,), env),
        "telegram_chat_id": _first((B66_ALERT_TELEGRAM_CHAT_ID_NAME,), env),
        "discord_webhook_url": _first((B66_ALERT_DISCORD_WEBHOOK_URL_NAME,), env),
        "email_to": _first((B66_ALERT_EMAIL_TO_NAME,), env),
    }


__all__ = [
    "MAIL_API_KEY_NAMES",
    "MAIL_FROM_NAMES",
    "B66_ALERT_EMAIL_TO_NAME",
    "resolve_b66_channel",
    "resolve_mail_channel",
]
