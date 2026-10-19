"""B66 inquiry acceptance, privacy and durable channel notification tests."""
from pathlib import Path

import httpx
import pytest

from app.b66_member_inquiries import D1B66InquiryStore, deliver_inquiry
from app.b66_signup_notifications import B66SignupNotifier
from test_b66_admin_membership import seed_db


def inquiry_store():
    db, admin, user, fake = seed_db()
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    for name in ("038_b66_member_inquiries.sql",
                 "051_b66_inquiry_quote_skill_assist.sql"):
        db.conn.executescript((migrations / name).read_text(encoding="utf-8"))
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

@pytest.mark.asyncio
async def test_inquiries_admin_only_and_status_updates(monkeypatch):
    import json
    from types import SimpleNamespace
    from app import b66_member_inquiries as mod
    from app.b66_member_admin import D1B66MemberAdminStore
    db, admin, member, store = inquiry_store()
    inquiry = await store.submit(member, "usage", "How to export", "Where is the export?")
    admin_store = D1B66MemberAdminStore(db, admin_email="admin@example.test")

    class Request:
        headers = {"content-type": "application/json"}
        query_params = {"status": "all"}
        path_params = {"inquiry_id": inquiry["inquiry_id"]}
        app = SimpleNamespace(state=SimpleNamespace(
            b66_inquiry_store=store, b66_member_admin_store=admin_store))
        async def stream(self):
            yield b'{"status":"resolved"}'

    req = Request()
    monkeypatch.setattr(mod, "current_user_id", lambda _: None)
    assert (await mod.b66_admin_inquiries(req)).status_code == 401
    assert (await mod.b66_admin_inquiry_status(req)).status_code == 401

    monkeypatch.setattr(mod, "current_user_id", lambda _: member)
    assert (await mod.b66_admin_inquiries(req)).status_code == 403
    assert (await mod.b66_admin_inquiry_status(req)).status_code == 403

    monkeypatch.setattr(mod, "current_user_id", lambda _: admin)
    entries = await mod.b66_admin_inquiries(req)
    assert entries.status_code == 200
    body = json.loads(entries.body)
    assert len(body["inquiries"]) == 1
    assert body["inquiries"][0]["body"] == "Where is the export?"
    assert (await mod.b66_admin_inquiry_status(req)).status_code == 200
    assert len(await store.list_admin("resolved")) == 1

    req.query_params = {"status": "invalid"}
    assert (await mod.b66_admin_inquiries(req)).status_code == 400


@pytest.mark.asyncio
async def test_multi_recipient_resend_signup_and_inquiry_payloads():
    import json
    from app.b66_signup_notifications import _parse_email_recipients

    recipients = ["first@example.org", "second@example.net"]
    assert _parse_email_recipients(" first@example.org , second@example.net ") == recipients
    assert _parse_email_recipients("first@example.org,first@EXAMPLE.org") == [
        "first@example.org"
    ]
    assert _parse_email_recipients("first@example.org,") == []
    assert _parse_email_recipients("first@example.org, invalid-address") == []
    assert _parse_email_recipients("first@example.org\nBcc:evil@example.com") == []
    assert _parse_email_recipients(",".join("u%d@example.org" % i for i in range(11))) == []
    posts = []

    def capture(request):
        assert str(request.url) == "https://api.resend.com/emails"
        payload = json.loads(request.content)
        assert payload["to"] == recipients
        assert payload["from"] == "no-reply@example.org"
        posts.append(payload)
        return httpx.Response(200, json={"id": "test-message-id"})

    db, _, member, store = inquiry_store()
    notifier = B66SignupNotifier(
        None, resend_api_key="re_mock_example", email_from="no-reply@example.org",
        email_to="first@example.org, second@example.net",
        http_transport=httpx.MockTransport(capture),
    )
    assert set(notifier.channels) == {"email"}
    assert await notifier._send("email")
    entry = await store.submit(member, "general", "Private subject", "Private inquiry body")
    assert await deliver_inquiry(store, notifier, entry) == {"sent": 1, "failed": 0}
    assert len(posts) == 2
    assert posts[0]["subject"] == "[B66] 신규 회원가입 알림"
    assert posts[1]["subject"] == "[B66] 회원 문의 접수"
    assert "Private inquiry body" not in posts[1]["text"]
    assert await store.pending() == []
    assert await deliver_inquiry(store, notifier, entry) == {"sent": 0, "failed": 0}
    assert len(posts) == 2


