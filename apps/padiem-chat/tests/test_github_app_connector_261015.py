"""GitHub App connector: signed owner, one-use OAuth, trusted installation, revocation."""
from __future__ import annotations
from urllib.parse import parse_qs, urlparse
import time
import httpx
import pytest
from app.auth import SESSION_COOKIE
from test_google_connector_ticket_bridge import app_fixture, cookie_for

ORIGIN = "https://chat.example.test"

class FakeGitHubStore:
    def __init__(self):
        self.states = {}
        self.links = {}
    async def begin(self, **kwargs):
        self.states[kwargs["state"]] = kwargs
    async def consume(self, **kwargs):
        saved = self.states.get(kwargs["state"])
        if not saved or saved["user_id"] != kwargs["user_id"] or saved["session"] != kwargs["session"]:
            return None
        self.states.pop(kwargs["state"])
        return saved["verifier"]
    async def save(self, **kwargs):
        self.links[kwargs["user_id"]] = kwargs
    async def status(self, user_id):
        link = self.links.get(user_id)
        return {"login": link["login"], "installation_id": link["installation_id"]} if link else None
    async def token_pair(self, user_id):
        link = self.links.get(user_id)
        return {k: link[k] for k in ("access_token", "refresh_token", "access_expires_at", "refresh_expires_at")} if link else None
    async def disconnect(self, user_id):
        self.links.pop(user_id, None)

class FakeGitHubProvider:
    def __init__(self):
        self.exchanges = 0
        self.installations = 0
    async def exchange(self, **kwargs):
        self.exchanges += 1
        assert kwargs["callback_url"] == ORIGIN + "/api/connectors/github/callback"
        return {"access_token": "ghu_test", "refresh_token": "ghr_test",
                "access_expires_at": int(time.time()) + 28800,
                "refresh_expires_at": int(time.time()) + 15897600}
    async def viewer(self, token):
        return 36503867, "skerishKang"
    async def installation(self, token):
        self.installations += 1
        return 171513671
    async def repositories(self, token, installation_id):
        assert installation_id == 171513671
        return [{"full_name": "skerishKang/ai-revenue-lab", "private": False}]

def app_with_ports():
    app, history, *_ = app_fixture()
    app.state.github_oauth_store = FakeGitHubStore()
    app.state.github_oauth_provider = FakeGitHubProvider()
    return app, history

@pytest.mark.asyncio
async def test_owner_oauth_installed_app_repositories_and_off():
    app, history = app_with_ports()
    owner_id = history.profile.id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(owner_id), domain="chat.example.test")
        start = await client.get("/api/connectors/github/start", follow_redirects=False)
        assert start.status_code == 303, start.text
        url = urlparse(start.headers["location"])
        assert url.netloc == "github.com" and url.path == "/login/oauth/authorize"
        data = parse_qs(url.query)
        assert data["code_challenge_method"] == ["S256"]
        assert data["client_id"] == ["Iv23liKN7UFDSli3stvg"]
        assert data["redirect_uri"] == [ORIGIN + "/api/connectors/github/callback"]
        callback = await client.get("/api/connectors/github/callback",
             params={"state": data["state"][0], "code": "temporary-code"}, follow_redirects=False)
        assert callback.status_code == 303, callback.text
        status = await client.get("/api/connectors/github/status")
        assert status.json() == {"ok": True, "state": "on", "login": "skerishKang"}
        repos = await client.get("/api/connectors/github/repositories")
        assert repos.json() == {"ok": True, "repositories": [{"full_name": "skerishKang/ai-revenue-lab", "private": False}]}
        assert app.state.github_oauth_provider.exchanges == 1
        replay = await client.get("/api/connectors/github/callback",
            params={"state": data["state"][0], "code": "duplicate"}, follow_redirects=False)
        assert replay.status_code == 400
        off = await client.post("/api/connectors/github/disconnect",
                                headers={"Origin": ORIGIN, "Content-Type": "application/json"})
        assert off.status_code == 200
        assert (await client.get("/api/connectors/github/status")).json() == {"ok": True, "state": "off"}

@pytest.mark.asyncio
async def test_owner_guards_and_foreign_origin_can_never_disconnect():
    app, history = app_with_ports()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
        assert (await client.get("/api/connectors/github/status")).status_code == 401
        assert (await client.get("/api/connectors/github/start")).status_code == 401
        client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test")
        forged = await client.post("/api/connectors/github/disconnect",
                                   headers={"Origin": "https://other.invalid", "Content-Type": "application/json"})
        assert forged.status_code == 403
        poisoned = await client.post("/api/connectors/github/disconnect",
                                     json={"user_id": "other"}, headers={"Origin": ORIGIN})
        assert poisoned.status_code == 400
        invalid = await client.get("/api/connectors/github/callback",params={"code":"fake","state":"forged"})
        assert invalid.status_code == 400
        assert app.state.github_oauth_provider.exchanges == 0
