"""#4672: actual D1 SQL backed by SQLite; no model/provider network I/O."""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.b66_durable_turn_attempt import (
    D1B66TurnAttemptStore, attempt_request_digest,
)
from app.b66_ai_chat_routes import reset_dialogue_idempotency
from test_b66_dialogue_history_4657 import MODEL, USER_A, _D1, _chat, _client_for, _sign_in, env

TOKEN = "abcdef0123456789abcdef0123456789"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "044_b66_ai_turn_attempt.sql"


def _wire(env):
    _sign_in(env.settings, env.client, USER_A)
    env.db.executescript(MIGRATION.read_text(encoding="utf-8"))
    env.app.state.b66_turn_attempt_store = D1B66TurnAttemptStore(_D1(env.db))
    reset_dialogue_idempotency()
    return env.app.state.b66_turn_attempt_store


def test_migration_atomic_unique_owner_product_token(tmp_path):
    dbpath = str(tmp_path / "attempt.db")
    a, b = (sqlite3.connect(dbpath, isolation_level=None) for _ in range(2))
    a.row_factory = sqlite3.Row
    b.row_factory = sqlite3.Row
    try:
        a.execute("PRAGMA journal_mode=WAL")
        a.execute("CREATE TABLE users(id TEXT PRIMARY KEY)")
        a.execute("INSERT INTO users VALUES ('owner-a')")
        a.execute("INSERT INTO users VALUES ('owner-b')")
        a.commit()
        a.executescript(MIGRATION.read_text(encoding="utf-8"))
        a.commit()
        b.execute("PRAGMA busy_timeout=1500")
        x, y = D1B66TurnAttemptStore(_D1(a)), D1B66TurnAttemptStore(_D1(b))
        digest = attempt_request_digest(
            model_id=MODEL, conversation_id=None,
            messages=[{"role": "user", "content": "첫 질문"}],
            model_parameters=None,
        )
        async def claim_twice():
            first = await x.claim("owner-a", TOKEN, MODEL, digest)
            second = await y.claim("owner-a", TOKEN, MODEL, digest)
            another = await y.claim("owner-b", TOKEN, MODEL, digest)
            return first, second, another
        first, second, other = asyncio.run(claim_twice())
        assert [first["status"], second["status"], other["status"]] == [
            "claimed", "in_progress", "claimed",
        ]
        assert a.execute("SELECT COUNT(*) FROM b66_ai_turn_attempt").fetchone()[0] == 2
    finally:
        a.close()
        b.close()


def test_real_http_no_schema_fails_before_paid_model(env):
    _sign_in(env.settings, env.client, USER_A)
    env.app.state.b66_turn_attempt_store = D1B66TurnAttemptStore(_D1(env.db))
    request = [{"role": "user", "content": "한 품목 견적"}]
    response = _chat(env.client, messages=request, turn_token=TOKEN)
    assert response.status_code == 503
    assert response.json()["code"] == "dialogue_attempt_unavailable"
    assert env.model.calls == []


def test_real_http_missing_token_refused_before_paid_model(env):
    _wire(env)
    response = _chat(env.client, messages=[{"role": "user", "content": "견적"}])
    assert response.status_code == 400
    assert response.json()["code"] == "turn_token_required"
    assert env.model.calls == []


def test_real_http_persisted_receipt_replays_after_isolate_reset(env):
    _wire(env)
    request = [{"role": "user", "content": "한 품목 견적"}]
    first = _chat(env.client, messages=request, turn_token=TOKEN)
    assert first.status_code == 200, first.text
    reset_dialogue_idempotency()
    second = _chat(env.client, messages=request, turn_token=TOKEN)
    assert second.status_code == 200, second.text
    assert second.json()["dialogue_replay"] is True
    assert second.json()["conversation_id"] == first.json()["conversation_id"]
    assert len(env.model.calls) == 1
    assert env.db.execute(
        "SELECT state FROM b66_ai_turn_attempt WHERE turn_token=?", (TOKEN,)
    ).fetchone()[0] == "completed"


def test_claim_mismatch_cannot_reuse_paid_token(env):
    _wire(env)
    first = _chat(env.client, messages=[{"role": "user", "content": "철근"}], turn_token=TOKEN)
    assert first.status_code == 200
    reset_dialogue_idempotency()
    second = _chat(env.client, messages=[{"role": "user", "content": "콘크리트"}], turn_token=TOKEN)
    assert second.status_code == 409
    assert second.json()["code"] == "dialogue_attempt_mismatch"
    assert len(env.model.calls) == 1


def test_uncertain_provider_failure_never_auto_reclaims_claim(env):
    _wire(env)
    env.model.fail = True
    req = [{"role": "user", "content": "철근"}]
    response = _chat(env.client, messages=req, turn_token=TOKEN)
    assert response.status_code == 502
    assert len(env.model.calls) == 1
    reset_dialogue_idempotency()
    env.model.fail = False
    retry = _chat(env.client, messages=req, turn_token=TOKEN)
    assert retry.status_code == 409
    assert retry.json()["code"] == "dialogue_turn_in_progress"
    assert len(env.model.calls) == 1


def test_parallel_isolate_memory_reset_still_single_paid_dispatch(env):
    _wire(env)
    env.model.delay = .15
    req = [{"role": "user", "content": "철근 첫 대화"}]
    import threading
    from concurrent.futures import ThreadPoolExecutor

    started = threading.Event()
    original = env.model.complete_registered_b66_chat_model

    async def slow(*args, **kwargs):
        started.set()
        return await original(*args, **kwargs)

    env.model.complete_registered_b66_chat_model = slow

    def send():
        return _chat(_client_for(env), messages=req, turn_token=TOKEN)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send)
        assert started.wait(timeout=5)
        # Simulate another isolate which has no visibility into in-memory
        # single-flight tokens. The persisted claim remains the only authority.
        reset_dialogue_idempotency()
        second = pool.submit(send).result(timeout=10)
        original_reply = first.result(timeout=10)
    assert original_reply.status_code == 200
    assert second.status_code == 409
    assert len(env.model.calls) == 1
