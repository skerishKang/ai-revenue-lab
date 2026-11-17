from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.byok_client import CustomProviderError, complete_owner_custom
from app.byok_usage import D1ByokUsageStore
from app.config import Settings
from app.request_contract import CustomModelSelection
from test_b66_ai_conversation_4466 import SQLiteD1

FAKE_KEY = "fake-" + "k" * 28
PROVIDER = "openai"
MODEL = "gpt-4.1-mini"
UID = "usr_" + "9" * 32
CID = "chat_" + "8" * 32
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class _CredentialStore:
    async def credential(self, user_id, provider_id):
        return FAKE_KEY, "https://provider.example.test"


class _Client:
    def __init__(self, *, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.calls = 0

    async def complete(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.answer


class _Gate:
    def __init__(self, *, allowed=True, code="fake_cap", status_code=429):
        self.allowed = allowed
        self.code = code
        self.status_code = status_code
        self.calls = 0

    async def authorize(self, *, raw_ip, user_id):
        self.calls += 1
        return SimpleNamespace(
            allowed=self.allowed,
            code=None if self.allowed else self.code,
            status_code=200 if self.allowed else self.status_code,
            user_message=None if self.allowed else "fake cap denial",
        )


def _state(client, gate):
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.row_factory = sqlite3.Row
    from app.local_cpython import apply_migrations

    apply_migrations(db, MIGRATIONS)
    settings = Settings.from_values(runtime_mode="mock")
    return SimpleNamespace(
        settings=settings,
        account_data_db=SQLiteD1(db),
        byok_usage_store=D1ByokUsageStore(SQLiteD1(db)),
        custom_credential_store=_CredentialStore(),
        custom_provider_client=client,
        usage_gate=gate,
    ), db


def _rows(db):
    return [
        dict(row)
        for row in db.execute(
            "SELECT * FROM byok_call_usage ORDER BY id"
        ).fetchall()
    ]


async def _call(state, selection=None):
    return await complete_owner_custom(
        state,
        uid=UID,
        selection=selection or CustomModelSelection(PROVIDER, MODEL),
        messages=[{"role": "user", "content": "fake prompt"}],
        conversation_id=CID,
    )


async def test_success_records_one_row_without_key(caplog):
    client = _Client(answer={"answer": "fake answer", "usage": {
        "input_tokens": 7, "output_tokens": 3,
    }})
    state, db = _state(client, _Gate())
    result = await _call(state)
    rows = _rows(db)
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == UID
    assert row["conversation_id"] == CID
    assert row["provider_id"] == PROVIDER
    assert row["model_id"] == MODEL
    assert row["credential_slot"] == PROVIDER
    assert row["is_byok"] == 1
    assert row["success"] == 1
    assert row["cap_decision"] == "allowed"
    assert row["input_tokens"] == 7
    assert row["output_tokens"] == 3
    assert row["char_count"] == len("fake answer")
    blob = json.dumps(result, ensure_ascii=False) + json.dumps(rows, ensure_ascii=False) + caplog.text
    assert FAKE_KEY not in blob
    db.close()


async def test_failure_records_one_row_without_key(caplog):
    error = CustomProviderError(502, "fake_provider_code", "fake provider failure")
    client = _Client(error=error)
    state, db = _state(client, _Gate())
    with pytest.raises(CustomProviderError) as info:
        await _call(state)
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["success"] == 0
    assert rows[0]["error_code"] == "fake_provider_code"
    assert rows[0]["char_count"] == 0
    blob = str(info.value) + json.dumps(rows, ensure_ascii=False) + caplog.text
    assert FAKE_KEY not in blob
    db.close()


async def test_cap_denial_records_one_row_and_skips_provider(caplog):
    client = _Client()
    state, db = _state(client, _Gate(allowed=False))
    with pytest.raises(CustomProviderError) as info:
        await _call(state)
    rows = _rows(db)
    assert client.calls == 0
    assert len(rows) == 1
    assert rows[0]["success"] == 0
    assert rows[0]["cap_decision"] == "denied"
    assert rows[0]["error_code"] == "fake_cap"
    blob = str(info.value) + json.dumps(rows, ensure_ascii=False) + caplog.text
    assert FAKE_KEY not in blob
    db.close()


async def test_b66_default_call_records_one_row_without_key(caplog):
    client = _Client(answer={"answer": "fake b66 answer"})
    state, db = _state(client, _Gate())
    result = await complete_owner_custom(
        state,
        uid=UID,
        selection=CustomModelSelection(PROVIDER, MODEL),
        messages=[{"role": "user", "content": "fake b66 prompt"}],
    )
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["conversation_id"] is None
    assert rows[0]["credential_slot"] == PROVIDER
    assert "fake b66 answer" in result["answer"]
    blob = json.dumps(result, ensure_ascii=False) + json.dumps(rows, ensure_ascii=False) + caplog.text
    assert FAKE_KEY not in blob
    db.close()


def test_usage_table_has_no_ip_column():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    from app.local_cpython import apply_migrations

    apply_migrations(db, MIGRATIONS)
    columns = [row["name"] for row in db.execute("PRAGMA table_info(byok_call_usage)").fetchall()]
    assert "raw_ip" not in columns
    assert "ip" not in columns
    db.close()
