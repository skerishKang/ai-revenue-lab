"""#5318 slice A: durable model call records (storage).

Network-free D1 store tests using a SQLite-backed D1 substitute. No browser
or provider call is involved.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.model_call_record_store import (
    D1ModelCallRecordStore,
    ModelCallRecordInput,
)

MIGRATIONS = ("067_model_call_records.sql",)


class Statement:
    def __init__(self, conn, query):
        self.conn = conn
        self.query = query
        self.parameters = ()

    def bind(self, *values):
        self.parameters = values
        return self

    async def run(self):
        self.conn.execute(self.query, self.parameters)
        self.conn.commit()
        return _Result([])

    async def all(self):
        cur = self.conn.execute(self.query, self.parameters)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        self.conn.commit()
        return _Result(rows)


class _Result:
    def __init__(self, rows):
        self.results = rows


class SQLiteD1:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        for name in MIGRATIONS:
            self.conn.executescript((migrations / name).read_text(encoding="utf-8"))

    def prepare(self, query):
        return Statement(self.conn, query)


def test_record_persists_and_round_trips():
    store = D1ModelCallRecordStore(SQLiteD1())

    async def run():
        rec = await store.record(
            ModelCallRecordInput(
                product="chat",
                provider_id="openai",
                model_id="gpt-4o",
                status="success",
                user_id="usr_" + "a" * 32,
                duration_ms=120,
                input_tokens=10,
                output_tokens=20,
                cost_usd=0.001,
            )
        )
        assert rec.id.startswith("mc_")
        assert rec.product == "chat"
        assert rec.status == "success"
        assert rec.duration_ms == 120
        recent = await store.list_recent(product="chat", limit=10)
        assert len(recent) == 1
        assert recent[0].id == rec.id
        assert recent[0].input_tokens == 10
        assert recent[0].output_tokens == 20

    asyncio.run(run())


def test_record_rejects_invalid_product():
    store = D1ModelCallRecordStore(SQLiteD1())

    async def run():
        with pytest.raises(ValueError):
            await store.record(
                ModelCallRecordInput(
                    product="bogus",
                    provider_id="openai",
                    model_id="gpt-4o",
                    status="success",
                )
            )

    asyncio.run(run())


def test_list_recent_filters_by_product():
    store = D1ModelCallRecordStore(SQLiteD1())

    async def run():
        await store.record(ModelCallRecordInput(product="chat", provider_id="openai", model_id="gpt-4o", status="success"))
        await store.record(ModelCallRecordInput(product="claw", provider_id="openai", model_id="gpt-4o", status="success"))
        chat = await store.list_recent(product="chat", limit=10)
        all_rows = await store.list_recent(limit=10)
        assert len(chat) == 1
        assert len(all_rows) == 2

    asyncio.run(run())


def test_count_by_provider_aggregates():
    store = D1ModelCallRecordStore(SQLiteD1())

    async def run():
        await store.record(ModelCallRecordInput(product="chat", provider_id="openai", model_id="gpt-4o", status="success", input_tokens=5, output_tokens=7, cost_usd=0.01))
        await store.record(ModelCallRecordInput(product="chat", provider_id="openai", model_id="gpt-4o", status="error", error_code="timeout"))
        counts = await store.count_by_provider()
        assert len(counts) == 1
        assert counts[0]["call_count"] == 2
        assert counts[0]["success_count"] == 1

    asyncio.run(run())


def test_store_fails_closed_without_binding():
    with pytest.raises(ValueError):
        D1ModelCallRecordStore(None)
