import pytest

from padiem_ai_core.compaction import HEADINGS, CompactionStore, compact, needs_compaction


def msg(id, role, content):
    return {"id": id, "role": role, "content": content}


def summary(messages, prompt):
    assert all(m["role"] != "user" for m in messages)
    return {"items": [{"section": heading, "text": "item " + str(i),
                       "source_ids": [messages[i % len(messages)]["id"]]}
                      for i, heading in enumerate(HEADINGS)]}


def test_budget():
    assert not needs_compaction([msg("1", "user", "한글")], 1000)
    assert needs_compaction([msg("1", "user", "한글")], 1)
    with pytest.raises(ValueError):
        needs_compaction([], 0)


def test_each_summary_item_has_sources_and_recall_survives_restart(tmp_path):
    path = tmp_path / "archive.sqlite"
    store = CompactionStore(path)
    messages = [msg("u", "user", "원문 사용자"), msg("a", "assistant", "old answer"),
                msg("t", "tool_result", "old tool"), msg("r", "assistant", "recent")]
    result = compact(messages, summary, 1, owner="alice", store=store)
    assert result["kept"] == [messages[0], messages[-1]]
    assert result["dropped_ids"] == ["a", "t"]
    assert [item["source_ids"] for item in result["summary"]["items"]] == [
        ["a"], ["t"], ["a"], ["t"]]
    assert all("## " + heading in result["summary"]["text"] for heading in HEADINGS)
    store.close()
    reopened = CompactionStore(path)
    assert reopened.recall(["t", "a"], owner="alice") == [messages[2], messages[1]]
    with pytest.raises(PermissionError):
        reopened.recall(["a"], owner="bob")
    reopened.close()


def test_repeated_compaction_keeps_original_sources(tmp_path):
    store = CompactionStore(tmp_path / "archive.sqlite")
    original = msg("first", "assistant", "original")
    first = compact([original], summary, 0, owner="alice", store=store)
    checkpoint = {"id": "checkpoint", "role": "assistant",
                  "content": first["summary"]["text"],
                  "summary_items": first["summary"]["items"]}
    second = compact([checkpoint], summary, 0, owner="alice", store=store)
    assert all(item["source_ids"] == ["first"] for item in second["summary"]["items"])
    assert store.recall(["first"], owner="alice") == [original]
    with pytest.raises(PermissionError):
        compact([checkpoint], summary, 0, owner="bob", store=store)


def test_rejects_fabricated_sources_and_partial_summary(tmp_path):
    store = CompactionStore(tmp_path / "archive.sqlite")
    source = [msg("a", "assistant", "fact")]
    def bad(messages, prompt):
        return {"items": [{"section": h, "text": "x", "source_ids": ["unknown"]} for h in HEADINGS]}
    with pytest.raises(ValueError, match="input message"):
        compact(source, bad, 0, owner="alice", store=store)
    with pytest.raises(PermissionError):
        store.recall(["a"], owner="alice")
    with pytest.raises(ValueError, match="four sections"):
        compact(source, lambda *_: {"items": [{"section": HEADINGS[0], "text": "x",
                                                "source_ids": ["a"]}]},
                0, owner="alice", store=store)


def test_no_summarizer_call_when_only_user(tmp_path):
    store = CompactionStore(tmp_path / "archive.sqlite")
    m = msg("u", "user", "keep")
    result = compact([m], lambda *_: pytest.fail("called"), 0, owner="alice", store=store)
    assert result["kept"] == [m] and result["dropped_ids"] == []


def test_immutable_source_and_owner_isolation(tmp_path):
    store = CompactionStore(tmp_path / "archive.sqlite")
    store.save([msg("a", "assistant", "first")], owner="alice")
    with pytest.raises(ValueError):
        store.save([msg("a", "assistant", "changed")], owner="alice")
    store.save([msg("a", "assistant", "other")], owner="bob")
    assert store.recall(["a"], owner="alice")[0]["content"] == "first"
    assert store.recall(["a"], owner="bob")[0]["content"] == "other"
