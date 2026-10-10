"""#3396: signed-account guided-resume store and actual migration contract."""
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_guided_draft import D1GuidedDraftStore, GuidedDraftError, normalize_guided_state
from app.config import Settings

A = "usr_" + "a" * 32
B = "usr_" + "b" * 32
WA, WB = "owner:" + A, "owner:" + B
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "028_b66_guided_draft.sql"


def sample():
    return {
        "schema": "b66.guided-draft.v1", "mode": "guided",
        "step": "price", "currentItem": 0, "taxUnknown": False,
        "savedSkillId": "b66skill_" + "b" * 32,
        "draft": {
            "recipient": {"company": "가상 테스트 회사", "person": "", "address": "", "email": ""},
            "sender": {"company": "승인된 회사"},
            "items": [{"id": "item-1", "name": "장비", "qty": 2, "unitPrice": None, "unit": ""}],
            "tax": {"mode": "EXCLUSIVE"}, "memo": "",
            "meta": {"quoteNo": "B66-E2E-TEST", "issueDate": "2026-10-10"},
        },
    }


def _client(store, user=A, signed_in=True):
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="google", public_base_url="https://chat.example.test",
        google_client_id="guided.apps.googleusercontent.com",
        google_client_secret="synthetic-only-google-secret",
        session_secret="synthetic-only-guided-test-session-secret",
        session_max_age_seconds=3600, live_enabled="false",
    )
    app = create_app(settings=settings, history_store=MagicMock(),
                     b66_guided_draft_store=store)
    client = TestClient(app, base_url="https://chat.example.test")
    if signed_in:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, user),
                           domain="chat.example.test", path="/")
    return client


class Prepared:
    def __init__(self, db, sql):
        self.db, self.sql, self.args = db, sql, ()

    def bind(self, *args):
        self.args = args
        return self

    async def first(self):
        row = self.db.execute(self.sql, self.args).fetchone()
        return dict(row) if row else None

    async def run(self):
        self.db.execute(self.sql, self.args)
        self.db.commit()
        return {}


class SQLiteD1:
    def __init__(self, db):
        self.db = db

    def prepare(self, sql):
        return Prepared(self.db, sql)


@pytest.fixture
def source():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY)")
    db.executemany("INSERT INTO users(id) VALUES (?)", [(A,), (B,)])
    db.executescript(MIGRATION.read_text(encoding="utf-8"))
    yield db, D1GuidedDraftStore(SQLiteD1(db))
    db.close()


def test_real_sql_migration_account_slot_reload_and_foreign_account(source):
    db, store = source
    own = _client(store)
    foreign = _client(store, user=B)
    original = sample()

    assert own.get("/api/b66/guided-draft").json() == {"ok": True, "state": None}
    saved = own.put("/api/b66/guided-draft", json=original)
    assert saved.status_code == 200
    assert saved.headers["cache-control"].startswith("private")
    result = own.get("/api/b66/guided-draft")
    assert result.status_code == 200 and result.json()["state"] == normalize_guided_state(original)
    assert foreign.get("/api/b66/guided-draft").json()["state"] is None

    # Same real D1 source after a separate authenticated HTTP client was created.
    another_browser = _client(store)
    assert another_browser.get("/api/b66/guided-draft").json()["state"]["step"] == "price"
    updated = sample()
    updated["step"] = "moreItems"
    updated["draft"]["items"][0]["unitPrice"] = 50000
    assert own.put("/api/b66/guided-draft", json=updated).status_code == 200
    assert db.execute("SELECT COUNT(*) FROM b66_guided_draft").fetchone()[0] == 1
    assert another_browser.get("/api/b66/guided-draft").json()["state"]["step"] == "moreItems"
    assert foreign.delete("/api/b66/guided-draft").status_code == 200
    assert own.get("/api/b66/guided-draft").json()["state"] is not None
    assert own.delete("/api/b66/guided-draft").status_code == 200
    assert own.get("/api/b66/guided-draft").json()["state"] is None


