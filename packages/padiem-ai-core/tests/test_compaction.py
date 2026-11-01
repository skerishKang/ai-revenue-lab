import pytest

from padiem_ai_core.compaction import HEADINGS, compact, needs_compaction


def msg(id, role, content):
    return {"id": id, "role": role, "content": content}


def summary(messages, prompt):
    assert all(item["role"] != "user" for item in messages)
    assert all(heading in prompt for heading in HEADINGS)
    return "\n".join(f"## {heading}\n- 기록" for heading in HEADINGS)


def test_budget_and_invalid_budget():
    messages = [msg("1", "user", "한글 test")]
    assert not needs_compaction(messages, 1000)
    assert needs_compaction(messages, 1)
    with pytest.raises(ValueError):
        needs_compaction(messages, 0)


def test_compact_preserves_users_recent_tail_roles_and_ids():
    messages = [msg("u1", "user", "원문 지시"), msg("a1", "assistant", "첫 답"),
                msg("t1", "tool_result", "도구 결과"), msg("u2", "user", "두 번째"),
                msg("a2", "assistant", "최근 답"), msg("t2", "tool_result", "최근 도구")]
    seen = []
    def summarize(older, prompt):
        seen.extend(older)
        return summary(older, prompt)
    result = compact(messages, summarize, keep_recent=2)
    assert result["kept"] == [messages[0], messages[3], messages[4], messages[5]]
    assert [m["role"] for m in result["kept"]] == ["user", "user", "assistant", "tool_result"]
    assert result["dropped_ids"] == ["a1", "t1"]
    assert seen == [messages[1], messages[2]]
    assert all("## " + heading in result["summary"] for heading in HEADINGS)
    assert messages[0]["content"] == "원문 지시"


def test_no_droppable_messages_do_not_call_summarizer():
    messages = [msg("1", "user", "보존")]
    result = compact(messages, lambda *_: pytest.fail("must not summarize user"), keep_recent=0)
    assert result["kept"] == messages and result["dropped_ids"] == []


def test_rejects_incomplete_summary_and_untracked_removed_ids():
    with pytest.raises(ValueError, match="four headings"):
        compact([msg("1", "assistant", "x")], lambda *_: "incomplete", keep_recent=0)
    with pytest.raises(ValueError, match="unique"):
        compact([{"role": "assistant", "content": "x"}], summary, keep_recent=0)
