import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import patch

from app.shared_auth_compare_flow import create_worker_comparison_flow


class Secret:
    def __init__(self, value):
        self.value = value
        self.reads = 0
    async def get(self):
        self.reads += 1
        return self.value


def test_default_off_does_not_read_any_secret():
    private, state = Secret('synthetic'), Secret('synthetic')
    env = SimpleNamespace(PADIEM_CHAT_SHARED_AUTH_COMPARE_ENABLED='false',
        PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK=private,
        PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY=state)
    assert asyncio.run(create_worker_comparison_flow(env, object())) is None
    assert private.reads == state.reads == 0


def test_enabled_resolves_both_bindings_and_fails_closed_without_them(capsys):
    private = Secret('{"kty":"EC","crv":"P-256","x":"a","y":"b","d":"c"}')
    state = Secret(base64.urlsafe_b64encode(b'x' * 32).rstrip(b'=').decode())
    env = SimpleNamespace(PADIEM_CHAT_SHARED_AUTH_COMPARE_ENABLED='true',
        PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK=private,
        PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY=state,
        PADIEM_CHAT_SHARED_AUTH_CLIENT_KID='synthetic')
    sentinel = object()
    with patch('app.shared_auth_compare_flow.create_chat_comparison_flow', return_value=sentinel):
        assert asyncio.run(create_worker_comparison_flow(env, object())) is sentinel
    assert private.reads == state.reads == 1
    state.value = None
    assert asyncio.run(create_worker_comparison_flow(env, object())) is None
    output = capsys.readouterr().out
    assert output == 'shared_auth_comparison: unavailable\n'
    assert 'synthetic' not in output
