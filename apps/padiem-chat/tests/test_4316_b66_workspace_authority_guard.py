"""#4316 — a half-configured identity authority stops every B66 owner route first.

The workspace is server-owned (`_resolve_memory_workspace`). When a deployment
binds only one of the two identity components, the resolution is unavailable and
must be treated as a refusal — not as "no workspace", and not as a reason to ask
a store what it thinks. The certified-PDF and native-sol routes already answered
`workspace_authority_unavailable`; this file pins the same boundary for the
remaining customer-data routes so a later store change cannot quietly turn a
missing scope into a wider read.

Each case asserts three things: the refusal code, that the store was never
asked, and that no customer value came back in the body.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings

USER_A = "usr_" + "a" * 32
SAVED_ID = "b66skill_" + "c" * 32
ASSET_ID = "b66asset_" + "e" * 32


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="b66-workspace-boundary.apps.googleusercontent.com",
        google_client_secret="b66-workspace-boundary-google-secret",
        session_secret="b66-workspace-boundary-session-secret-",
        session_max_age_seconds=3600,
        live_enabled="false",
    )


class _SkillStore:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def list_skills(self, *, user_id, workspace_id, limit=20):
        self.calls.append(("list", user_id, workspace_id))
        return [{"saved_skill_id": SAVED_ID, "skill_name": "우리 견적서"}]

    async def get_skill(self, *, user_id, workspace_id, saved_skill_id):
        self.calls.append(("get", user_id, workspace_id, saved_skill_id))
        return {"saved_skill_id": saved_skill_id, "skill": {"id": "private-skill"}}


class _Interpreter:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def interpret(self, *, message, skill, model_id=None):
        self.calls.append((message, skill))
        return {"draft": {"recipient": "private"}}

    def safe_dict(self):
        return {}


class _ProfileStore:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def get_profile(self, *, user_id, workspace_id):
        self.calls.append(("get", user_id, workspace_id))
        return {"company": "비공개 회사"}

    async def put_profile(self, *, user_id, workspace_id, profile):
        self.calls.append(("put", user_id, workspace_id))
        return dict(profile)


class _AssetStore:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def get_for_owner(self, *, user_id, workspace_id, asset_id):
        self.calls.append(("get", user_id, workspace_id, asset_id))
        return None


def _client(**kwargs) -> TestClient:
    """A signed-in client whose identity authority is only half configured."""

    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        # A shadow store with no authority (and vice versa) is the unavailable
        # case: neither component alone may resolve a workspace.
        identity_shadow_store=object(),
        **kwargs,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, USER_A),
        domain="chat.example.test",
        path="/",
    )
    return client


def _assert_unavailable(response) -> None:
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "workspace_authority_unavailable", response.text
    assert "private" not in response.text
    assert "비공개" not in response.text


def test_saved_skill_list_refuses_before_reading_the_store() -> None:
    store = _SkillStore()
    client = _client(b66_saved_quote_skill_store=store)
    _assert_unavailable(client.get("/api/b66/saved-skills"))
    assert store.calls == []


def test_saved_skill_detail_refuses_before_reading_the_store() -> None:
    store = _SkillStore()
    client = _client(b66_saved_quote_skill_store=store)
    _assert_unavailable(client.get(f"/api/b66/saved-skills/{SAVED_ID}"))
    assert store.calls == []


def test_quote_interpret_refuses_before_the_skill_or_the_model() -> None:
    store = _SkillStore()
    interpreter = _Interpreter()
    client = _client(b66_saved_quote_skill_store=store, b66_quote_interpreter=interpreter)
    response = client.post(
        "/api/b66/quote/interpret",
        json={
            "saved_skill_id": SAVED_ID,
            "model_id": "test-fixture/quote-projection",
            "message": "ABC건설에 배관 20개",
        },
    )
    _assert_unavailable(response)
    assert store.calls == []
    assert interpreter.calls == []


def test_company_profile_get_refuses_before_reading_the_store() -> None:
    store = _ProfileStore()
    client = _client(b66_company_profile_store=store)
    _assert_unavailable(client.get("/api/b66/company-profile"))
    assert store.calls == []


def test_company_profile_put_refuses_before_writing_the_store() -> None:
    store = _ProfileStore()
    client = _client(b66_company_profile_store=store)
    _assert_unavailable(
        client.put("/api/b66/company-profile", json={"company": "테스트상사"})
    )
    assert store.calls == []


def test_quote_asset_detail_refuses_before_reading_the_store() -> None:
    store = _AssetStore()
    client = _client(b66_quote_asset_store=store)
    _assert_unavailable(client.get(f"/api/b66/assets/{ASSET_ID}"))
    assert store.calls == []
