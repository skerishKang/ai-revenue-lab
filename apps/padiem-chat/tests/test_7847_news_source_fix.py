"""#7847 follow-up — correcting a published news item's source only.

The tool uses the store's own update path; preview writes nothing and the
identity, title, detail and date of the item are never part of the request.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_7718_chat_news import news_database

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("news_source_fix", ROOT / "tools" / "chat_news_publish.py")
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


def _record(number=9, source="ai_tester"):
    return SimpleNamespace(
        number=number, kind="improved", title="새 소식 제목", detail="새 소식 설명",
        source=source, published_at="2026-11-18T08:30:00.000Z", version="2026.11.18",
    )


class FakeNewsStore:
    def __init__(self, record=None):
        self.record = record if record is not None else _record()
        self.updates = []
        self.gets = []

    async def get(self, number):
        self.gets.append(number)
        return self.record if number == self.record.number else None

    async def update_source(self, number, source):
        self.updates.append((number, source))
        if self.record is None or number != self.record.number:
            return None
        self.record = SimpleNamespace(**{**vars(self.record), "source": source})
        return self.record


def test_dry_run_reads_the_item_but_writes_nothing():
    store = FakeNewsStore()
    result = asyncio.run(TOOL.run_fix_source(store, number=9, source="none"))
    assert store.gets == [9] and store.updates == []
    assert result["error"] is None and result["lines"][-1] == "ok=true"
    assert "source_before=ai_tester" in result["lines"]
    assert "source_after=none" in result["lines"]
    assert "version=2026.11.18" in result["lines"]
    assert "title=새 소식 제목" in result["lines"]


def test_apply_changes_only_the_source():
    store = FakeNewsStore()
    result = asyncio.run(TOOL.run_fix_source(store, number=9, source="none", apply=True))
    assert result["error"] is None
    assert store.updates == [(9, "none")]
    record = store.record
    assert record.source == "none"
    assert (record.number, record.kind, record.title, record.detail,
            record.version, record.published_at) == (
        9, "improved", "새 소식 제목", "새 소식 설명", "2026.11.18",
        "2026-11-18T08:30:00.000Z")


@pytest.mark.parametrize("source", ("team", "user ", "", "AI_TESTER", None, 1))
def test_source_outside_the_known_list_is_refused(source):
    store = FakeNewsStore()
    with pytest.raises(TOOL.ToolError) as caught:
        asyncio.run(TOOL.run_fix_source(store, number=9, source=source))
    assert caught.value.code == "NEWS_SOURCE_INVALID"
    assert store.updates == []


@pytest.mark.parametrize("number", (0, -1, "9", None, 1.5))
def test_invalid_item_number_is_refused(number):
    store = FakeNewsStore()
    with pytest.raises(TOOL.ToolError) as caught:
        asyncio.run(TOOL.run_fix_source(store, number=number, source="none"))
    assert caught.value.code == "NEWS_NUMBER_INVALID"
    assert store.updates == []


def test_missing_item_is_reported_without_a_write():
    store = FakeNewsStore()
    result = asyncio.run(TOOL.run_fix_source(store, number=11, source="none", apply=True))
    assert result["error"] == "NEWS_NOT_FOUND"
    assert store.updates == []


def test_refusing_store_reports_no_write_progress():
    class Refusing(FakeNewsStore):
        async def update_source(self, number, source):
            return None
    result = asyncio.run(TOOL.run_fix_source(Refusing(), number=9, source="none", apply=True))
    assert result["error"] == "NEWS_STORE_REFUSED"


def test_store_update_source_changes_only_the_source_column():
    _db, _feedback, news = news_database()
    created = asyncio.run(news.create(
        "improved", "새 소식 제목", "새 소식 설명", "ai_tester", "2026.11.18"))
    before = asyncio.run(news.get(created.number))
    updated = asyncio.run(news.update_source(created.number, "none"))
    after = asyncio.run(news.get(created.number))
    assert updated.source == "none" and after.source == "none"
    for field in ("number", "kind", "title", "detail", "published_at", "version"):
        assert getattr(before, field) == getattr(after, field), field
    with pytest.raises(ValueError):
        asyncio.run(news.update_source(created.number, "team"))


def test_main_fix_mode_preview_uses_com2_conventions_only_for_apply(monkeypatch, capsys):
    calls = []
    for name, value in (("_assert_root", lambda: calls.append("root")),
                        ("_load_env_file", lambda path: calls.append("env")),
                        ("_use_deployed_tree", lambda: calls.append("tree")),
                        ("_become_service_user", lambda: calls.append("user"))):
        monkeypatch.setattr(TOOL, name, value)
    monkeypatch.setattr(TOOL, "_load_state",
                        lambda: SimpleNamespace(news_store=FakeNewsStore()))
    preview = TOOL.main(["--fix-source", "9", "--source", "none"])
    out = capsys.readouterr().out
    assert preview == 0 and calls == ["root", "env", "tree", "user"]
    assert "source_before=ai_tester" in out and "source_after=none" in out and "ok=true" in out
    calls.clear()
    applied = TOOL.main(["--fix-source", "9", "--source", "none", "--apply"])
    assert applied == 0 and len(calls) == 4
    assert "news=9" in capsys.readouterr().out
