"""#7607: starting a Google connection from the pages.dev mirror must say where to.

``padiem-chat.pages.dev`` is a reviewed origin for ordinary cookie mutations
(#6850), but it cannot finish the Google connect handoff: the #7553 browser
binding cookie is set for ``.padiem.net`` by a cross-site response, and the
OAuth callback returns to the ``.padiem.net`` host. A start from the mirror
therefore fails inside the callback with no user-facing reason.

The server can see this before it asks Google for anything: the request Origin
is one of the reviewed parallel origins (server configuration
``PADIEM_CHAT_PUBLIC_BASE_URLS``) but not the canonical public origin. That
case now answers with a Korean instruction naming the canonical host, still
before the ticket RPC, so no connect ticket and no authorization URL are
created. Cookie validation and the reviewed-origin list are not widened.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.history import UserProfile
from app.main import create_app

CANONICAL = "https://chat.padiem.net"
PAGES = "https://padiem-chat.pages.dev"
UNREVIEWED = "https://evil.example.test"
SESSION_SECRET = "issue-7607-pages-google-connect-session-secret-000000000"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=CANONICAL,
        public_base_urls=PAGES,
        google_client_id="issue-7607.apps.googleusercontent.com",
        google_client_secret="unit-test-only-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


class MemoryHistoryStore:
    def __init__(self) -> None:
        self.profile = UserProfile("usr_" + "7" * 32, "user@example.test", "Pages User", "")

    async def get_user(self, user_id):
        return self.profile if user_id == self.profile.id else None


class MemoryShadowStore:
    def __init__(self, record: IdentityShadowRecord | None) -> None:
        self.record = record

    async def load_projection(self, product_user_id):
        if self.record is None or self.record.product_user_id != product_user_id:
            return None
        return self.record


class FakeControlPlaneBinding:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.ticket = "opaque-connect-ticket-that-never-appears-in-headers"

    async def issue_google_connect_ticket(self, payload):
        self.calls.append(("ticket", dict(payload)))
        return {
            "ok": True,
            "ticket": {
                "connect_ticket": self.ticket,
                "connector_id": payload["connector_id"],
                "expires_at": (NOW + timedelta(minutes=3)).isoformat(),
            },
        }


def shadow(profile_id: str) -> IdentityShadowRecord:
    return IdentityShadowRecord(
        product_user_id=profile_id,
        canonical_subject_id="sub_test",
        auth_session_id="sess_test",
        session_revision=1,
        session_state="active",
        session_expires_at=NOW + timedelta(hours=1),
        observed_at=NOW,
    )


def app_fixture(*, auth_transport=None):
    history = MemoryHistoryStore()
    binding = FakeControlPlaneBinding()
    app = create_app(
        settings(),
        auth_transport=auth_transport,
        history_store=history,
        control_plane_identity_authority=CloudflareControlPlaneIdentityAuthority(binding),
        identity_shadow_store=MemoryShadowStore(shadow(history.profile.id)),
    )
    return app, history, binding


def _client(app, profile_id: str):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=CANONICAL)
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings(), profile_id),
        domain="chat.padiem.net",
        path="/",
    )
    return client


def _oauth_edge(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "ok": True,
            "authorization": {
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=test",
                "connector_id": "google-drive",
                "expires_at": (NOW + timedelta(minutes=10)).isoformat(),
                "raw_connect_ticket": False,
            },
        },
    )


@pytest.mark.asyncio
async def test_pages_origin_start_is_refused_before_google_with_a_named_instruction():
    app, history, binding = app_fixture()
    async with _client(app, history.profile.id) as client:
        response = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": PAGES},
            json={"connector_id": "google-drive", "begin_oauth": True},
        )

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "connector_ticket_origin_not_canonical"
    assert "chat.padiem.net" in body["error"]["message"]
    assert "에서" in body["error"]["message"]
    # Nothing was asked of the identity authority or Google.
    assert binding.calls == []
    assert "authorization" not in body
    assert binding.ticket not in response.text


@pytest.mark.asyncio
async def test_canonical_origin_start_still_reaches_google_exactly_as_before():
    app, history, binding = app_fixture(auth_transport=httpx.MockTransport(_oauth_edge))
    async with _client(app, history.profile.id) as client:
        response = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": CANONICAL},
            json={"connector_id": "google-drive", "begin_oauth": True},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["authorization"]["connector_id"] == "google-drive"
    assert body["authorization"]["authorization_url"].startswith("https://accounts.google.com/")
    assert binding.calls == [("ticket", {"session_id": "sess_test", "connector_id": "google-drive"})]


@pytest.mark.asyncio
async def test_an_unreviewed_origin_keeps_the_original_rejection():
    app, history, binding = app_fixture()
    async with _client(app, history.profile.id) as client:
        response = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": UNREVIEWED},
            json={"connector_id": "google-drive", "begin_oauth": True},
        )

    assert response.status_code == 403
    body = response.json()
    # The shared guard (no cookie-authenticated mutation from an unreviewed
    # origin) or this route answers, both unchanged; neither names a host.
    assert body["error"]["code"] in {"origin_rejected", "connector_ticket_origin_rejected"}
    assert "chat.padiem.net" not in json.dumps(body, ensure_ascii=False)
    assert binding.calls == []


def test_the_connect_buttons_show_the_canonical_host_line_for_that_refusal() -> None:
    """The server's refusal reaches the screen as its own line, not "try again".

    All three Google connect buttons (Drive, Gmail, Calendar) used to replace
    every failure with one generic line, so the guidance above never showed.
    """
    import json
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    static = Path(__file__).resolve().parents[1] / "static"
    app = (static / "app.js").read_text(encoding="utf-8")
    calendar = (static / "chat-calendar-module.js").read_text(encoding="utf-8")
    locale = (static / "locale.js").read_text(encoding="utf-8")

    start = app.index("  function connectorTicketErrorKey(")
    helper = app[start: app.index("\n  }\n", start) + 5]
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available")
    script = (
        helper
        + "\nconst out = ["
        + 'connectorTicketErrorKey({ error: { code: "connector_ticket_origin_not_canonical" } }, "fallback"),'
        + 'connectorTicketErrorKey({ error: { code: "connector_ticket_origin_rejected" } }, "fallback"),'
        + 'connectorTicketErrorKey(null, "fallback"),'
        + "];\nprocess.stdout.write(JSON.stringify(out));"
    )
    done = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == ["connectors-connect-canonical-only", "fallback", "fallback"]

    # Each button decides its line from the server's answer before it fails.
    assert app.count("ticketErrorKey = connectorTicketErrorKey(startDocument, ticketErrorKey);") == 2
    assert app.count("setConnectorCopy(connectorsError, ticketErrorKey);") == 2
    assert "ticketErrorKey = deps.connectorTicketErrorKey(startDocument, ticketErrorKey);" in calendar
    assert "deps.setConnectorCopy(deps.connectorsError, ticketErrorKey);" in calendar
    assert locale.count('"connectors-connect-canonical-only"') == 2
