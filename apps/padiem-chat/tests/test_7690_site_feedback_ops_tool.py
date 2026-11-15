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
FAKE_ACCOUNT = 'usr_' + 'e' * 32
MISSING_ACCOUNT = 'usr_' + '9' * 32
FB_ID = 'fb_' + 'f' * 32


class FakeSiteAdmin:
    def __init__(self):
        self.held = {}
        self.assign_calls = []
        self.unassign_calls = []

    async def is_site_admin(self, *, user_id, site):
        return site in self.held.get(user_id, set())

    async def assign(self, *, user_id, site, now=None):
        self.assign_calls.append((user_id, site))
        if user_id == MISSING_ACCOUNT:
            return 'missing'
        held = self.held.setdefault(user_id, set())
        if site in held:
            return 'already'
        held.add(site)
        return 'assigned'

    async def unassign(self, *, user_id, site):
        self.unassign_calls.append((user_id, site))
        held = self.held.get(user_id, set())
        if site not in held:
            return 'not-assigned'
        held.discard(site)
        return 'removed'

    async def sites_for(self, *, user_id):
        return frozenset(self.held.get(user_id, set()))


class FakeChatFeedback:
    async def get_record(self, feedback_id):
        return SimpleNamespace(user_id=FAKE_ACCOUNT)


class FakeSite:
    def __init__(self):
        self.record = SimpleNamespace(site='miraen-home', status='new', ops_memo=None,
                                      created_at='2026-11-15T16:30:35Z', body='가려진-본문-내용')
        self.status = []
        self.memo = []

    async def get_record(self, feedback_id):
        return self.record

    async def set_status(self, feedback_id, status):
        self.status.append((feedback_id, status))
        self.record = SimpleNamespace(site=self.record.site, status=status, ops_memo=self.record.ops_memo,
                                      created_at=self.record.created_at, body=self.record.body)
        return self.record

    async def set_ops_memo(self, feedback_id, memo):
        self.memo.append((feedback_id, memo))
        self.record = SimpleNamespace(site=self.record.site, status=self.record.status, ops_memo=memo,
                                      created_at=self.record.created_at, body=self.record.body)
        return self.record


def test_site_preview_and_apply_do_not_echo_body_or_memo():
    store = FakeSite()
    preview = asyncio.run(TOOL.run_feedback(store, SITE_ID, status='fixed', memo='memo-text'))
    assert store.status == [] and store.memo == []
    assert preview['lines'][:4] == [f'feedback={SITE_ID}', 'site=miraen-home',
                                    'received=2026-11-15T16:30:35Z', 'status=new']
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


def test_site_admin_add_preview_then_apply():
    authorizer, feedback = FakeSiteAdmin(), FakeChatFeedback()
    preview = asyncio.run(TOOL.run_site_admin(authorizer, feedback, 'add', 'miraen-home', feedback_id=FB_ID))
    assert authorizer.assign_calls == []
    assert preview['lines'][:4] == [f'feedback={FB_ID}', 'site=miraen-home', 'action=add', 'target=feedback']
    assert 'before=no' in preview['lines'] and 'after=no' in preview['lines'] and 'result=ready' in preview['lines']
    assert FAKE_ACCOUNT not in preview['lines']
    applied = asyncio.run(TOOL.run_site_admin(authorizer, feedback, 'add', 'miraen-home', feedback_id=FB_ID, apply=True))
    assert 'result=assigned' in applied['lines'] and 'after=yes' in applied['lines'] and 'sites=1' in applied['lines']
    assert FAKE_ACCOUNT not in applied['lines']
    again = asyncio.run(TOOL.run_site_admin(authorizer, feedback, 'add', 'miraen-home', feedback_id=FB_ID, apply=True))
    assert 'result=already' in again['lines'] and 'before=yes' in again['lines']


