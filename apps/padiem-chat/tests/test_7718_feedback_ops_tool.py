"""#7718 ops tool: bounded preview/apply output and root-only gate."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "feedback_ops.py"
SPEC = importlib.util.spec_from_file_location("feedback_ops_7718", TOOL_PATH)
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

ID = "fb_" + "a" * 32
BODY = "private-feedback-body"
REPLY = "private-operator-reply"


class FakeStore:
    def __init__(self, record=None):
        self.record = record if record is not None else SimpleNamespace(status="new")
        self.status_writes = []
        self.replies = []
        self.get_calls = 0

    async def get_record(self, feedback_id, **kwargs):
        self.get_calls += 1
        return self.record

    async def set_status(self, feedback_id, status):
        self.status_writes.append((feedback_id, status))
        self.record = SimpleNamespace(status=status)
        return self.record

    async def add_reply(self, feedback_id, side, body, **kwargs):
        self.replies.append((feedback_id, side, body, kwargs))
        return SimpleNamespace(side=side)


def test_preview_does_not_write_and_never_prints_values():
    store = FakeStore()
    result = asyncio.run(TOOL.run_feedback(store, ID, status="fixed"))
    assert store.status_writes == [] and store.replies == []
    assert result["lines"] == [f"feedback={ID}", "status=new", "ok=true"]
    assert BODY not in result["lines"] and REPLY not in result["lines"]


def test_apply_writes_status_and_reply_without_echoing_reply():
    store = FakeStore()
    result = asyncio.run(TOOL.run_feedback(store, ID, status="fixed", reply=REPLY, apply=True))
    assert store.status_writes == [(ID, "fixed")]
    assert store.replies == [(ID, "ops", REPLY, {})]
    assert result["lines"] == [f"feedback={ID}", "status=fixed", "ok=true"]
    assert REPLY not in result["lines"] and BODY not in result["lines"]


def test_not_found_and_invalid_inputs_are_bounded():
    missing_store = FakeStore()
    missing_store.record = None
    missing = asyncio.run(TOOL.run_feedback(missing_store, ID, status="fixed"))
    assert missing["error"] == "FEEDBACK_NOT_FOUND"
    for kwargs in ({"status": "wrong"}, {"reply": ""}, {"reply": "x" * 4001}):
        with pytest.raises(TOOL.ToolError):
            asyncio.run(TOOL.run_feedback(FakeStore(), ID, **kwargs))
    with pytest.raises(TOOL.ToolError):
        asyncio.run(TOOL.run_feedback(FakeStore(), "bad", status="fixed"))


def test_main_requires_root_before_loading_state(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(TOOL, "_assert_root", lambda: (_ for _ in ()).throw(TOOL.ToolError("ROOT_REQUIRED")))
    monkeypatch.setattr(TOOL, "_load_state", lambda: calls.append("state"))
    assert TOOL.main(["--feedback-id", ID, "--status", "fixed"]) == 1
    assert "STOP ROOT_REQUIRED" in capsys.readouterr().out
    assert calls == []


def test_main_preview_and_apply_are_bounded(monkeypatch, capsys):
    store = FakeStore()
    monkeypatch.setattr(TOOL, "_assert_root", lambda: None)
    monkeypatch.setattr(TOOL, "_load_env_file", lambda path: None)
    monkeypatch.setattr(TOOL, "_use_deployed_tree", lambda: False)
    monkeypatch.setattr(TOOL, "_become_service_user", lambda: None)
    monkeypatch.setattr(TOOL, "_load_state", lambda: store)
    assert TOOL.main(["--feedback-id", ID, "--status", "fixed"]) == 0
    assert store.status_writes == [] and store.replies == []
    assert TOOL.main(["--feedback-id", ID, "--status", "fixed", "--reply", REPLY, "--apply"]) == 0
    assert store.status_writes == [(ID, "fixed")] and len(store.replies) == 1
    output = capsys.readouterr().out
    assert f"feedback={ID}" in output and "status=fixed" in output and "ok=true" in output
    assert REPLY not in output and BODY not in output