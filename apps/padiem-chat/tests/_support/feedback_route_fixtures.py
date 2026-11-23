"""#8061: shared in-process feedback route fixtures.

Moved verbatim from ``test_7680_feedback_routes.py`` so sibling test modules stop
importing a test file. Values, headers and assertions are unchanged.
"""
from __future__ import annotations

import json
import secrets
from types import SimpleNamespace

from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from _support.feedback_store import OWNER, OTHER

BASE = 'https://chat.example.test'
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret=secrets.token_urlsafe(32), feedback_daily_limit=2)


class AdminAuthority:
    async def is_global_model_admin(self, *, user_id):
        return user_id == OTHER


def request(store, *, method='GET', user=OWNER, body=None, path='/api/chat/feedback',
            feedback_id='', query='', origin=BASE):
    state = SimpleNamespace(settings=SETTINGS, history_store=object(), feedback_store=store,
                            central_model_admin_authorizer=AdminAuthority())
    headers = [(b'content-type', b'application/json')]
    if user:
        token = create_session_token(SETTINGS, user, canonical_session_id="session_test_a")
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    if origin is not None:
        headers.append((b'origin', origin.encode()))
    data = json.dumps(body or {}, ensure_ascii=True).encode()
    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}
    return Request({'type': 'http', 'method': method, 'path': path,
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {'feedback_id': feedback_id}}, receive)


def payload(response):
    return json.loads(response.body)
