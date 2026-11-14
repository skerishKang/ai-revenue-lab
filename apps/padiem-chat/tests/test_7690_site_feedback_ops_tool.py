"""#7690 ops tool: site feedback status/memo, no reply, no echoed body/memo."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOL_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'feedback_ops.py'
SPEC = importlib.util.spec_from_file_location('feedback_ops_7690', TOOL_PATH)
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)
SITE_ID = 'sf_' + 'a' * 32


class FakeSite:
    def __init__(self):
        self.record = SimpleNamespace(site='miraen-home', status='new', ops_memo=None)
        self.status = []
        self.memo = []

    async def get_record(self, feedback_id):
        return self.record

    async def set_status(self, feedback_id, status):
        self.status.append((feedback_id, status))
        self.record = SimpleNamespace(site=self.record.site, status=status, ops_memo=self.record.ops_memo)
        return self.record

    async def set_ops_memo(self, feedback_id, memo):
        self.memo.append((feedback_id, memo))
        self.record = SimpleNamespace(site=self.record.site, status=self.record.status, ops_memo=memo)
        return self.record


def test_site_preview_and_apply_do_not_echo_body_or_memo():
    store = FakeSite()
    preview = asyncio.run(TOOL.run_feedback(store, SITE_ID, status='fixed', memo='memo-text'))
    assert store.status == [] and store.memo == []
    assert preview['lines'][:3] == [f'feedback={SITE_ID}', 'site=miraen-home', 'status=new']
    assert 'memo=unset' in preview['lines'] and 'ok=true' in preview['lines']
    assert 'memo-text' not in preview['lines']
    applied = asyncio.run(TOOL.run_feedback(store, SITE_ID, status='fixed', memo='memo-text', apply=True))
    assert store.status == [(SITE_ID, 'fixed')] and store.memo == [(SITE_ID, 'memo-text')]
    assert 'memo=set' in applied['lines'] and 'memo-text' not in applied['lines']


def test_site_rejects_reply_ai_and_invalid_memo():
    store = FakeSite()
    for kwargs in ({'reply': 'x'}, {'ai_tester': True}, {'memo': 'x' * 2001}):
        with pytest.raises(TOOL.ToolError):
            asyncio.run(TOOL.run_feedback(store, SITE_ID, **kwargs))
    with pytest.raises(TOOL.ToolError):
        asyncio.run(TOOL.run_feedback(store, SITE_ID))


def test_main_site_selects_site_store(monkeypatch, capsys):
    store = FakeSite()
    monkeypatch.setattr(TOOL, '_assert_root', lambda: None)
    monkeypatch.setattr(TOOL, '_load_env_file', lambda path: None)
    monkeypatch.setattr(TOOL, '_use_deployed_tree', lambda: False)
    monkeypatch.setattr(TOOL, '_become_service_user', lambda: None)
    state = SimpleNamespace(feedback_store=object(), site_feedback_store=store)
    monkeypatch.setattr(TOOL, '_load_state', lambda: state)
    assert TOOL.main(['--feedback-id', SITE_ID, '--site', '--status', 'fixed',
                      '--memo', 'memo', '--apply']) == 0
    assert store.status == [(SITE_ID, 'fixed')] and store.memo == [(SITE_ID, 'memo')]
    output = capsys.readouterr().out
    assert f'feedback={SITE_ID}' in output and 'status=fixed' in output and 'ok=true' in output
    assert 'memo' not in output.replace('memo=set', '')