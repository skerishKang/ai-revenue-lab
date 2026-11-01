import os
import time

import pytest

from padiem_ai_core import output_store
from padiem_ai_core.output_store import OutputStore


def test_store_retains_full_output_and_returns_hermes_preview(tmp_path):
    store = OutputStore(tmp_path, preview_chars=10)
    result = store.store("0123456789abcdef", owner="alice", source="command")
    assert result == {"handle": result["handle"], "size": 16, "head": "0123",
                      "tail": "abcdef", "truncated": True}
    assert store.read(result["handle"], owner="alice", offset=0, length=100) == "0123456789abcdef"
    short = store.store("짧음", owner="alice", source="command")
    assert (short["size"], short["head"], short["tail"], short["truncated"]) == (6, "짧음", "", False)


def test_read_byte_ranges_at_utf8_boundaries(tmp_path):
    store = OutputStore(tmp_path)
    handle = store.store("A한글B", owner="alice", source="command")["handle"]
    assert store.read(handle, owner="alice", offset=0, length=8) == "A한글B"
    assert store.read(handle, owner="alice", offset=2, length=5) == "글"
    assert store.read(handle, owner="alice", offset=1, length=2) == ""
    assert store.read(handle, owner="alice", offset=4, length=3) == "글"


def test_search_reports_byte_offsets_and_limits(tmp_path):
    store = OutputStore(tmp_path)
    handle = store.store("한글 찾기\n찾기 또 찾기\n", owner="alice", source="command")["handle"]
    assert store.search(handle, owner="alice", pattern="찾기", max_hits=2) == [
        {"offset": 7, "line": "한글 찾기"},
        {"offset": 14, "line": "찾기 또 찾기"},
    ]
    assert store.search(handle, owner="alice", pattern="없음", max_hits=1) == []
    assert store.search(handle, owner="alice", pattern="찾기", max_hits=0) == []


def test_wrong_owner_cannot_read_or_search(tmp_path):
    store = OutputStore(tmp_path)
    handle = store.store("secret", owner="alice", source="command")["handle"]
    with pytest.raises(FileNotFoundError):
        store.read(handle, owner="bob", offset=0, length=10)
    with pytest.raises(FileNotFoundError):
        store.search(handle, owner="bob", pattern="secret", max_hits=1)


def test_expired_output_is_removed_on_next_operation(tmp_path):
    now = time.time()
    store = OutputStore(tmp_path, retention_seconds=60, clock=lambda: now)
    old = store.store("old", owner="alice", source="command")["handle"]
    old_path = store._path(old, "alice")
    os.utime(old_path, (now - 61, now - 61))
    fresh = store.store("new", owner="alice", source="command")["handle"]
    assert not old_path.exists()
    assert not old_path.with_suffix(".json").exists()
    assert store.read(fresh, owner="alice", offset=0, length=10) == "new"


def test_module_interface_uses_configured_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("PADIEM_OUTPUT_STORE_DIR", str(tmp_path))
    result = output_store.store(b"test", owner="alice", source="command")
    assert output_store.read(result["handle"], owner="alice", offset=0, length=4) == "test"
    assert output_store.search(result["handle"], owner="alice", pattern="test", max_hits=1)[0]["offset"] == 0