def test_unauthorized_and_caller_supplied_owner_fail_closed(source):
    _, store = source
    anonymous = _client(store, signed_in=False)
    for method in ("get", "put", "delete"):
        reply = getattr(anonymous, method)(
            "/api/b66/guided-draft",
            **({"json": sample()} if method == "put" else {}),
        )
        assert reply.status_code == 401
    owner = _client(store)
    for key in ("user_id", "owner", "workspaceId", "tenant"):
        value = sample()
        value[key] = B
        assert owner.put("/api/b66/guided-draft", json=value).status_code == 400
    assert owner.get("/api/b66/guided-draft").json()["state"] is None


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(mode="chat"),
    lambda d: d.update(step="unexpected"),
    lambda d: d.update(currentItem=8),
    lambda d: d.update(taxUnknown="yes"),
    lambda d: d.update(sourceFile="base64:xyz"),
    lambda d: d["draft"].update(rendererHtml="<img>"),
    lambda d: d["draft"]["items"].extend([{}] * 3),
    lambda d: d["draft"]["items"][0].update(unitPrice=float("nan")),
    lambda d: d["draft"]["recipient"].update(company="x" * 250),
    lambda d: d["draft"]["items"][0].update(secret="customer"),
])
def test_invalid_or_non_guided_source_data_is_rejected(source, mutate):
    _, store = source
    invalid = sample()
    mutate(invalid)
    if any(isinstance(row.get("unitPrice"), float) and not __import__("math").isfinite(row["unitPrice"])
           for row in invalid.get("draft", {}).get("items", []) if isinstance(row, dict)):
        # TestClient itself rejects NaN before network; normalization must too.
        with pytest.raises(GuidedDraftError):
            normalize_guided_state(invalid)
    else:
        assert _client(store).put("/api/b66/guided-draft", json=invalid).status_code == 400


def test_malformed_existing_row_is_not_sent_to_client(source):
    db, store = source
    db.execute(
        "INSERT INTO b66_guided_draft (user_id,workspace_id,state_json,updated_at)"
        " VALUES (?,?,?,?)", (A, WA, '{"schema":"evil"}', "2026-10-10"),
    )
    db.commit()
    result = _client(store).get("/api/b66/guided-draft")
    assert result.status_code == 503 and result.json()["error"]["code"] == "guided_state_read_failed"


def test_oversize_and_secret_fields_are_not_stored(source):
    _, store = source
    payload = sample()
    payload["draft"]["memo"] = "x" * 18000
    assert _client(store).put("/api/b66/guided-draft", json=payload).status_code in {400, 413}
    assert _client(store).get("/api/b66/guided-draft").json()["state"] is None
    for term in ("rawBytes", "providerPayload", "html", "apiKey", "secret"):
        obj = sample()
        obj["draft"][term] = "forbidden"
        with pytest.raises(GuidedDraftError):
            normalize_guided_state(obj)


def test_same_user_foreign_workspace_is_unreadable_and_untouched(source):
    """The authenticated route derives workspace; query/body cannot select another slot."""
    db, store = source
    foreign_workspace = "owner:independent-workspace"
    saved = json.dumps(normalize_guided_state(sample()), ensure_ascii=False)
    db.execute(
        "INSERT INTO b66_guided_draft (user_id,workspace_id,state_json,updated_at)"
        " VALUES (?,?,?,?)", (A, foreign_workspace, saved, "2026-10-10")
    )
    db.commit()
    own = _client(store)
    url = "/api/b66/guided-draft?workspace_id=" + foreign_workspace
    assert own.get(url).json() == {"ok": True, "state": None}
    assert own.delete(url).status_code == 200
    assert own.get(url).json() == {"ok": True, "state": None}
    row = db.execute(
        "SELECT state_json FROM b66_guided_draft WHERE user_id=? AND workspace_id=?",
        (A, foreign_workspace)
    ).fetchone()
    assert row is not None and row["state_json"] == saved
    assert own.put("/api/b66/guided-draft", json=sample()).status_code == 200
    assert db.execute("SELECT COUNT(*) FROM b66_guided_draft").fetchone()[0] == 2
