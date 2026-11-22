"""#7690: a site-feedback receipt journals one ops line, a refusal journals the
site and the closed reason code, and the ops tool shows the received time.
Bodies never appear in the journal or the tool output."""
import asyncio
import re

from app.d1_sqlite import SqliteD1
from app.site_feedback_routes import site_feedback
from app.site_feedback_store import D1SiteFeedbackStore
from _support.feedback_store import database
from test_7690_site_feedback_ops_tool import SITE_ID, TOOL, FakeSite
from test_7690_site_feedback_routes import BODY, ORIGIN, SETTINGS_LIMIT, request

RECEIVED = re.compile(r"site_feedback_received site=miraen-home id=sf_[0-9a-f]{32}\Z")
REJECTED_400 = 'site_feedback_rejected site=miraen-home reason=feedback_invalid_request'
REJECTED_429 = 'site_feedback_rejected site=miraen-home reason=feedback_daily_limit'
MARKER = '고유한-본문-마커'


def _body(now_ms, **overrides):
    value = {'site': 'miraen-home', 'body': BODY + ' ' + MARKER,
             'screen': {'url': ORIGIN + '/', 'width': 390, 'height': 844},
             'rendered_at': now_ms - 2000, 'honeypot': ''}
    value.update(overrides)
    return value


def test_a_receipt_journals_one_line_without_the_body(monkeypatch, capsys):
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            now_ms = 1_700_000_000_000
            monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: now_ms)
            monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-15T00:00:00Z')
            created = await site_feedback(request(store, method='POST', body=_body(now_ms)))
            assert created.status_code == 201
            lines = capsys.readouterr().out.strip().splitlines()
            assert len(lines) == 1 and RECEIVED.fullmatch(lines[0]), lines
            # The receipt id is random hex, so a width-like digit run ('390')
            # can legitimately appear inside it; the leak check targets the
            # label part the journal composes, never the id.
            assert MARKER not in lines[0] and ORIGIN not in lines[0]
            assert '390' not in lines[0].partition('id=sf_')[0]
        finally:
            db.close()
    asyncio.run(scenario())


def test_a_refusal_journals_the_site_and_the_closed_reason_only(monkeypatch, capsys):
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            now_ms = 1_700_000_000_000
            monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: now_ms)
            monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-15T00:00:00Z')
            body = _body(now_ms)
            for _ in range(2):
                first = await site_feedback(request(store, method='POST', body=body,
                                                    settings=SETTINGS_LIMIT, ip='203.0.113.1'))
                assert first.status_code == 201
            limited = await site_feedback(request(store, method='POST', body=body,
                                                  settings=SETTINGS_LIMIT, ip='203.0.113.7'))
            assert limited.status_code == 429
            bad = await site_feedback(request(store, method='POST', body={**body, 'honeypot': 'x'},
                                              settings=SETTINGS_LIMIT, ip='203.0.113.7'))
            assert bad.status_code == 400
            lines = capsys.readouterr().out.strip().splitlines()
            assert lines[-2] == REJECTED_429 and lines[-1] == REJECTED_400, lines
            assert sum(1 for line in lines if line.startswith('site_feedback_received ')) == 2
            assert all(MARKER not in line and ORIGIN not in line for line in lines)
        finally:
            db.close()
    asyncio.run(scenario())


def test_an_unregistered_site_journals_nothing(monkeypatch, capsys):
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            now_ms = 1_700_000_000_000
            monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: now_ms)
            monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-15T00:00:00Z')
            # An unregistered site (here with an injected newline) is refused
            # without a journal line: nothing unvalidated reaches the journal.
            refused = await site_feedback(request(
                store, method='POST', body=_body(now_ms, site='other-site\nline')))
            assert refused.status_code == 400
            assert capsys.readouterr().out == ''
        finally:
            db.close()
    asyncio.run(scenario())


def test_the_tool_shows_the_received_time_and_never_the_body():
    store = FakeSite()
    preview = asyncio.run(TOOL.run_feedback(store, SITE_ID, status='fixed', memo='memo-text'))
    assert [line for line in preview['lines'] if line.startswith('received=')] == \
        ['received=2026-11-15T16:30:35Z']
    assert '가려진-본문-내용' not in preview['lines']
    applied = asyncio.run(TOOL.run_feedback(store, SITE_ID, status='fixed', memo='memo-text', apply=True))
    assert applied['lines'].count('received=2026-11-15T16:30:35Z') == 1
    assert '가려진-본문-내용' not in applied['lines']
    # The record carries a body the whole time; the tool simply never reads it out.
    assert store.record.body == '가려진-본문-내용'
