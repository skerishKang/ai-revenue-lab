"""#4657: B66 customer dialogue history — save, restore, continue, isolate.

These drive the real routes over the real ``D1HistoryStore`` on a real SQLite
database built from the migrations, so the product boundary and the persistence
contract are proven at the data-access boundary. No provider, network, paid
model call or Production action happens here: the B14 client is a stub.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_registered_model_boundary import B14AuthorizedModelRoute
from app.history import (
    D1HistoryStore,
    MAX_HISTORY_MESSAGE_CHARS,
    HISTORY_PREVIEW_SUFFIX,
    PRODUCT_SCOPE_CHAT,
)
from test_b66_quote_runtime import USER_A, USER_B, _settings

MODEL = "google/gemini-3.5-flash-lite"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


# ── real SQLite D1 double ────────────────────────────────────────────────────
class _Statement:
    def __init__(self, connection, sql, values=()):
        self.conn, self.sql, self.values = connection, sql, values

    def bind(self, *values):
        return _Statement(self.conn, self.sql, values)

    async def first(self):
        row = self.conn.execute(self.sql, self.values).fetchone()
        return dict(row) if row is not None else None

    async def run(self):
        cursor = self.conn.execute(self.sql, self.values)
        return SimpleNamespace(
            results=[dict(row) for row in cursor.fetchall()],
            meta={"changes": cursor.rowcount},
        )


class _D1:
    def __init__(self, connection):
        self.connection = connection

    def prepare(self, sql):
        return _Statement(self.connection, sql)


class _PrivateR2:
    """Private full-original store; the same shape the canonical store expects."""

    def __init__(self):
        self.objects = {}

    async def put(self, key, payload, **_kwargs):
        self.objects[key] = bytes(payload)

    async def get(self, key):
        data = self.objects.get(key)
        return None if data is None else SimpleNamespace(
            size=len(data), arrayBuffer=lambda: data,
        )

    async def delete(self, key):
        self.objects.pop(key, None)


def _open_db():
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for migration in (
        "001_auth_history.sql",
        "002_projects.sql",
        "042_conversation_product_scope.sql",
    ):
        db.executescript((MIGRATIONS / migration).read_text(encoding="utf8"))
    for owner in (USER_A, USER_B):
        db.execute(
            "INSERT INTO users(id,auth_provider,provider_subject,email,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (owner, "google", owner, owner + "@example.com", "2026-10-14", "2026-10-14"),
        )
    db.commit()
    return db


class _Resolver:
    def __init__(self):
        self.calls = []

    async def resolve_quote_model(self, requirements):
        self.calls.append(requirements)
        return B14AuthorizedModelRoute(
            model_id=MODEL, route_id="b66-dialogue-route",
            owner_policy_id="b66-owner-test", registered=True,
            enabled=True, authorized=True, credential_ready=True,
            route_count=1, capabilities=frozenset({"chat"}),
        )


class _Model:
    """A model stub that may answer differently per call, on purpose.

    A deterministic answer cannot prove retry safety: idempotency must never be
    decided by comparing the assistant's prose.
    """

    def __init__(self, answer="AI 견적 답변", answers=None, delay=None):
        self.calls = []
        self.answer = answer
        self.answers = list(answers or [])
        self.delay = delay
        self.fail = False

    def ensure_registered_quote_runtime_available(self):
        return None

    async def complete_registered_b66_chat_model(
        self, messages, *, model, additional_system_context=None, model_parameters=None
    ):
        self.calls.append([dict(m) for m in messages])
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("synthetic upstream failure")
        if len(self.calls) <= len(self.answers):
            answer = self.answers[len(self.calls) - 1]
        else:
            answer = self.answer
        return {"answer": answer, "route": {"mode": "manual", "model": model}}


def _app(history_store):
    settings = _settings()
    app = create_app(settings=settings, history_store=history_store)
    resolver, model = _Resolver(), _Model()
    app.state.b66_quote_model_resolver = resolver
    app.state.b14_client = model
    return settings, app, resolver, model


def _sign_in(settings, client, owner):
    client.cookies.set(
        SESSION_COOKIE, create_session_token(settings, owner),
        domain="chat.example.test", path="/",
    )


@pytest.fixture()
def env():
    db = _open_db()
    bucket = _PrivateR2()
    store = D1HistoryStore(_D1(db), full_context_bucket=bucket)
    settings, app, resolver, model = _app(store)
    client = TestClient(app, base_url="https://chat.example.test")
    yield SimpleNamespace(
        db=db, bucket=bucket, store=store, settings=settings,
        app=app, client=client, resolver=resolver, model=model,
    )
    db.close()


def _chat(client, *, messages, conversation_id=None, model_id=MODEL, turn_token=None):
    body = {"model_id": model_id, "messages": messages}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    if turn_token is not None:
        body["turn_token"] = turn_token
    return client.post("/api/b66/ai/chat", json=body)


def _client_for(env):
    """A fresh TestClient with the same signed-in cookie, for use in a thread."""
    from starlette.testclient import TestClient

    fresh = TestClient(env.app, base_url="https://chat.example.test")
    for name, value in env.client.cookies.items():
        fresh.cookies.set(name, value, domain="chat.example.test")
    return fresh


def _seed_b66(env, owner, user_text="철근 견적 알려줘", answer="네, 알려드릴게요"):
    _sign_in(env.settings, env.client, owner)
    env.model.answer = answer
    res = _chat(env.client, messages=[{"role": "user", "content": user_text}])
    assert res.status_code == 200, res.text
    assert res.json().get("dialogue_saved") is True, res.text
    return res.json()["conversation_id"]


def _seed_chat(env, owner, text="일반 채팅", answer="일반 답변"):
    import asyncio

    return asyncio.run(env.store.append_exchange(
        owner, None, text, answer, product_scope=PRODUCT_SCOPE_CHAT,
    ))


# ── guest / auth ─────────────────────────────────────────────────────────────
def test_guest_cannot_list_read_or_delete_b66_dialogues(env):
    assert env.client.get("/api/b66/ai/dialogues").status_code == 401
    cid = "chat_" + "a" * 32
    assert env.client.get(f"/api/b66/ai/dialogues/{cid}").status_code == 401
    assert env.client.delete(f"/api/b66/ai/dialogues/{cid}").status_code == 401
    assert env.resolver.calls == [] and env.model.calls == []


# ── list / search ────────────────────────────────────────────────────────────
def test_list_and_search_return_only_the_owners_b66_dialogue(env):
    b66_id = _seed_b66(env, USER_A)
    chat_id = _seed_chat(env, USER_A, text="철근 견적 채팅 대화")

    listed = env.client.get("/api/b66/ai/dialogues")
    assert listed.status_code == 200
    body = listed.json()
    assert body["authority"] == "b66-dialogue"
    assert [row["conversation_id"] for row in body["conversations"]] == [b66_id]
    assert chat_id not in listed.text

    found = env.client.get("/api/b66/ai/dialogues", params={"q": "철근"})
    assert found.status_code == 200
    assert [row["conversation_id"] for row in found.json()["conversations"]] == [b66_id]

    # A term that exists only in the same-owner Chat title returns nothing.
    chat_only = env.client.get("/api/b66/ai/dialogues", params={"q": "일반"})
    assert chat_only.status_code == 200
    assert chat_only.json()["conversations"] == []


def test_query_and_limit_bounds_are_enforced(env):
    _seed_b66(env, USER_A)
    assert env.client.get(
        "/api/b66/ai/dialogues", params={"q": "가" * 1000}
    ).status_code == 400
    assert env.client.get(
        "/api/b66/ai/dialogues", params={"limit": "9999"}
    ).status_code == 400
    assert env.client.get(
        "/api/b66/ai/dialogues", params={"limit": "0"}
    ).status_code == 400
    assert env.client.get(
        "/api/b66/ai/dialogues", params={"limit": "abc"}
    ).status_code == 400


# ── detail / delete isolation ────────────────────────────────────────────────
def test_same_owner_chat_conversation_is_neither_readable_nor_deletable_from_b66(env):
    chat_id = _seed_chat(env, USER_A)
    _sign_in(env.settings, env.client, USER_A)
    assert env.client.get(f"/api/b66/ai/dialogues/{chat_id}").status_code == 404
    assert env.client.delete(f"/api/b66/ai/dialogues/{chat_id}").status_code == 404

    import asyncio
    survived = asyncio.run(env.store.get_conversation(
        USER_A, chat_id, product_scope=PRODUCT_SCOPE_CHAT,
    ))
    assert survived is not None and len(survived["messages"]) == 2


def test_another_owner_cannot_read_or_delete_a_b66_dialogue(env):
    b66_id = _seed_b66(env, USER_A)
    _sign_in(env.settings, env.client, USER_B)
    assert env.client.get(f"/api/b66/ai/dialogues/{b66_id}").status_code == 404
    assert env.client.delete(f"/api/b66/ai/dialogues/{b66_id}").status_code == 404
    assert env.client.get("/api/b66/ai/dialogues").json()["conversations"] == []


def test_malformed_and_unknown_ids_are_the_same_bounded_404(env):
    _sign_in(env.settings, env.client, USER_A)
    for bad in ("not-a-conversation", "chat_short", "b66quote_" + "a" * 32,
                "chat_" + "a" * 32):
        assert env.client.get(f"/api/b66/ai/dialogues/{bad}").status_code == 404
        assert env.client.delete(f"/api/b66/ai/dialogues/{bad}").status_code == 404


def test_delete_removes_only_the_owners_b66_dialogue(env):
    b66_id = _seed_b66(env, USER_A)
    _sign_in(env.settings, env.client, USER_A)
    deleted = env.client.delete(f"/api/b66/ai/dialogues/{b66_id}")
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert env.client.get("/api/b66/ai/dialogues").json()["conversations"] == []
    assert env.client.get(f"/api/b66/ai/dialogues/{b66_id}").status_code == 404


# ── save / restore / continue ────────────────────────────────────────────────
def test_a_successful_b66_answer_is_saved_and_continuable(env):
    _sign_in(env.settings, env.client, USER_A)
    first = _chat(env.client, messages=[{"role": "user", "content": "철근 견적 알려줘"}])
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["dialogue_saved"] is True
    cid = body["conversation_id"]
    assert cid.startswith("chat_")

    restored = env.client.get(f"/api/b66/ai/dialogues/{cid}")
    assert restored.status_code == 200
    conversation = restored.json()["conversation"]
    assert conversation["conversation_id"] == cid
    assert [m["role"] for m in conversation["messages"]] == ["user", "assistant"]

    # Continue: the server uses its own stored history, not the browser array.
    continued = _chat(
        env.client,
        messages=[
            {"role": "user", "content": "철근 견적 알려줘"},
            {"role": "assistant", "content": body["answer"]},
            {"role": "user", "content": "부가세 포함으로 다시"},
        ],
        conversation_id=cid,
    )
    assert continued.status_code == 200, continued.text
    assert continued.json()["conversation_id"] == cid
    # The model saw the stored turn plus the new user turn, not the browser echo.
    assert env.model.calls[-1] == [
        {"role": "user", "content": "철근 견적 알려줘"},
        {"role": "assistant", "content": body["answer"]},
        {"role": "user", "content": "부가세 포함으로 다시"},
    ]
    after = env.client.get(f"/api/b66/ai/dialogues/{cid}").json()["conversation"]
    assert [m["role"] for m in after["messages"]] == ["user", "assistant", "user", "assistant"]


def test_a_browser_supplied_transcript_cannot_supersede_stored_history(env):
    _sign_in(env.settings, env.client, USER_A)
    cid = _seed_b66(env, USER_A, user_text="원래 저장된 질문", answer="원래 저장된 답변")
    forged = _chat(
        env.client,
        messages=[
            {"role": "user", "content": "조작된 과거 질문"},
            {"role": "assistant", "content": "조작된 과거 답변"},
            {"role": "user", "content": "새 질문"},
        ],
        conversation_id=cid,
    )
    assert forged.status_code == 200
    assert env.model.calls[-1] == [
        {"role": "user", "content": "원래 저장된 질문"},
        {"role": "assistant", "content": "원래 저장된 답변"},
        {"role": "user", "content": "새 질문"},
    ]


def test_a_same_owner_chat_id_cannot_be_continued_and_costs_no_model_call(env):
    _sign_in(env.settings, env.client, USER_A)
    chat_id = _seed_chat(env, USER_A)
    res = _chat(
        env.client,
        messages=[{"role": "user", "content": "이어쓰기 시도"}],
        conversation_id=chat_id,
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "conversation_not_found"
    assert env.resolver.calls == [] and env.model.calls == []


def test_an_unknown_or_foreign_id_is_refused_before_any_model_call(env):
    _sign_in(env.settings, env.client, USER_A)
    for cid in ("chat_" + "c" * 32, "not-a-conversation"):
        res = _chat(
            env.client,
            messages=[{"role": "user", "content": "질문"}],
            conversation_id=cid,
        )
        assert res.status_code in (400, 404), res.text
    assert env.resolver.calls == [] and env.model.calls == []


def test_a_failed_model_call_leaves_no_dialogue_record(env):
    _sign_in(env.settings, env.client, USER_A)
    env.model.fail = True
    res = _chat(env.client, messages=[{"role": "user", "content": "실패할 질문"}])
    assert res.status_code == 502
    assert env.client.get("/api/b66/ai/dialogues").json()["conversations"] == []


CONTINUATION = [
    {"role": "user", "content": "철근 견적 알려줘"},
    {"role": "assistant", "content": "네, 알려드릴게요"},
    {"role": "user", "content": "같은 요청"},
]


def _messages_of(env, conversation_id):
    return env.client.get(f"/api/b66/ai/dialogues/{conversation_id}").json()["conversation"]["messages"]


def test_a_replayed_turn_with_a_different_model_answer_is_not_appended(env):
    """A transport retry must reconcile before dispatch.

    The second call would produce *different* prose, so an implementation that
    compares assistant text for identity would append a second exchange here.
    """
    _sign_in(env.settings, env.client, USER_A)
    env.model.answers = ["네, 알려드릴게요", "첫 답변", "전혀 다른 두 번째 답변"]
    cid = _seed_b66(env, USER_A)

    first = _chat(env.client, messages=CONTINUATION, conversation_id=cid)
    assert first.status_code == 200
    assert first.json()["answer"] == "첫 답변"
    after_first = len(env.model.calls)
    assert after_first == 2, "seed turn + one dispatch"
    assert len(_messages_of(env, cid)) == 4

    # The identical request is replayed (same last user turn, browser behind).
    again = _chat(env.client, messages=CONTINUATION, conversation_id=cid)
    assert again.status_code == 200
    assert again.json()["conversation_id"] == cid
    assert again.json()["dialogue_replay"] is True
    assert again.json()["answer"] == "첫 답변", "the stored answer, never a new one"
    # No second paid dispatch, and no second exchange.
    assert len(env.model.calls) == after_first
    assert len(_messages_of(env, cid)) == 4
    assert _messages_of(env, cid)[-1]["content"] == "첫 답변"


def test_a_retried_first_turn_does_not_call_the_model_twice(env):
    """A first turn has no stored dialogue, so the retry identity is the token."""
    from app.b66_ai_chat_routes import reset_dialogue_idempotency

    _sign_in(env.settings, env.client, USER_A)
    reset_dialogue_idempotency()
    request = [{"role": "user", "content": "철근 견적 알려줘"}]
    token = "f" * 32
    env.model.answers = ["첫 답변", "전혀 다른 답변"]

    first = _chat(env.client, messages=request, turn_token=token)
    assert first.status_code == 200
    created = first.json()["conversation_id"]
    assert len(env.model.calls) == 1

    again = _chat(env.client, messages=request, turn_token=token)
    assert again.status_code == 200
    assert again.json()["conversation_id"] == created
    assert again.json()["answer"] == "첫 답변"
    assert len(env.model.calls) == 1
    listed = env.client.get("/api/b66/ai/dialogues").json()["conversations"]
    assert [row["conversation_id"] for row in listed] == [created]


def test_concurrent_duplicate_requests_append_one_exchange(env):
    """Two in-flight copies of the same turn must not both append or both charge."""
    import threading

    from app.b66_ai_chat_routes import reset_dialogue_idempotency

    _sign_in(env.settings, env.client, USER_A)
    env.model.answers = ["네, 알려드릴게요", "동시 답변", "다른 동시 답변"]
    cid = _seed_b66(env, USER_A)
    reset_dialogue_idempotency()
    env.model.delay = 0.15
    before = len(env.model.calls)

    results: list = []

    def post_duplicate():
        # One TestClient per thread: TestClient is not safe to share.
        results.append(_chat(
            _client_for(env), messages=CONTINUATION, conversation_id=cid
        ))

    workers = [threading.Thread(target=post_duplicate) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    assert all(res.status_code == 200 for res in results), [res.text for res in results]
    assert len(env.model.calls) == before + 1, "an accepted duplicate must not re-dispatch"
    assert len(_messages_of(env, cid)) == 4, "an accepted duplicate must not append a pair"
    assert _messages_of(env, cid)[-1]["content"] == "동시 답변"


def test_an_out_of_sync_client_is_refused_before_any_model_call(env):
    """A browser claiming turns the server never stored must not start a context."""
    _sign_in(env.settings, env.client, USER_A)
    cid = _seed_b66(env, USER_A)
    before = len(env.model.calls)
    # The browser claims turns the server never stored: refuse before dispatch.
    invented = CONTINUATION + [
        {"role": "assistant", "content": "서버에 없는 답변"},
        {"role": "user", "content": "서버에 없는 질문"},
    ]
    res = _chat(env.client, messages=invented, conversation_id=cid)
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "dialogue_out_of_sync"

    # Repeating the last recorded message with no new turns is ambiguous too.
    repeated = list(CONTINUATION)
    repeated[-1] = {"role": "user", "content": "철근 견적 알려줘"}
    res = _chat(env.client, messages=repeated, conversation_id=cid)
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "dialogue_turn_already_recorded"
    assert len(env.model.calls) == before
    assert len(_messages_of(env, cid)) == 2


def test_a_continued_dialogue_reaches_the_model_with_the_full_original(env):
    _sign_in(env.settings, env.client, USER_A)
    long_answer = "긴답변" * 3000 + "::ANSWER_TAIL"
    env.model.answer = long_answer
    first = _chat(env.client, messages=[{"role": "user", "content": "긴 답변 부탁"}])
    assert first.status_code == 200
    cid = first.json()["conversation_id"]
    assert env.bucket.objects, "the full original must be kept in private R2"

    # The D1 preview is bounded and marked; the model must not receive it.
    preview = env.client.get(f"/api/b66/ai/dialogues/{cid}").json()["conversation"]
    stored_answer = preview["messages"][1]["content"]
    assert len(stored_answer) == MAX_HISTORY_MESSAGE_CHARS
    assert stored_answer.endswith(HISTORY_PREVIEW_SUFFIX)

    continued = _chat(
        env.client,
        messages=[{"role": "user", "content": "다음 질문"}],
        conversation_id=cid,
    )
    assert continued.status_code == 200
    sent = env.model.calls[-1]
    assert sent[1]["content"] == long_answer
    assert "::ANSWER_TAIL" in sent[1]["content"]


def test_dialogue_history_is_unavailable_without_a_composed_store(env):
    # The routes fail closed when no B66 dialogue adapter is composed, instead
    # of exposing any conversation or falling back to a Chat-scoped read.
    _sign_in(env.settings, env.client, USER_A)
    env.app.state.b66_conversation_store = None
    res = env.client.get("/api/b66/ai/dialogues")
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "dialogue_history_unavailable"
import threading


def test_concurrent_first_turn_requests_share_one_conversation(env):
    """Two in-flight copies of one first turn charge once and share one id."""
    from app.b66_ai_chat_routes import reset_dialogue_idempotency

    reset_dialogue_idempotency()
    _sign_in(env.settings, env.client, USER_A)
    env.model.answers = ["첫 답변", "전혀 다른 답변"]
    env.model.delay = 0.15
    token = "f" * 32
    request = [{"role": "user", "content": "철근 견적 알려줘"}]
    before_calls = len(env.model.calls)
    results = []

    def post():
        results.append(_chat(_client_for(env), messages=request, turn_token=token))

    workers = [threading.Thread(target=post) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    assert all(res.status_code == 200 for res in results), [res.text for res in results]
    assert len(env.model.calls) == before_calls + 1
    assert len({res.json()["conversation_id"] for res in results}) == 1
    assert all(res.json()["answer"] == "첫 답변" for res in results)
    listed = env.client.get("/api/b66/ai/dialogues").json()["conversations"]
    assert len(listed) == 1


def test_concurrent_same_conversation_slow_model_is_refused_without_redispatch(env):
    """An overlapping duplicate that outlasts the bounded wait refuses safely."""
    from app.b66_ai_chat_routes import reset_dialogue_idempotency

    reset_dialogue_idempotency()
    _sign_in(env.settings, env.client, USER_A)
    env.model.answers = ["네, 알려드릴게요", "동시 답변", "다른 동시 답변"]
    cid = _seed_b66(env, USER_A)
    reset_dialogue_idempotency()
    env.model.delay = 5.0
    before = len(env.model.calls)
    results = []

    def post():
        results.append(_chat(_client_for(env), messages=CONTINUATION, conversation_id=cid))

    workers = [threading.Thread(target=post) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=30)

    assert sorted(res.status_code for res in results) == [200, 409], [res.text for res in results]
    timeout_result = next(res for res in results if res.status_code == 409)
    assert timeout_result.json()["error"]["code"] == "dialogue_turn_in_progress"
    assert len(env.model.calls) == before + 1
    assert len(env.client.get(f"/api/b66/ai/dialogues/{cid}").json()["conversation"]["messages"]) == 4
