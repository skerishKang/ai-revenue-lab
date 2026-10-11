"""B66 inquiry acceptance, privacy and durable channel notification tests."""
from pathlib import Path

import httpx
import pytest

from app.b66_member_inquiries import D1B66InquiryStore, deliver_inquiry
from app.b66_signup_notifications import B66SignupNotifier
from test_b66_admin_membership import seed_db


def inquiry_store():
    db, admin, user, fake = seed_db()
    migration = Path(__file__).resolve().parents[1] / "migrations" / "038_b66_member_inquiries.sql"
    db.conn.executescript(migration.read_text(encoding="utf-8"))
    return db, admin, user, D1B66InquiryStore(db)


@pytest.mark.asyncio
async def test_inquiry_saved_per_member_and_rate_limited():
    db, admin, user, store = inquiry_store()
    for i in range(3):
        event = await store.submit(user, "usage", f"Question {i}", "How does B66 work?")
        assert event["inquiry_id"].startswith("b66inq_")
        assert event["user_id"] == user
    with pytest.raises(ValueError, match="inquiry_rate_limited"):
        await store.submit(user, "usage", "Fourth", "Rate limit")
    own = await store.list_user(user)
    assert len(own) == 3
    assert len(await store.list_user(admin)) == 0
    assert len(await store.list_admin("open")) == 3
    assert await store.set_status(own[0]["inquiry_id"], "resolved")
    assert len(await store.list_admin("resolved")) == 1
    assert len(await store.list_admin("open")) == 2


@pytest.mark.asyncio
async def test_notify_delivers_only_metadata_and_dedupes_per_channel():
    db, admin, user, store = inquiry_store()
    event = await store.submit(user, "billing", "Private billing detail", "Secret customer details.")
    calls = []
    def handler(request):
        payload = request.content.decode("utf-8")
        calls.append((request.url.host, payload))
        assert "Private billing detail" not in payload
        assert "Secret customer details" not in payload
        return httpx.Response(200, json={"ok": True})
    notifier = B66SignupNotifier(
        None, telegram_bot_token="123456:" + "A" * 45,
        telegram_chat_id="-123456",
        discord_webhook_url="https://discord.com/api/webhooks/1234567890123456789/" + "Z" * 45,
        resend_api_key="re_test_not_real",
        email_from="no-reply@example.com", email_to="admin@example.com",
        http_transport=httpx.MockTransport(handler),
    )
    assert set(notifier.channels) == {"telegram", "discord", "email"}
    assert await deliver_inquiry(store, notifier, event) == {"sent": 3, "failed": 0}
    assert len(calls) == 3
    assert (await store.pending()) == []
    assert await deliver_inquiry(store, notifier, event) == {"sent": 0, "failed": 0}
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_inquiry_alert_failed_channel_can_retry_without_duplicates():
    db, admin, user, store = inquiry_store()
    event = await store.submit(user, "bug", "Failed preview", "PDF layout is broken.")
    calls = []
    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "discord.com" and calls.count("discord.com") == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})
    notifier = B66SignupNotifier(
        None, telegram_bot_token="123456:" + "A" * 45,
        telegram_chat_id="-123456",
        discord_webhook_url="https://discord.com/api/webhooks/1234567890123456789/" + "Z" * 45,
        http_transport=httpx.MockTransport(handler),
    )
    assert await deliver_inquiry(store, notifier, event) == {"sent": 1, "failed": 1}
    assert len(await store.pending()) == 1
    assert await deliver_inquiry(store, notifier, event) == {"sent": 1, "failed": 0}
    assert len(calls) == 3
    assert await store.pending() == []

@pytest.mark.asyncio
async def test_public_submission_requires_auth_and_valid_input(monkeypatch):
    import json
    from types import SimpleNamespace
    from app import b66_member_inquiries as mod
    db, admin, user, store = inquiry_store()

    class Request:
        method = "POST"
        headers = {"content-type": "application/json"}
        app = SimpleNamespace(state=SimpleNamespace(
            b66_inquiry_store=store, b66_signup_notifier=None))
        def __init__(self, payload):
            self.payload = payload
        async def stream(self):
            yield json.dumps(self.payload).encode("utf-8")

    monkeypatch.setattr(mod, "current_user_id", lambda request: None)
    data = {"category": "general", "subject": "Hello", "body": "Please help me"}
    assert (await mod.b66_inquiries(Request(data))).status_code == 401

    monkeypatch.setattr(mod, "current_user_id", lambda request: user)
    assert (await mod.b66_inquiries(Request(
        {"category": "general", "subject": "", "body": "message"}
    ))).status_code == 400
    saved = await mod.b66_inquiries(Request(data))
    assert saved.status_code == 201
    assert (json.loads(saved.body)["inquiry_id"]).startswith("b66inq_")
    assert len(await store.list_user(user)) == 1
    assert len(await store.list_user(admin)) == 0