def test_invalid_multi_recipient_configuration_does_not_send_partially():
    invalid_values = ["one@example.org,", "one@example.org,not-an-email", "one@example.org\nBcc:bad@example.org"]
    for email_to in invalid_values:
        notifier = B66SignupNotifier(None, resend_api_key="re_mock",
                                      email_from="no-reply@example.org", email_to=email_to)
        assert "email" not in notifier.channels


@pytest.mark.asyncio
async def test_quote_skill_assist_category_accepted_and_labeled(monkeypatch):
    import json
    from types import SimpleNamespace
    from app import b66_member_inquiries as mod
    db, admin, member, store = inquiry_store()

    class Request:
        method = "POST"
        headers = {"content-type": "application/json"}
        app = SimpleNamespace(state=SimpleNamespace(
            b66_inquiry_store=store, b66_signup_notifier=None))
        payload = {
            "category": "quote_skill_assist",
            "subject": "Our quote form",
            "body": "Please reuse our header and table layout.",
        }
        async def stream(self):
            yield json.dumps(self.payload).encode("utf-8")

    monkeypatch.setattr(mod, "current_user_id", lambda _: member)
    response = await mod.b66_inquiries(Request())
    assert response.status_code == 201
    inquiries = await store.list_admin("open")
    assert len(inquiries) == 1
    assert inquiries[0]["category"] == "quote_skill_assist"

    sent = []
    def handler(request):
        sent.append(json.loads(request.content)["text"])
        return httpx.Response(200, json={"ok": True})
    notifier = B66SignupNotifier(
        None, telegram_bot_token="123456:" + "A" * 45,
        telegram_chat_id="-123456",
        http_transport=httpx.MockTransport(handler),
    )
    assert await deliver_inquiry(store, notifier, inquiries[0]) == {"sent": 1, "failed": 0}
    assert len(sent) == 1
    assert "견적서 양식 의뢰" in sent[0]
    assert "Please reuse our header" not in sent[0]


@pytest.mark.asyncio
async def test_category_migration_preserves_inquiries_and_receipts():
    db, admin, member, _ = seed_db()
    migrations = Path(__file__).resolve().parents[1] / "migrations"
    db.conn.executescript(
        (migrations / "038_b66_member_inquiries.sql").read_text(encoding="utf-8"))
    old_id = "b66inq_" + "a" * 32
    db.conn.execute(
        "INSERT INTO b66_member_inquiries "
        "(inquiry_id,user_id,category,subject,body,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,'open','2026-10-01T00:00:00.000Z','2026-10-01T00:00:00.000Z')",
        (old_id, member, "usage", "Old question", "Still readable"),
    )
    db.conn.execute(
        "INSERT INTO b66_inquiry_alert_delivery (inquiry_id,channel,delivered_at) "
        "VALUES (?,?,?)", (old_id, "telegram", "2026-10-01T00:00:01.000Z"),
    )
    db.conn.executescript(
        (migrations / "051_b66_inquiry_quote_skill_assist.sql").read_text(encoding="utf-8"))

    store = D1B66InquiryStore(db)
    own = await store.list_user(member)
    assert [(row["inquiry_id"], row["category"]) for row in own] == [
        (old_id, "usage")
    ]
    assert await store.receipt_exists(old_id, "telegram")
    assert [row["inquiry_id"] for row in await store.pending()] == [old_id]
    new = await store.submit(member, "quote_skill_assist", "New request", "Build our form")
    assert new["category"] == "quote_skill_assist"
    assert db.conn.execute("PRAGMA foreign_key_check").fetchall() == []
