"""Network-free conversation-to-quote runtime fixtures."""
from __future__ import annotations

from unittest.mock import MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_quote_conversation import B66QuoteConversationProjection
from app.config import Settings


USER_A = "usr_" + "a" * 32
USER_B = "usr_" + "b" * 32
SAVED_ID = "b66skill_" + "c" * 32


def _settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "b66-runtime.apps.googleusercontent.com",
        "google_client_secret": "b66-runtime-google-secret",
        "session_secret": "b66-runtime-session-secret-not-real-00",
        "session_max_age_seconds": 3600,
        "live_enabled": "false",
    }
    values.update(overrides)
    return Settings.from_values(**values)


def _skill():
    return {
        "schemaVersion": 1,
        "id": "saved-skill-1",
        "name": "우리 견적서",
        "fixedDefaults": {
            "sender": {"company": "테스트상사"},
            "validDays": 30,
            "taxMode": "EXCLUSIVE",
            "memo": "",
        },
        "variableSchema": {
            "recipient": True,
            "quoteNo": True,
            "issueDate": True,
            "items": True,
            "memo": True,
            "taxMode": True,
        },
        "internalTemplate": {
            "id": "template-private",
            "title": {"text": "견 적 서"},
        },
        "approval": {"status": "approved"},
        "fingerprint": "d" * 64,
        "rendererContract": "quote-template-renderer.v1",
        "calculationAuthority": "quote-core",
    }


def _saved_row(*, user_id=USER_A, workspace_id=None):
    workspace = workspace_id or f"owner:{user_id}"
    return {
        "saved_skill_id": SAVED_ID,
        "workspace_id": workspace,
        "skill_id": "saved-skill-1",
        "skill_name": "우리 견적서",
        "skill_fingerprint": "d" * 64,
        "skill_version": 1,
        "status": "approved",
        "skill": _skill(),
    }


class _Store:
    def __init__(self):
        self.rows = {
            (USER_A, f"owner:{USER_A}", SAVED_ID): _saved_row(user_id=USER_A)
        }
        self.calls = []

    async def list_skills(self, *, user_id, workspace_id, limit=20):
        self.calls.append(("list", user_id, workspace_id))
        result = []
        for (uid, wid, _), row in self.rows.items():
            if uid == user_id and wid == workspace_id and row["status"] == "approved":
                result.append({k: v for k, v in row.items() if k != "skill"})
        return result[:limit]

    async def get_skill(self, *, user_id, workspace_id, saved_skill_id):
        self.calls.append(("get", user_id, workspace_id, saved_skill_id))
        return self.rows.get((user_id, workspace_id, saved_skill_id))


class _Interpreter:
    def __init__(self):
        self.calls = []

    async def interpret(self, *, message, skill, model_id=None):
        self.calls.append((message, skill))
        return B66QuoteConversationProjection(
            recipient={
                "company": "ABC건설",
                "person": None,
                "address": None,
                "email": None,
            },
            quote_no=None,
            issue_date=None,
            items=({"name": "배관", "qty": 20, "unitPrice": 30000},),
            memo=None,
            tax_mode=None,
            missing=(),
        )


def _client(store, interpreter, *, user_id=USER_A, signed_in=True):
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_saved_quote_skill_store=store,
        b66_quote_interpreter=interpreter,
    )
    client = TestClient(app, base_url="https://chat.example.test")
    if signed_in:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, user_id, canonical_session_id="session_test_a"),
            domain="chat.example.test",
            path="/",
        )
    return client
