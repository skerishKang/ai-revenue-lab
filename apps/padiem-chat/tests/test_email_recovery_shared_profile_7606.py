"""A recovery callback may discard only a deleted, stale legacy identity."""
import asyncio
from types import SimpleNamespace

import pytest

from app.history import D1HistoryStore, _password_user_id
from app.shared_profile_provision import provision_shared_profile
from test_email_recovery_7606 import ACCOUNT, EMAIL, EPOCH, build, complete, issue


class Verifier:
    def __init__(self, account=ACCOUNT, amr=None):
        self.account = account
        self.amr = ['pwd'] if amr is None else amr

    async def verify(self, _token):
        return {'accountId': self.account, 'amr': self.amr}


def recovered():
    app, db, mail = build()
    assert issue(app).status_code == 200
    answer = complete(app, mail.token())
    assert answer.status_code == 200
    return app, db, answer.json()['product_user_id']


def provision(app, db, user_id, legacy, *, account=ACCOUNT, amr=None, store=None):
    request = SimpleNamespace(app=app)
    notified = []

    async def notify(_request, user):
        notified.append(user)

    asyncio.run(provision_shared_profile(
        request, user_id, 'synthetic-access',
        {'account_id': account, 'profile': {'email': EMAIL, 'email_verified': False, 'name': '', 'picture': ''}},
        verifier=Verifier(account, amr), store=store or D1HistoryStore(db),
        legacy_user=lambda _: legacy, notify=notify,
    ))
    return notified


@pytest.mark.parametrize('legacy', [_password_user_id(EMAIL), 'usr_' + 'b' * 32])
def test_mail_proven_recovery_discards_a_missing_previous_local_user(legacy):
    app, db, user_id = recovered()
    assert user_id != legacy
    assert provision(app, db, user_id, legacy) == [user_id]
    assert db.connection.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 1


@pytest.mark.parametrize('reason', ['live_legacy', 'no_proof', 'other_account', 'epoch_changed', 'switch_off', 'google_amr'])
def test_recovery_exception_keeps_other_identity_conflicts_closed(reason):
    app, db, user_id = recovered()
    legacy = _password_user_id(EMAIL)
    kwargs = {}
    if reason == 'live_legacy':
        db.connection.execute(
            "INSERT INTO users(id,auth_provider,provider_subject,email,display_name,picture_url,created_at,updated_at) "
            "VALUES (?,'google','different-subject','other@example.invalid','Other','',?,?)", (legacy, EPOCH, EPOCH))
    elif reason == 'no_proof':
        db.connection.execute('DELETE FROM password_recovery_tokens')
    elif reason == 'other_account':
        kwargs['account'] = 'sub_other'
    elif reason == 'epoch_changed':
        db.connection.execute('UPDATE password_credentials SET created_at=?', ('2026-11-13T00:00:00+00:00',))
    elif reason == 'switch_off':
        object.__setattr__(app.state.settings, 'email_recovery_enabled', False)
    elif reason == 'google_amr':
        kwargs['amr'] = ['google']
    with pytest.raises(ValueError, match='legacy_account_conflict'):
        provision(app, db, user_id, legacy, **kwargs)


def test_recovery_exception_fails_closed_when_local_absence_cannot_be_proved():
    app, db, user_id = recovered()
    store = D1HistoryStore(db)

    async def unavailable(_user):
        raise RuntimeError('synthetic store failure')

    store.user_row_exists = unavailable
    with pytest.raises(ValueError, match='legacy_account_conflict'):
        provision(app, db, user_id, _password_user_id(EMAIL), store=store)
