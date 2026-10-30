import asyncio
import base64
import json
import unittest
from unittest.mock import patch
import sys
import types
from http.cookies import SimpleCookie
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from starlette.datastructures import QueryParams
from starlette.applications import Starlette
import httpx
import app

from app.shared_auth_compare_flow import CALLBACK, COOKIE, TOKEN_URL, ComparisonFlow, exchange_with_httpx
from tests.shared_es256_test_crypto import TestES256


def b64int(value):
    return base64.urlsafe_b64encode(value.to_bytes(32, 'big')).rstrip(b'=').decode()


def jwk():
    key = ec.generate_private_key(ec.SECP256R1()).private_numbers()
    return {'kty':'EC', 'crv':'P-256', 'd':b64int(key.private_value),
            'x':b64int(key.public_numbers.x), 'y':b64int(key.public_numbers.y)}


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.user = 'usr_synthetic'
        self.calls = []
        async def exchange(url, data):
            self.calls.append((url, data))
            return {'access_token':'synthetic-access'}
        async def compare(request, token):
            self.assertEqual(token, 'synthetic-access')
            return 'MATCH'
        self.jwk = jwk()
        self.flow = ComparisonFlow(state_key=b's' * 32, client_id='b62', client_jwk=self.jwk,
            kid='synthetic-kid', operator_guard=lambda r: True, legacy_user=lambda r: self.user,
            comparator=compare, exchange=exchange, crypto=TestES256(), clock=lambda:self.now)

    def run_flow(self, value):
        return asyncio.run(value)

    def start(self):
        response = self.run_flow(self.flow.start(SimpleNamespace()))
        cookie = SimpleCookie()
        cookie.load(response.headers['set-cookie'])
        target = urlsplit(response.headers['location'])
        params = parse_qs(target.query)
        return response, cookie[COOKIE].value, params

    def callback(self, cookie, state, code='synthetic-code'):
        request = SimpleNamespace(cookies={COOKIE:cookie}, query_params=QueryParams({'state':state,'code':code}))
        return self.run_flow(self.flow.callback(request))

    def test_default_off_and_bound_code_exchange(self):
        self.assertEqual(self.flow.routes(), [])
        self.assertEqual(len(self.flow.routes(enabled=True)), 2)
        response, cookie, params = self.start()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(params['redirect_uri'], [CALLBACK])
        self.assertEqual(params['code_challenge_method'], ['S256'])
        result = self.callback(cookie, params['state'][0])
        self.assertEqual(json.loads(result.body), {'result':'MATCH'})
        self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertNotIn(b'synthetic-access', result.body)
        self.assertEqual(len(self.calls), 1)
        sent = self.calls[0][1]
        digest = base64.urlsafe_b64encode(__import__('hashlib').sha256(sent['code_verifier'].encode()).digest()).rstrip(b'=').decode()
        self.assertEqual(digest, params['code_challenge'][0])

    def test_bad_state_wrong_user_and_expiry_never_exchange(self):
        _, cookie, params = self.start()
        state = params['state'][0]
        for check in ('bad_state', 'wrong_user', 'expired'):
            self.user = 'different' if check == 'wrong_user' else 'usr_synthetic'
            self.now = 1601 if check == 'expired' else 1000
            result = self.callback(cookie, 'bad' if check == 'bad_state' else state)
            self.assertEqual(json.loads(result.body), {'result':'UNKNOWN'})
        self.assertEqual(self.calls, [])

    def test_wrong_operator_cannot_start_or_exchange(self):
        _, cookie, params = self.start()
        self.flow.guard = lambda r: False
        self.assertEqual(self.run_flow(self.flow.start(SimpleNamespace())).status_code, 403)
        self.assertEqual(json.loads(self.callback(cookie, params['state'][0]).body), {'result':'UNKNOWN'})
        self.assertEqual(self.calls, [])

    def test_client_assertion_has_auth_contract_and_valid_es256_signature(self):
        encoded = self.run_flow(self.flow._assertion(self.now))
        head, body, signature = encoded.split('.')
        decode = lambda value: base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
        claims = json.loads(decode(body))
        self.assertEqual(claims['aud'], 'https://auth.padiem.net/token')
        self.assertEqual(claims['iss'], 'b62')
        raw = decode(signature)
        der = encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        private = ec.derive_private_key(int.from_bytes(decode(self.jwk['d']), 'big'), ec.SECP256R1())
        private.public_key().verify(der, (head + '.' + body).encode(), ec.ECDSA(hashes.SHA256()))

    def test_bound_flow_runs_through_an_isolated_asgi_app(self):
        async def scenario():
            app = Starlette(routes=self.flow.routes(enabled=True))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url='https://chat.padiem.net') as client:
                start = await client.get('/_test/auth/account-comparison/start')
                state = parse_qs(urlsplit(start.headers['location']).query)['state'][0]
                response = await client.get('/_test/auth/account-comparison/callback',
                                            params={'state':state, 'code':'synthetic-code'})
                self.assertEqual(response.json(), {'result':'MATCH'})
                self.assertEqual(response.headers['cache-control'], 'no-store')
        self.run_flow(scenario())

    def test_exchange_uses_workers_compatible_stream_and_fixed_url(self):
        seen = []
        class Response:
            status_code = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def aiter_bytes(self):
                yield b'{"access_token":"synthetic"}'
        class Client:
            def __init__(self, **kwargs): self.options = kwargs
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            def stream(self, method, url, **kwargs):
                seen.append((method, url, self.options))
                return Response()
        shim = types.ModuleType('app.httpx_compat')
        shim.AsyncClient = Client
        auth = types.ModuleType('app.auth')
        auth.MAX_AUTH_RESPONSE_BYTES = 1024 * 1024
        with patch.dict(sys.modules, {'app.httpx_compat':shim, 'app.auth':auth}):
            with patch.object(app, 'httpx_compat', shim, create=True):
                result = self.run_flow(exchange_with_httpx(TOKEN_URL, {'code':'synthetic'}))
                with self.assertRaises(ValueError):
                    self.run_flow(exchange_with_httpx('https://invalid.example/token', {}))
        self.assertEqual(result, {'access_token':'synthetic'})
        self.assertEqual(seen, [('POST',TOKEN_URL,{'follow_redirects':False})])
