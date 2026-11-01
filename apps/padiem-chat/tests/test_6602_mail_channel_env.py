"""Mail-channel env resolution for the COM2 CPython host.

The Worker reads these names from trusted bindings; the host reads them from
systemd's EnvironmentFile. The order must stay reuse-first, and a missing
credential must keep the honest "cannot send" answer.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mail_channel_env import (  # noqa: E402
    MAIL_API_KEY_NAMES,
    MAIL_FROM_NAMES,
    resolve_b66_channel,
    resolve_mail_channel,
)
from app.password_reset_delivery import build_email_delivery  # noqa: E402


def test_padiem_names_are_the_last_reuse_fallback():
    key = "re_" + "a" * 32
    resolved_key, sender = resolve_mail_channel(
        {
            "PADIEM_RESEND_API_KEY": key,
            "PADIEM_RESEND_EMAIL_FROM": "noreply@notify.padiem.net",
        }
    )
    assert resolved_key == key
    assert sender == "noreply@notify.padiem.net"


def test_blank_earlier_name_is_skipped():
    key = "re_" + "b" * 32
    resolved_key, sender = resolve_mail_channel(
        {
            "B66_ALERT_RESEND_API_KEY": "   ",
            "PADIEM_CHAT_PASSWORD_RESET_RESEND_API_KEY": key,
            "B66_ALERT_EMAIL_FROM": "",
            "PADIEM_CHAT_PASSWORD_RESET_EMAIL_FROM": "reset@notify.padiem.net",
        }
    )
    assert resolved_key == key
    assert sender == "reset@notify.padiem.net"


def test_first_configured_name_wins():
    owner_key = "re_" + "c" * 32
    resolved_key, sender = resolve_mail_channel(
        {
            "B66_ALERT_RESEND_API_KEY": owner_key,
            "PADIEM_RESEND_API_KEY": "re_" + "d" * 32,
            "B66_ALERT_EMAIL_FROM": "owner@notify.padiem.net",
            "PADIEM_RESEND_EMAIL_FROM": "noreply@notify.padiem.net",
        }
    )
    assert resolved_key == owner_key
    assert sender == "owner@notify.padiem.net"


def test_missing_configuration_builds_no_delivery():
    key, sender = resolve_mail_channel({})
    assert (key, sender) == ("", "")
    assert build_email_delivery(resend_api_key=key, email_from=sender) is None


def test_configured_pair_builds_a_delivery():
    key = "re_" + "e" * 32
    delivery = build_email_delivery(
        resend_api_key=key, email_from="noreply@notify.padiem.net"
    )
    assert delivery is not None
    assert callable(getattr(delivery, "send", None))


def test_b66_recipient_is_read_separately_from_the_sender():
    values = resolve_b66_channel(
        {"B66_ALERT_EMAIL_TO": "owner@example.com", "B66_ALERT_DISCORD_WEBHOOK_URL": ""}
    )
    assert values["email_to"] == "owner@example.com"
    assert values["discord_webhook_url"] == ""
    assert values["telegram_bot_token"] == ""
    assert values["telegram_chat_id"] == ""


def test_documented_reuse_order_is_preserved():
    assert MAIL_API_KEY_NAMES[-1] == "PADIEM_RESEND_API_KEY"
    assert MAIL_FROM_NAMES[-1] == "PADIEM_RESEND_EMAIL_FROM"
