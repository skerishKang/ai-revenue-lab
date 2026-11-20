"""#8105followup: every channel's first line comes from one label table."""
from __future__ import annotations

import asyncio

from app.ops_alert_delivery import (
    CHAT_SITE_LABEL,
    KIND_LABELS,
    SITE_LABELS,
    alert_message,
    alert_title,
    deliver_alert,
)
from app.ops_notify_event import EVENT_KINDS, SITE_LINKS

BASE = "https://chat.example.test"


def _site_entry(site, kind, *, summary=False):
    return {
        "alert_id": "opsalr_" + "a" * 32,
        "notify_site": site,
        "notify_kind": kind,
        "notify_title": "safe-title",
        "notify_source_id": "src_1",
        "notify_audience": "summary" if summary else "event",
        "notify_day": "2026-11-20",
        "notify_count": 3,
        "notify_body": "private-body-text",
        "account_email": "private@example.test",
    }


def _chat_entry(kind):
    return {
        "alert_id": "opsalr_" + "b" * 32,
        "kind": kind,
        "target_id": "target_1",
        "label": "분류",
        "body": "private-body-text",
        "email": "private@example.test",
        "user_id": "private-account-id",
    }


def _expected(entry):
    site = entry.get("notify_site")
    if site in SITE_LINKS:
        label = SITE_LABELS.get(site, site)
        if entry.get("notify_audience") == "summary":
            return "[운영센터] %s 일일 요약 (%s)" % (label, entry["notify_day"])
        return "[운영센터] %s · %s" % (
            label, KIND_LABELS.get(entry.get("notify_kind"), entry.get("notify_kind")),
        )
    return "[운영센터] %s · %s" % (
        CHAT_SITE_LABEL, KIND_LABELS.get(entry.get("kind"), entry.get("kind")),
    )


def test_the_table_covers_the_requested_codes():
    assert SITE_LABELS["lovetree"] == "러브트리"
    assert SITE_LABELS["pc"] == "PC"
    for kind in EVENT_KINDS:
        assert kind in KIND_LABELS


def test_every_site_and_kind_first_line_matches_the_computed_title():
    for site in SITE_LINKS:
        for kind in EVENT_KINDS:
            entry = _site_entry(site, kind)
            expected = _expected(entry)
            assert alert_title(entry) == expected
            assert alert_message(entry, base_url=BASE).splitlines()[0] == expected


def test_chat_alerts_use_the_chat_label_for_every_known_kind():
    for kind in KIND_LABELS:
        entry = _chat_entry(kind)
        expected = _expected(entry)
        assert alert_title(entry) == expected
        assert alert_message(entry, base_url=BASE).splitlines()[0] == expected


def test_unknown_codes_fall_back_to_the_original_name(monkeypatch):
    monkeypatch.setitem(SITE_LINKS, "newsite", "https://site.example.test")
    entry = _site_entry("newsite", "brand_new_kind")
    expected = _expected(entry)
    assert "newsite" in expected and "brand_new_kind" in expected
    assert alert_title(entry) == expected
    assert alert_message(entry, base_url=BASE).splitlines()[0] == expected
    chat = _chat_entry("brand_new_kind")
    assert alert_title(chat) == _expected(chat)


class _Store:
    async def receipt_exists(self, alert_id, channel):
        return False

    async def channel_abandoned(self, alert_id, channel):
        return False

    async def record_success(self, alert_id, channel):
        return None

    async def record_failure(self, alert_id, channel):
        return None

    async def complete(self, alert_id, channels):
        return None


class _Notifier:
    channels = {"telegram": (), "discord": (), "email": ()}

    def __init__(self):
        self.calls = []

    async def _send(self, channel, *, message=None, subject=None):
        self.calls.append({"channel": channel, "message": message, "subject": subject})
        return True


def test_all_three_channels_share_one_title_and_keep_private_fields_out():
    async def scenario():
        entry = _site_entry("lovetree", "feedback_new")
        notifier = _Notifier()
        result = await deliver_alert(_Store(), notifier, entry, base_url=BASE)
        assert result == {"sent": 3, "failed": 0}
        expected = _expected(entry)
        assert {call["channel"] for call in notifier.calls} == set(_Notifier.channels)
        for call in notifier.calls:
            assert call["message"].splitlines()[0] == expected
            assert call["subject"] == expected
            for forbidden in ("private-body-text", "private@example.test"):
                assert forbidden not in call["message"]

    asyncio.run(scenario())