def test_site_admin_remove_and_not_assigned():
    authorizer, feedback = FakeSiteAdmin(), FakeChatFeedback()
    untouched = asyncio.run(TOOL.run_site_admin(authorizer, feedback, 'remove', 'miraen-home', feedback_id=FB_ID, apply=True))
    assert 'result=not-assigned' in untouched['lines'] and authorizer.unassign_calls == []
    asyncio.run(TOOL.run_site_admin(authorizer, feedback, 'add', 'miraen-home', feedback_id=FB_ID, apply=True))
    applied = asyncio.run(TOOL.run_site_admin(authorizer, feedback, 'remove', 'miraen-home', feedback_id=FB_ID, apply=True))
    assert 'result=removed' in applied['lines'] and 'after=no' in applied['lines'] and 'sites=0' in applied['lines']
    preview = asyncio.run(TOOL.run_site_admin(authorizer, feedback, 'remove', 'miraen-home', feedback_id=FB_ID))
    assert 'result=not-assigned' in preview['lines']


def test_site_admin_account_path_missing_and_validation():
    authorizer = FakeSiteAdmin()
    preview = asyncio.run(TOOL.run_site_admin(authorizer, None, 'add', 'miraen-home', account=FAKE_ACCOUNT))
    assert 'target=account' in preview['lines'] and 'result=ready' in preview['lines']
    assert FAKE_ACCOUNT not in preview['lines']
    missing = asyncio.run(TOOL.run_site_admin(authorizer, None, 'add', 'miraen-home', account=MISSING_ACCOUNT, apply=True))
    assert 'result=account-missing' in missing['lines'] and missing['error'] == 'USER_NOT_FOUND'
    for kwargs in ({'action': 'add', 'site': 'miraen-home'},
                   {'action': 'add', 'site': 'miraen-home', 'feedback_id': FB_ID, 'account': FAKE_ACCOUNT},
                   {'action': 'add', 'site': 'other-site', 'account': FAKE_ACCOUNT},
                   {'action': 'add', 'site': 'miraen-home', 'feedback_id': SITE_ID},
                   {'action': 'add', 'site': 'miraen-home', 'account': 'bad'},
                   {'action': 'grant', 'site': 'miraen-home', 'account': FAKE_ACCOUNT}):
        with pytest.raises(TOOL.ToolError):
            asyncio.run(TOOL.run_site_admin(authorizer, FakeChatFeedback(), **kwargs))


def test_main_site_admin_cli(monkeypatch, capsys):
    authorizer, feedback, chat_feedback = FakeSiteAdmin(), FakeChatFeedback(), FakeSite()
    monkeypatch.setattr(TOOL, '_assert_root', lambda: None)
    monkeypatch.setattr(TOOL, '_load_env_file', lambda path: None)
    monkeypatch.setattr(TOOL, '_use_deployed_tree', lambda: False)
    monkeypatch.setattr(TOOL, '_become_service_user', lambda: None)
    state = SimpleNamespace(feedback_store=chat_feedback, site_feedback_store=object(),
                            site_feedback_admin_authorizer=authorizer)
    monkeypatch.setattr(TOOL, '_load_state', lambda: state)
    assert TOOL.main(['--site-admin-add', 'miraen-home', '--account', FAKE_ACCOUNT]) == 0
    output = capsys.readouterr().out
    assert 'result=ready' in output and 'ok=true' in output and FAKE_ACCOUNT not in output
    assert TOOL.main(['--site-admin-add', 'miraen-home', '--account', FAKE_ACCOUNT, '--apply']) == 0
    assert 'result=assigned' in capsys.readouterr().out
    assert TOOL.main(['--site-admin-add', 'miraen-home', '--status', 'fixed']) == 1
    assert 'STOP NOT_APPLICABLE' in capsys.readouterr().out
    assert TOOL.main(['--site-admin-add', 'miraen-home', '--site-admin-remove', 'miraen-home']) == 1
    assert 'STOP ACTION_CONFLICT' in capsys.readouterr().out
    assert TOOL.main(['--feedback-id', FB_ID, '--status', 'fixed', '--apply']) == 0
    assert 'status=fixed' in capsys.readouterr().out
    assert TOOL.main(['--status', 'fixed']) == 1
    assert 'STOP FEEDBACK_ID_REQUIRED' in capsys.readouterr().out
    state.site_feedback_admin_authorizer = None
    assert TOOL.main(['--site-admin-add', 'miraen-home', '--account', FAKE_ACCOUNT]) == 1
    assert 'STOP SITE_ADMIN_STORE_UNAVAILABLE' in capsys.readouterr().out